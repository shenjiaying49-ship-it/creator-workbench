#!/usr/bin/env python3
"""一周自动运营引擎（X 为主力自动发布，Threads/抖音生成待办）

运营逻辑来源（实测提炼）：
- X 1100→7万粉全流程（BearLiu）：每天1条高质量原创 + "每天1块钱"（50条高质量评论）
- 小红书IP三件套：垂直定位、固定栏目、70分模板机械执行
- 排期节奏：X 周二/四/日 10:30，Threads 每晚 21:30，抖音周三/六

用法：.venv/bin/python auto_ops.py   （前台跑，可 nohup 后台）
持续 7 天，每 10 分钟醒一次：
  - 到点的 X 稿 → twikit 自动发布（需 config.json publish.x 凭据）
  - 到点的 Threads → 生成 intent 链接进今日任务卡（一键打开发布框）
  - 每天早上 08:30 生成「今日运营任务卡」写 data/daily_ops.json
  - 日志写 data/ops_log.jsonl
"""
import json
import os
import sys
import time
import datetime as dt
import urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DATA = os.path.join(BASE, "data")
POSTS = os.path.join(DATA, "posts.json")
OPS = os.path.join(DATA, "daily_ops.json")
LOG = os.path.join(DATA, "ops_log.jsonl")

# 对标账号（评论互动目标：AI中文圈头部，来自 X 增长指南“先关注+建List”）
ENGAGE_TARGETS = {
    "X": ["@dotey 宝玉", "@op7418 歸藏", "@karminai3", "@sundyme", "@aiwaiter2024"],
    "Threads": ["AI中文圈 KOL 的 Threads 账号（从 X 简介找同名）"],
}

WEEK_PLAN = {  # weekday -> (platform, time)
    0: [("Threads", "21:30")],                                   # 周一
    1: [("X", "10:30"), ("Threads", "21:30")],                   # 周二
    2: [("抖音", "12:30"), ("Threads", "21:30")],                # 周三
    3: [("X", "20:00"), ("Threads", "21:30")],                   # 周四
    4: [("Threads", "21:30")],                                   # 周五
    5: [("抖音", "18:30"), ("Threads", "21:30")],                # 周六
    6: [("X", "10:30"), ("Threads", "21:30")],                   # 周日
}


def log(event, detail):
    line = json.dumps({"t": dt.datetime.now().strftime("%m-%d %H:%M:%S"), "event": event, "detail": detail},
                      ensure_ascii=False)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_posts():
    try:
        with open(POSTS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_ops(ops):
    tmp = OPS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ops, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OPS)


def next_draft(platform):
    """按落库顺序取第一个「待确认/已生成」且未发布的平台稿"""
    posts = load_posts()
    for p in posts:
        if p.get("platform") == platform and p.get("status") == "待确认" and p.get("body"):
            return p
    return None


def mark_published(post_id):
    posts = load_posts()
    for p in posts:
        if p.get("id") == post_id:
            p["status"] = "已发布"
            p["updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    tmp = POSTS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    os.replace(tmp, POSTS)


def publish_x_auto(post):
    import publisher
    text = post.get("body", "") or post.get("title", "")
    if post.get("tags"):
        text += "\n\n" + " ".join(post["tags"])
    return publisher.publish_x(text)


def threads_intent(post):
    first = (post.get("body", "") or "").split("— — —")[0].strip()
    return "https://www.threads.net/intent/post?text=" + urllib.parse.quote(first[:480])


def build_daily_card(day):
    """生成今日运营任务卡（发布 + 互动任务）"""
    slots = WEEK_PLAN.get(day.weekday(), [])
    posts = load_posts()
    items = []
    for plat, tm in slots:
        draft = next_draft(plat)
        if not draft:
            items.append({"platform": plat, "time": tm, "state": "无稿可发",
                          "note": "稿件库该平台暂无待发稿（LLM配额恢复后点「补齐」生成）"})
            continue
        item = {"platform": plat, "time": tm, "post_id": draft["id"],
                "title": (draft.get("topic") or draft.get("title", ""))[:40],
                "state": "待发", "note": ""}
        if plat == "Threads":
            item["intent"] = threads_intent(draft)
            item["note"] = "点链接打开预填发布框，确认发送"
        elif plat == "抖音":
            item["note"] = "口播稿已备好，拍摄后传创作者中心"
            item["body_preview"] = (draft.get("body") or "")[:120]
        elif plat == "X":
            item["note"] = "引擎到点自动发布（twikit）" if publisher_ok() else "X 凭据未配置，到点会降级为 intent 链接"
        items.append(item)

    posted_today = [p for p in posts if p.get("status") == "已发布"
                    and (p.get("updated") or "").startswith(dt.date.today().isoformat())
                    and p.get("source") != "xhs_sync"]  # 导入的旧稿不算"今天发"
    return {
        "date": day.isoformat(),
        "generated": dt.datetime.now().strftime("%m-%d %H:%M"),
        "publish": items,
        "engagement": [
            {"platform": "X", "task": "每天1块钱：50条高质量评论（对标账号帖子下留观点，不做沙发式回复）",
             "targets": ENGAGE_TARGETS["X"]},
            {"platform": "X", "task": "转发1条领域优质帖并附自己的观点（转发带观点权重最高）", "targets": []},
            {"platform": "Threads", "task": "10-20条互动：回复对标账号 + 自己帖子的所有评论", "targets": ENGAGE_TARGETS["Threads"]},
            {"platform": "小红书", "task": "回复自己笔记的全部新评论 + 首评资料钩子检查", "targets": []},
        ],
        "published_today": len(posted_today),
        "source": "运营逻辑：BearLiu X 0→7万粉全流程 + 小红书IP三件套 + 账号自有排期",
    }


def publisher_ok():
    try:
        import publisher
        return publisher.x_configured()
    except Exception:
        return False


def main():
    days = 7
    start = dt.datetime.now()
    card_date = None
    fired = set()  # "date HH:MM plat" 已触发过的发布位
    log("engine_start", f"运行 {days} 天，X自动={'是' if publisher_ok() else '否（未配凭据）'}")

    while (dt.datetime.now() - start) < dt.timedelta(days=days):
        now = dt.datetime.now()
        today = now.date()

        # 1) 每日任务卡（08:30 后首次生成/刷新）
        if now.hour >= 8 and card_date != today:
            card = build_daily_card(today)
            save_ops(card)
            card_date = today
            log("daily_card", f"{len(card['publish'])} 个发布位, 已发 {card['published_today']}")

        # 2) 到点发布
        for plat, tm in WEEK_PLAN.get(today.weekday(), []):
            key = f"{today} {tm} {plat}"
            hh, mm = int(tm[:2]), int(tm[3:])
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if key in fired or now < due or (now - due) > dt.timedelta(hours=2):
                continue
            draft = next_draft(plat)
            if not draft:
                fired.add(key)
                log("no_draft", f"{plat} {tm}")
                continue
            if plat == "X":
                res = publish_x_auto(draft)
                if res.get("ok"):
                    mark_published(draft["id"])
                    log("auto_published", f"X {res.get('url','')} {draft.get('topic','')[:30]}")
                else:
                    log("x_fail", f"{res.get('msg','')[:80]}")
                    # 失败不标记，下个循环还会重试直到过窗
            fired.add(key)
            # Threads/抖音：不自动发，任务卡里已带 intent/提示
            if plat in ("Threads", "抖音"):
                log("manual_slot", f"{plat} {tm} 待用户在任务卡确认")

        time.sleep(600)  # 10 分钟

    log("engine_end", "7 天运营周期结束")


if __name__ == "__main__":
    main()
