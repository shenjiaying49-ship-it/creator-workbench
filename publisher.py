"""多平台发布器
方案来源（GitHub 实测选型，取最简可用路径）：
- X: twikit（github.com/d60/twikit，4707★，免官方 API key，用账号登录一次后走内部接口）
- Threads: 官方 API 需要 Meta 开发者应用审核；v1 用 threads.net intent 链接（带文一键打开发布框，剩一次点击）
- 抖音: 图文/口播稿阶段用创作者中心半自动；有成品视频后接 dreammis/social-auto-upload（15280★，Playwright+cookies）
- 小红书: 按用户要求保持手动发布
"""
import json
import os
import urllib.parse

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
X_COOKIES = os.path.join(DATA, "x_cookies.json")


def _load_config():
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def split_thread(text, limit=275):
    """把长文切成 ≤280 字符的多条推文，按段落边界切，自动编号"""
    parts = [p.strip() for p in (text or "").replace("— — —", "\n").split("\n\n") if p.strip()]
    tweets, cur = [], ""
    for p in parts:
        while len(p) > limit:  # 单段超长兜底：硬切
            head, p = p[:limit], p[limit:]
            if cur:
                tweets.append(cur)
                cur = ""
            tweets.append(head)
        if not p:
            continue
        if len(cur) + len(p) + 2 <= limit:
            cur = (cur + "\n\n" + p).strip()
        else:
            if cur:
                tweets.append(cur)
            cur = p
    if cur:
        tweets.append(cur)
    return [f"{i+1}/{len(tweets) if len(tweets) > 1 else ''} {t}".strip() if len(tweets) > 1 else t
            for i, t in enumerate(tweets)]


def x_configured():
    pc = _load_config().get("publish", {}).get("x", {})
    return bool(pc.get("username") and pc.get("password"))


def publish_x(text):
    """X 发帖。已配置账号 → twikit 自动发并缓存 cookies；否则返回 intent 预填链接。"""
    intent = "https://x.com/intent/post?text=" + urllib.parse.quote((text or "")[:2500])
    if not x_configured():
        return {"ok": False, "mode": "intent", "url": intent,
                "msg": "X 账号未配置，已生成带文预填链接（一键打开发布框）。要全自动发帖，把 X 用户名/邮箱/密码填进 config.json 的 publish.x"}
    try:
        from twikit import Client
    except ImportError:
        return {"ok": False, "mode": "intent", "url": intent, "msg": "twikit 未安装（.venv 缺依赖）"}
    pc = _load_config().get("publish", {}).get("x", {})
    client = Client("zh-CN")
    try:
        if os.path.exists(X_COOKIES):
            client.load_cookies(X_COOKIES)
        else:
            client.login(auth_info_1=pc["username"], auth_info_2=pc.get("email", pc["username"]),
                         password=pc["password"])
            client.save_cookies(X_COOKIES)
        tweets = split_thread(text)
        first = client.create_tweet(text=tweets[0])
        reply = first
        for t in tweets[1:]:
            reply = client.create_tweet(text=t, reply_to=reply.id)
        screen = getattr(getattr(first, "user", None), "screen_name", "") or ""
        return {"ok": True, "mode": "auto",
                "url": f"https://x.com/{screen}/status/{first.id}" if screen else "",
                "msg": f"已发布 X thread（{len(tweets)} 条）"}
    except Exception as e:
        return {"ok": False, "mode": "intent", "url": intent,
                "msg": f"自动发布失败（{str(e)[:120]}），已降级为预填链接"}


def publish_threads(text):
    """Threads：intent 链接带文打开发布框（免密钥最简路径）。"""
    first = (text or "").split("— — —")[0].strip()
    url = "https://www.threads.net/intent/post?text=" + urllib.parse.quote(first[:480])
    return {"ok": False, "mode": "intent", "url": url,
            "msg": "已打开 Threads 发布框并预填文字，确认后点发送即可（自动直发需接 Meta 官方 API，要建开发者应用）"}


def publish_douyin(post):
    """抖音：口播稿阶段 → 打开创作者中心 + 文案给剪贴板；有视频文件后接 social-auto-upload。"""
    return {"ok": False, "mode": "manual",
            "url": "https://creator.douyin.com/creator-micro/content/upload",
            "msg": "抖音需要视频成片：文案已准备好，拍摄后上传。自动上传可接 social-auto-upload（需 cookies 登录一次）"}


def publish(post, platform):
    if platform == "小红书":
        return {"ok": False, "mode": "manual", "url": "https://creator.xiaohongshu.com/publish/publish",
                "msg": "小红书按你的要求保持手动发布"}
    if platform == "X":
        text = post.get("body", "") or post.get("title", "")
        if post.get("tags"):
            text += "\n\n" + " ".join(post["tags"])
        return publish_x(text)
    if platform == "Threads":
        return publish_threads(post.get("body", ""))
    if platform == "抖音":
        return publish_douyin(post)
    return {"ok": False, "mode": "none", "msg": f"未知平台 {platform}"}
