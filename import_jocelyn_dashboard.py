#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ego-browser 从小红书创作者后台抓到的 Jocelyn 数据写入工作台：
- posts.json：补齐真实发布的笔记（与已 seed 的对应上则更新，否则新增）
- analytics.json：写入每篇笔记的曝光/观看/互动数据
- account_daily.json：账号级周报数据（粉丝/主页访客/环比）
幂等：重复运行按 id/post_id 覆盖。
"""
import json
import os
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
POSTS_PATH = os.path.join(DATA, "posts.json")
ANALYTICS_PATH = os.path.join(DATA, "analytics.json")
ACCOUNT_PATH = os.path.join(DATA, "account_daily.json")

def load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default

def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# ---- 创作者后台抓取结果（2026-09-21，统计周期 09-14~09-20 / 笔记近30天） ----
NOTES = [
    # (id, title, 发布时间, 曝光, 观看, 封面点击率%, 赞, 评, 藏, 涨粉, 分享, 人均观看时长s, content_line)
    ("joc005", "AI圈为什么普遍有年龄焦虑？", "2026-09-21 16:21", None, 180, None, 10, 0, 3, None, 2, None, "流量线"),
    ("joc010", "穷鬼留子上课必备神器", "2026-09-14 18:34", 1528, 238, 15.9, 17, 0, 5, 0, 2, 6, "收藏线"),
    ("joc009", "Token太多用不完，大家都在用ai做什么呢", "2026-09-10 12:51", 738, 119, 16.4, 5, 4, 0, 1, 0, 6, "流量线"),
    ("joc004", "75万人看过的去AI味方法论", "2026-09-08 20:11", 2023, 168, 10.2, 19, 0, 14, 0, 6, 2, "收藏线"),
    ("joc003", "高强度工作一年后，我决定回学校重新生活", "2026-09-08 19:44", 1600, 247, 16.7, 27, 4, 5, 0, 0, 9, "人设线"),
    ("joc008", "西湖最适合亲嘴的地方。", "2026-09-01 23:17", 64188, 8871, 14.1, 338, 65, 132, 1, 457, 14, "流量线"),
    ("joc007", "贵客松完结篇，期待我们下一次开造！", "2026-08-31 15:34", 2586, 410, 17.4, 17, 4, 5, 7, 3, 11, "人设线"),
    ("joc006", "工作半年后，我为啥选择从明星 AI初创离职", "2026-08-27 16:43", 16623, 2637, 18.2, 77, 6, 22, 1, 15, 25, "人设线"),
]

ACCOUNT_SNAPSHOT = {
    "date": time.strftime("%Y-%m-%d"),
    "period": "09-14 至 09-20",
    "followers_total": 261,
    "followers_new": 2,
    "followers_lost": 1,
    "profile_visits": 144,
    "profile_to_follower_rate": 0.007,
    "views_week": 3418,
    "impressions_week": 24000,
    "interactions_week": 203,
    "ctr_week": 0.151,
    "avg_watch_seconds_week": 18,
    "views_percentile": 96,
    "followers_percentile": 10,
    "active_fans": ["Chris 会联结", "小螃蟹", "三岁的恐龙不会飞", "Yuki.AI", "汐旬", "Xaiver", "自动华.AI", "地瓜瓜"],
    "fan_interests": ["生活记录", "职场", "娱乐", "科技数码", "教育", "美食", "影视", "情感"],
}

posts = load(POSTS_PATH, [])
by_id = {p.get("id"): p for p in posts}

for (pid, title, created, imp, views, ctr, likes, comments, collects, followers, shares, watch, line) in NOTES:
    rec = {
        "id": pid, "account": "Jocelyn", "title": title, "topic": title,
        "content_line": line, "tags": "", "is_ad": False,
        "status": "已发布", "format": "图文",
        "created": created, "updated": created, "material_ids": [],
    }
    if pid in by_id:
        old = by_id[pid]
        old.update({k: v for k, v in rec.items() if k != "body"})
        old["title"] = title  # 用后台真实标题
    else:
        rec["body"] = "（正文存档于小红书，工作台未录入）"
        posts.append(rec)

save(POSTS_PATH, posts)

analytics = load(ANALYTICS_PATH, [])
by_pid = {a.get("post_id"): a for a in analytics}
for (pid, title, created, imp, views, ctr, likes, comments, collects, followers, shares, watch, line) in NOTES:
    row = {
        "post_id": pid,
        "node": "7天",
        "impressions": imp if imp is not None else "",
        "views": views,
        "ctr": ctr if ctr is not None else "",
        "likes": likes,
        "comments": comments,
        "collects": collects,
        "shares": shares,
        "followers": followers if followers is not None else "",
        "avg_watch_seconds": watch if watch is not None else "",
    }
    if pid in by_pid:
        by_pid[pid].update(row)
    else:
        analytics.append(row)
save(ANALYTICS_PATH, analytics)

snapshots = load(ACCOUNT_PATH, [])
snapshots = [s for s in snapshots if s.get("date") != ACCOUNT_SNAPSHOT["date"]]
snapshots.append(ACCOUNT_SNAPSHOT)
save(ACCOUNT_PATH, snapshots)

print(f"posts.json: {len(posts)} 篇（Jocelyn {len([p for p in posts if p.get('account')=='Jocelyn'])} 篇）")
print(f"analytics.json: {len(analytics)} 条（Jocelyn 8 篇笔记数据已写入）")
print(f"account_daily.json: {len(snapshots)} 条账号快照（今日：粉丝 {ACCOUNT_SNAPSHOT['followers_total']}，周观看 {ACCOUNT_SNAPSHOT['views_week']}）")
