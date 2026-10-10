#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本：把 Yuki.AI 发帖记录导入工作台作为演示数据"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

posts = [
    ("2026-09-09", "模型越聪明，越不能默认开满", "收藏线", None, None, None, None, None, None),
    ("2026-08-06", "你越顺着 AI，它越敷衍你", "收藏线", None, None, None, None, None, None),
    ("2026-08-04", "裸辞去做AI startup BD后，履历成了我最没用的东西", "人设线", None, None, None, None, None, None),
    ("2026-08-03", "为什么AI工具越装越多，工作反而更慢", "收藏线", 146, 4, 2, 0, 1, None),
    ("2026-08-01", "装AI Skill前，先查这3个危险信号", "收藏线", 108, 8, 2, 0, 2, None),
    ("2026-07-31", "创业者最贵的成本，是每件事都要亲自解释", "收藏线", 602, 21, 14, 0, 4, None),
    ("2026-07-30", "面试AI startup，别再说“我会用ChatGPT”", "流量线", 108, 6, 4, 0, 0, None),
    ("2026-07-29", "口播邪修：说错一句，直接删掉那行字", "收藏线", 79, 3, 2, 1, 0, None),
    ("2026-07-28", "推荐一个完全免费的宝藏PDF工具网站", "流量线", 25, 2, 0, 0, 0, None),
    ("2026-07-27", "把Obsidian丢给KIMI，它还是太懂我了", "收藏线", 369, 12, 11, 0, 3, None),
    ("2026-07-24", "如何让AI快速了解项目上下文", "收藏线", 381, 12, 15, 0, 1, None),
    ("2026-07-15", "这个开源工具把视频剪辑的Token成本砍了99%", "收藏线", 1219, 64, 111, 9, 25, None),
    ("2026-07-13", "怎么向明星初创 founder 证明你的价值", "流量线", 559, 16, 13, 0, 1, None),
    ("2026-07-12", "AI真实现状：工作 10 分钟，调试 3 小时", "流量线", 199, 2, 3, 0, 1, None),
    ("2026-07-08", "流量异常没流量复制一遍真有用！", "流量线", 40, 6, 0, 17, 0, None),
    ("2026-07-07", "大厂裸辞，放弃200w年薪创业的他，后悔了吗", "人设线", 45, 4, 3, 0, 0, None),
    ("2026-07-06", "一个真正值得参与的黑客松有什么特点？", "流量线", 1557, 89, 68, 2, 12, None),
    ("2026-07-04", "年薪40-60w的大厂人正在失业", "流量线", 304, 3, 3, 0, 0, None),
]

def main():
    posts_path = os.path.join(DATA, "posts.json")
    analytics_path = os.path.join(DATA, "analytics.json")

    existing_posts = json.load(open(posts_path, encoding="utf-8")) if os.path.exists(posts_path) else []
    existing_analytics = json.load(open(analytics_path, encoding="utf-8")) if os.path.exists(analytics_path) else []

    if any(p.get("account") == "Yuki.AI" for p in existing_posts):
        print("Yuki.AI 演示数据已存在，跳过导入")
        return

    for i, (date, title, line, views, likes, collects, comments, shares, followers) in enumerate(posts):
        pid = f"yuki{i:02d}"
        existing_posts.append({
            "id": pid,
            "account": "Yuki.AI",
            "title": title,
            "body": "（历史稿件，正文存档于 Yuki ai 内容/ 目录）",
            "topic": title,
            "content_line": line,
            "tags": "",
            "is_ad": False,
            "status": "已发布",
            "created": date + " 12:00",
            "updated": date + " 12:00",
        })
        if views is not None:
            existing_analytics.append({
                "post_id": pid,
                "account": "Yuki.AI",
                "node": "发布后7天",
                "views": views, "likes": likes, "collects": collects,
                "comments": comments, "shares": shares,
                "followers": followers or 0, "profile_visits": 0,
            })

    json.dump(existing_posts, open(posts_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(existing_analytics, open(analytics_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"已导入 {len(posts)} 篇 Yuki.AI 历史稿件，{len([p for p in posts if p[3] is not None])} 条数据记录")

if __name__ == "__main__":
    main()
