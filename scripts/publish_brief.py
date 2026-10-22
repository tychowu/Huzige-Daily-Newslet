#!/usr/bin/env python3
"""
publish_brief.py —— 《胡子哥财经晨报》每日出图 → 上传公网 → 推送微信

三步：
  1) 读当期 cards/card-01..04.png
  2) 上传到 COS 桶 diwu-pru-brief-<APPID>，路径 issue/<日期>/<文件名>
     —— 用日期分层，每天一份，历史可回看，CDN 不会串图
  3) 调 Server酱 API 推送到个人微信（Markdown 里引用公网 URL）

设计约束（都踩过坑才定下来的）：
  · Server酱 **不支持 base64 推本地图片**，本地图必须先有公网 URL。
    所以顺序只能是「先上传 → 拿到 URL → 再推送」，不能反。
  · 图片 URL 里的日期目录必须变，否则浏览器/CDN 缓存会给你返回昨天的图。
  · SendKey 只从 ~/.workbuddy/serverchan-config.json 读，不进代码、不进日志。
  · 推送内容里不写任何合规敏感词（见 references/checklist.md 合规红线）。

用法：
  python3 publish_brief.py --workdir <简讯工作目录> [--dry-run] [--no-push]
  python3 publish_brief.py --workdir ... --text "自定义配文"

退出码：0 = 成功；2 = 配置缺失；3 = 上传失败；4 = 推送失败但图已上线
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

CONF_COS = os.path.expanduser("~/.workbuddy/diwu-pru-config.json")
CONF_SCT = os.path.expanduser("~/.workbuddy/serverchan-config.json")
BUCKET_PREFIX = "diwu-pru"
# 自定义域名（CDN 加速 + 自己的域名，微信里更不容易被拦图）
BRIEF_SUBDOMAIN = "brief"


def log(t):
    print(t, flush=True)


def fail(msg, code=1):
    print(f"❌ {msg}", flush=True)
    sys.exit(code)


# ── 0. 配置 ──────────────────────────────────────────────────────
def load_cos_conf():
    if not os.path.exists(CONF_COS):
        fail(f"找不到腾讯云配置 {CONF_COS}", 2)
    with open(CONF_COS) as f:
        c = json.load(f)
    return {
        "secretId": c["credentials"]["secretId"],
        "secretKey": c["credentials"]["secretKey"],
        "region": c["deploy"]["region"],
        "domainBase": c["deploy"]["domainBase"],
        "appId": c["account"]["appId"],
    }


def load_sct_conf():
    """SendKey 从独立配置读。没有就只上传不推送（图仍然上线可访问）。"""
    if not os.path.exists(CONF_SCT):
        return None
    with open(CONF_SCT) as f:
        c = json.load(f)
    key = (c.get("sendKey") or "").strip()
    if not key:
        return None
    return key


# ── 1. 收集当期图 ────────────────────────────────────────────────
def collect_cards(workdir):
    """收集当期 4 张图。交付物就是这 4 张，没有拼版预览。"""
    cards_dir = os.path.join(workdir, "cards")
    if not os.path.isdir(cards_dir):
        fail(f"找不到卡片目录 {cards_dir}", 2)
    pngs = []
    for i in range(1, 5):
        p = os.path.join(cards_dir, f"card-{i:02d}.png")
        if not os.path.exists(p):
            fail(f"缺图：{p} —— 先跑 render.cjs", 2)
        pngs.append(p)
    return pngs


# ── 2. 上传 COS ──────────────────────────────────────────────────
def upload(pngs, cos_conf, issue_date):
    """上传到 issue/<日期>/<文件名>，返回公网 URL 列表。"""
    from qcloud_cos import CosConfig, CosS3Client

    bucket = f"{BUCKET_PREFIX}-brief-{cos_conf['appId']}"
    region = cos_conf["region"]
    cos = CosS3Client(CosConfig(
        Region=region,
        SecretId=cos_conf["secretId"],
        SecretKey=cos_conf["secretKey"],
    ))

    # 桶不存在就建（幂等）
    try:
        cos.create_bucket(Bucket=bucket, ACL="public-read")
        log(f"  [OK] 建桶 {bucket}")
    except Exception as e:
        log(f"  [复用] 桶已存在或建桶跳过: {str(e)[:80]}")
    try:
        cos.put_bucket_acl(Bucket=bucket, ACL="public-read")
    except Exception as e:
        log(f"  [WARN] 公有读 ACL 设置失败: {str(e)[:80]}")

    base = f"https://{bucket}.cos.{region}.myqcloud.com"
    cdn_base = f"https://{BRIEF_SUBDOMAIN}.{cos_conf['domainBase']}"
    urls = []
    for p in pngs:
        name = os.path.basename(p)
        key = f"issue/{issue_date}/{name}"
        with open(p, "rb") as fp:
            cos.put_object(Bucket=bucket, Body=fp, Key=key, ContentType="image/png")
        # 优先用自定义域名（CDN）；子域名没上线时退回 COS 默认域名
        url = f"{cdn_base}/{key}"
        urls.append({"name": name, "key": key, "url": url,
                     "fallback_url": f"{base}/{key}",
                     "bytes": os.path.getsize(p)})
        log(f"  [OK] {name}  {os.path.getsize(p)//1024}KB")
    return bucket, urls


# ── 3. 推 Server酱 ───────────────────────────────────────────────
def url_ok(url, timeout=8):
    """HEAD 一下确认可公开取图。CDN 刚建好时可能还没生效，要能退回默认域名。"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def pick_reachable_urls(urls):
    """逐个试自定义域名，不通就退回 COS 默认域名。

    微信对 myqcloud.com 的图片偶尔会拦，优先用自有域名；
    但子域名刚上线时 CDN 可能还没生效，所以要有退路。
    """
    fixed = []
    for u in urls:
        if url_ok(u["url"]):
            u["via"] = "cdn"
        elif url_ok(u["fallback_url"]):
            u["url"] = u["fallback_url"]
            u["via"] = "cos"
            log(f"  [回退] {u['name']} 自定义域名未生效，改用 COS 默认域名")
        else:
            u["via"] = "fail"
            log(f"  [FAIL] {u['name']} 两个域名都取不到")
        fixed.append(u)
    return fixed


def purge_cdn(cos_conf, key_prefix):
    """重传后刷一下 CDN 缓存，否则浏览器/CDN 会给你返回上一次的图。"""
    try:
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.cdn.v20180606 import cdn_client, models as cdn_models
        cred = credential.Credential(cos_conf["secretId"], cos_conf["secretKey"])
        hp = HttpProfile(); hp.reqTimeout = 30
        cp = ClientProfile(); cp.httpProfile = hp
        cdn = cdn_client.CdnClient(cred, cos_conf["region"], cp)
        req = cdn_models.PurgePathCacheRequest()
        req.FlushType = "flush"
        req.Paths = [f"https://{BRIEF_SUBDOMAIN}.{cos_conf['domainBase']}/{key_prefix}"]
        r = cdn.PurgePathCache(req)
        log(f"  [OK] CDN 缓存刷新已提交 (TaskId={getattr(r, 'TaskId', None)})")
    except Exception as e:
        log(f"  [WARN] CDN 刷新失败（不影响推送，日期目录天然避缓存）: {str(e)[:120]}")


def build_desp(title, urls, text, workdir):
    """拼 Markdown 正文：4 张大图 + 配文。

    图片用 ![](url) 引用，Server酱 会渲染成可长按保存的图片卡片。
    """
    lines = [f"### {title}", ""]
    if text:
        lines += [text, ""]
    for u in urls:
        lines.append(f"![{u['name']}]({u['url']})")
        lines.append("")
    lines.append("---")
    lines.append(f"胡子哥财经晨报 · {issue_date_str}")
    return "\n".join(lines)


issue_date_str = ""


def push_serverchan(sendkey, title, desp):
    """Server酱 Turbo: https://sctapi.ftqq.com/<SendKey>.send
    返回 (code, message)。code=0 为成功。

    坑：Server酱 对无效 key 返回 **HTTP 400**（不是 200 + 错误码），
    urllib 会把它当异常抛掉，响应体里的 code=40001 与「错误的Key」提示就丢了。
    所以必须自己捕获 HTTPError 并把 body 读出来，否则真 key 出问题时
    只能看到一句没用的「Bad Request」。
    """
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
    body = ""
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # 4xx/5xx 也带 JSON 响应体，里面才是真正的错误原因
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        if not body:
            return -1, f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return -1, f"请求异常: {str(e)[:200]}"
    try:
        j = json.loads(body)
        return j.get("code", -1), j.get("message") or j.get("info") or body[:200]
    except Exception:
        return -1, body[:200]


# ── main ─────────────────────────────────────────────────────────
def main():
    global issue_date_str

    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True, help="简讯工作目录（含 cards/）")
    ap.add_argument("--date", default="", help="期次日期 YYYYMMDD，默认取 data.json 的 meta.date")
    ap.add_argument("--title", default="", help="推送标题，默认「胡子哥财经晨报 · <日期>」")
    ap.add_argument("--text", default="", help="配文（Markdown）")
    ap.add_argument("--dry-run", action="store_true", help="只打印要发什么，不上传不推送")
    ap.add_argument("--no-push", action="store_true", help="只上传，不推送")
    args = ap.parse_args()

    workdir = os.path.abspath(args.workdir)

    # 期次日期
    issue_date = args.date
    meta = {}
    dj = os.path.join(workdir, "data.json")
    if os.path.exists(dj):
        with open(dj) as f:
            meta = json.load(f).get("meta", {})
    if not issue_date:
        d = (meta.get("date") or "").replace(".", "").replace("-", "")
        issue_date = d or time.strftime("%Y%m%d")
    issue_date_str = meta.get("date") or issue_date
    issue_no = meta.get("issue") or ""

    log("=" * 56)
    log(f" 胡子哥财经晨报 {issue_no} · 发布推送")
    log("=" * 56)
    log(f" 工作目录 : {workdir}")
    log(f" 期次     : {issue_no} / {issue_date_str}")

    pngs = collect_cards(workdir)
    log(f" 待发布   : {len(pngs)} 个文件")

    if args.dry_run:
        log("\n[dry-run] 不上传不推送，流程走通检查完毕。")
        return

    # 上传
    log("\n→ 上传 COS")
    cos_conf = load_cos_conf()
    bucket, urls = upload(pngs, cos_conf, issue_date)
    log(f"  桶: {bucket}")
    purge_cdn(cos_conf, f"issue/{issue_date}/")

    # 确认公网可取（自定义域名优先，不通退回 COS 默认域名）
    log("\n→ 校验公网可访问")
    urls = pick_reachable_urls(urls)
    if any(u.get("via") == "fail" for u in urls):
        fail("有图片公网取不到，不推送（避免推出去是坏图）", 3)

    # 打印 URL 供人工核对
    log("\n  公网 URL:")
    for u in urls:
        log(f"   {u['name']:<22} {u['url']}")

    # 推送
    if args.no_push:
        log("\n[--no-push] 已上传，未推送。")
        return

    sendkey = load_sct_conf()
    if not sendkey:
        log("\n⚠️  没有 SendKey（~/.workbuddy/serverchan-config.json）——图已上线但未推送。")
        log("   去 https://sct.ftqq.com 微信扫码登录 → 复制 SendKey → 写入该文件后重跑。")
        return

    title = args.title or f"胡子哥财经晨报 · {issue_date_str}"
    desp = build_desp(title, urls, args.text, workdir)

    log(f"\n→ 推送 Server酱")
    log(f"  标题: {title}")
    code, msg = push_serverchan(sendkey, title, desp)
    if code == 0:
        log(f"  [OK] 推送成功: {msg}")
        log("\n📱 去微信看「服务器酱」公众号的消息。")
    else:
        log(f"  [FAIL] 推送失败 code={code} msg={msg}")
        log("  图已上线，可用上面的 URL 手动查看。")
        sys.exit(4)


if __name__ == "__main__":
    main()
