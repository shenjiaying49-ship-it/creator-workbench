#!/usr/bin/env python3
"""五库日报数据同步：从豆包多维表格《自媒体五库系统》拉五张表 → static/wuku-data.json
由 launchd (com.wuku.sync) 每日 12:00 调用；也可手动运行。
页面 daily.html 加载时 fetch 该文件，自动刷新五库流水/规则库/作品表/进化日志。"""
import json
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "static" / "wuku-data.json"
BASE_TOKEN = os.environ.get("WUKU_BASE_TOKEN") or json.loads((BASE / "config.json").read_text()).get("wuku", {}).get("base_token", "")
SAMPLE_CUTOFF = "2026-10-15"   # 五库模板自带示例数据都在此日期之前；用户真实录入从 10-15 起
SNAPSHOT = BASE / "data" / "xhs_jocelyn_snapshot.json"   # Jocelyn 小红书真实作品快照
TABLES = {
    "topics": "tblwVlgtdprHLcxu",   # 选题库
    "fanwen": "tblw1g4EZYOVVDD3",   # 范文库
    "works": "tblyQYdwdkiiKUtY",    # 作品库
    "rules": "tble0ODUvREvWzTC",    # 规则库
    "review": "tblD2erv6vZWe984",   # 复盘库
}


def pull(table_id):
    """调 lark-cli 拉一张表，返回记录列表。cwd 必须可写：lark-cli 把 ndjson 落在当前目录。"""
    import tempfile
    rows = []
    with tempfile.TemporaryDirectory(prefix="wuku-sync-") as folder:
        offset = 0
        while True:
            proc = subprocess.run(["lark-cli", "base", "+record-list", "--base-token", BASE_TOKEN,
                "--table-id", table_id, "--limit", "200", "--offset", str(offset)],
                capture_output=True, text=True, timeout=120, cwd=folder)
            result = json.loads(proc.stdout)
            if proc.returncode or not result.get("record_file"):
                raise RuntimeError("飞书读取失败：" + table_id + "；旧快照保留，请检查CLI登录")
            with open(result["record_file"]) as f:
                page = [json.loads(line) for line in f if line.strip()]
            rows.extend(page)
            if not result.get("has_more"):
                break
            if not page:
                raise RuntimeError("分页为空，保留旧快照")
            offset += len(page)
    return rows


def first(v):
    return (v or [""])[0] if isinstance(v, list) else (v or "")


def dshort(v):
    return (v or "")[:10].replace("2026-", "")


def main():
    topics = pull(TABLES["topics"])
    fanwen = pull(TABLES["fanwen"])
    works = pull(TABLES["works"])
    rules = pull(TABLES["rules"])
    review = pull(TABLES["review"])

    # ---- 区分模板示例与真实录入 ----
    def real(rows, field):
        return [r for r in rows if (r.get(field) or "")[:10] >= SAMPLE_CUTOFF]

    topics_r, fanwen_r = real(topics, "收录日期"), real(fanwen, "收藏日期")
    works_r, rules_r, review_r = real(works, "发布时间"), real(rules, "首次沉淀日期"), real(review, "复盘日期")

    # ---- 五库流水（含配色分段，页面直接渲染） ----
    TEAL, MID, RED, GREY, AMBER = "#0ABAB5", "#7ccfcc", "#c0392b", "#e8ecec", "#b07d2b"

    def seg(pairs):
        total = sum(n for _, n in pairs) or 1
        return [{"c": c, "pct": round(n / total * 100, 1)} for c, n in pairs if n]

    def counts(rows, field):
        out = {}
        for r in rows:
            k = first(r.get(field))
            out[k] = out.get(k, 0) + 1
        return out

    t_status, f_status, r_conf = counts(topics_r, "状态"), counts(fanwen_r, "状态"), counts(rules_r, "置信度")
    sample_note = lambda n: (" · 模板示例 %d" % n) if n else ""

    pools = {
        "选题库": {"v": len(topics_r),
                   "note": " · ".join(f"{k} {v}" for k, v in sorted(t_status.items(), key=lambda x: -x[1])) + sample_note(len(topics) - len(topics_r)),
                   "bars": seg([(TEAL, t_status.get("待使用", 0)), (MID, t_status.get("已采用", 0)), (GREY, max(len(topics_r) - t_status.get("待使用", 0) - t_status.get("已采用", 0), 0))])},
        "范文库": {"v": len(fanwen_r),
                   "note": " · ".join(f"{k} {v}" for k, v in sorted(f_status.items(), key=lambda x: -x[1])) + sample_note(len(fanwen) - len(fanwen_r)),
                   "pending": f_status.get("待分析", 0),
                   "bars": seg([(RED, f_status.get("待分析", 0)), (TEAL, f_status.get("已提炼", 0) + f_status.get("已使用", 0))])},
        "作品库": {"v": len(works_r),
                   "note": ("真实回填 %d 条" % len(works_r) if works_r else "真实作品 0 条 · 用「贴数据回填」") + sample_note(len(works) - len(works_r)),
                   "bars": seg([(TEAL, len(works_r)), (GREY, 1 if not works_r else 0)])},
        "规则库": {"v": len(rules_r),
                   "note": " · ".join(f"{k} {v}" for k, v in sorted(r_conf.items(), key=lambda x: -x[1])) + (" · 模板预置 %d" % (len(rules) - len(rules_r)) if len(rules) > len(rules_r) else ""),
                   "bars": seg([(TEAL, r_conf.get("已验证", 0)), (MID, r_conf.get("高置信", 0)), (GREY, r_conf.get("待验证", 0))])},
        "复盘库": {"v": len(review_r),
                   "note": ("真实复盘 %d" % len(review_r) if review_r else "真实复盘 0 · 周日提炼后生成") + sample_note(len(review) - len(review_r)),
                   "bars": seg([(TEAL, len(review_r)), (GREY, 1 if not review_r else 0)])},
    }

    # ---- 规则库（页面按置信度筛选展示；模板预置打标） ----
    rule_list = [{
        "n": r.get("规则名称") or "未命名规则",
        "c": first(r.get("规则类别")) or "-",
        "conf": first(r.get("置信度")) or "待验证",
        "u": int(r.get("使用次数") or 0),
        "d": dshort(r.get("最近更新日期")),
        "x": (r.get("规则内容") or "").strip(),
        "sample": (r.get("首次沉淀日期") or "")[:10] < SAMPLE_CUTOFF,
    } for r in rules]

    # ---- 我的作品：真实回填（Base ≥ 分界线）+ 小红书快照 ----
    work_rows = []
    for r in works_r:
        work_rows.append({"t": r.get("作品标题") or "-", "pf": first(r.get("平台")) or "-",
                          "d": (r.get("发布时间") or "")[5:10], "likes": r.get("点赞数"), "collects": r.get("收藏/转发数"),
                          "comments": r.get("评论数"), "plays": r.get("播放量"), "fans": r.get("涨粉数"), "src": "回填"})
    snap_meta = {}
    try:
        snap = json.loads(SNAPSHOT.read_text())
        snap_meta = {"crawled_at": snap.get("crawled_at"), "followers": snap.get("followers"), "n": len(snap.get("notes", []))}
        for n in snap.get("notes", []):
            d = datetime.fromtimestamp(n["publish_ts"] / 1000).strftime("%m-%d") if n.get("publish_ts") else ""
            work_rows.append({"t": n.get("title") or "-", "pf": "小红书", "d": d, "likes": n.get("likes"),
                              "collects": n.get("collects"), "comments": n.get("comments"), "plays": None, "fans": None,
                              "src": "快照" + ("·视频" if n.get("type") == "video" else "")})
    except Exception as e:
        print("snapshot skipped:", e, file=sys.stderr)
    work_rows.sort(key=lambda w: (w["likes"] or 0), reverse=True)

    # ---- 范文库真实条目（供初稿 prompt 引用同类范文写法） ----
    fanwen_export = [{
        "t": r.get("范文标题") or "-", "pf": first(r.get("平台")) or "-",
        "ct": first(r.get("内容类型")) or "-", "d": (r.get("收藏日期") or "")[5:10],
        "why": (r.get("为什么值得收藏") or "")[:120], "pts": (r.get("可复用的点") or "")[:160],
        "ex": (r.get("逐字稿/口播稿") or "")[:520],
    } for r in fanwen_r]

    # ---- Jocelyn 平台分析（本系统唯一账号）：posts.json × analytics.json 连接 ----
    jy_rows, jy_sum = [], {"posts": 0, "views": 0, "likes": 0, "collects": 0, "comments": 0, "followers": 0}
    try:
        posts_all = json.loads((BASE / "data" / "posts.json").read_text())
        analytics = json.loads((BASE / "data" / "analytics.json").read_text())
        pmap = {p["id"]: p for p in posts_all if p.get("account") == "Jocelyn"}
        for a in analytics:
            p = pmap.get(a.get("post_id"))
            if not p:
                continue
            jy_sum["posts"] += 1
            for k in ("views", "likes", "collects", "comments", "followers"):
                jy_sum[k] += a.get(k) or 0
            jy_rows.append({"t": (p.get("title") or "-")[:30], "d": (p.get("created") or "")[5:10],
                            "node": a.get("node") or "-", "views": a.get("views") or 0, "likes": a.get("likes") or 0,
                            "collects": a.get("collects") or 0, "comments": a.get("comments") or 0,
                            "followers": a.get("followers") or 0})
        jy_rows.sort(key=lambda r: -(r["views"] + r["likes"] * 2 + r["collects"] * 2))
    except Exception as e:
        print("jocelyn analytics skipped:", e, file=sys.stderr)

    # ---- 发布全文存档（wuku_archive.json，发布打卡自动写入）----
    pub_rows, pub_keys, last_publish = [], set(), None
    try:
        pubs = json.loads((BASE / "data" / "wuku_archive.json").read_text())
        for e in pubs:
            pub_rows.append({"d": (e.get("date") or "")[5:10], "t": e.get("title") or "-", "line": e.get("form") or "-",
                             "st": "已发布", "views": None, "likes": None, "collects": None, "comments": None,
                             "followers": None, "src": "发布存档", "body": e.get("body") or ""})
            pub_keys.add((e.get("title"), e.get("platform")))
        if pubs:
            last_publish = max(e.get("date") for e in pubs)
    except Exception:
        pass

    # ---- 作品全量存档（posts.json Jocelyn 全部 + 分析数据 join + 快照/回填补充）----
    archive = []
    try:
        posts_all = json.loads((BASE / "data" / "posts.json").read_text())
        analytics = json.loads((BASE / "data" / "analytics.json").read_text())
        amap = {}
        for a in analytics:
            pid = a.get("post_id")
            if pid not in amap or a.get("node") == "发布至今(实时同步)":
                amap[pid] = a
        seen_titles = set()
        for p in posts_all:
            if p.get("account") != "Jocelyn":
                continue
            t = p.get("title") or "-"
            seen_titles.add(t.replace(" ", "")[:20])
            a = amap.get(p["id"]) or {}
            archive.append({"d": (p.get("created") or "")[5:10], "t": t[:40],
                            "line": p.get("content_line") or "-", "st": p.get("status") or "-",
                            "views": a.get("views"), "likes": a.get("likes"), "collects": a.get("collects"),
                            "comments": a.get("comments"), "followers": a.get("followers"), "src": "稿件库"})
        for w in work_rows:
            if (w.get("t"), w.get("pf")) in pub_keys:
                continue  # 发布存档行已带全文，避免 Base 行重复
            if w.get("src", "").startswith("回填") or w.get("t", "").replace(" ", "")[:20] not in seen_titles:
                archive.append({"d": w.get("d") or "", "t": w.get("t") or "-", "line": "-", "st": "已发布",
                                "views": w.get("plays"), "likes": w.get("likes"), "collects": w.get("collects"),
                                "comments": w.get("comments"), "followers": w.get("fans"), "src": w.get("src") or "快照"})
        archive = pub_rows + archive
        if not last_publish and work_rows:
            last_publish = max((w.get("d") or "" for w in work_rows if w.get("d")), default=None)
        if last_publish and len(last_publish) == 5:
            last_publish = str(datetime.now().year) + "-" + last_publish
        archive.sort(key=lambda r: r.get("d") or "", reverse=True)
    except Exception as e:
        print("archive skipped:", e, file=sys.stderr)

    # ---- 进化日志（只看真实规则，按最近更新日期聚合，最新 5 天） ----
    by_date = {}
    for r in rule_list:
        if r["sample"]:
            continue
        by_date.setdefault(r["d"], []).append(r)
    evol = []
    for d in sorted(by_date, reverse=True)[:5]:
        items = by_date[d]
        verified = [i for i in items if i["conf"] == "已验证"]
        head = "，".join(i["n"] for i in items[:2]) + ("…" if len(items) > 2 else "")
        evol.append({"d": d, "t": "规则库 +{} · {}".format(len(items), "含已验证 skill" if verified else "待验证样本"), "x": head})

    out = {
        "fetched_at": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M%z"),
        "pools": pools,
        "topics_list": [{"id": r.get("record_id"), "title": r.get("选题标题") or "未命名",
                         "why": r.get("为什么值得做") or "", "direction": first(r.get("选题方向")),
                         "status": first(r.get("状态")), "platform": first(r.get("平台")),
                         "date": (r.get("收录日期") or "")[:10], "source": r.get("来源链接") or ""} for r in topics_r],
        "review_list": [{"id": r.get("record_id"), "title": r.get("复盘主题") or "未命名",
                         "date": (r.get("复盘日期") or "")[:10], "observation": r.get("数据表现总结") or "",
                         "next": r.get("优化方向") or ""} for r in review_r],
        "rules": rule_list,
        "works": work_rows,
        "jy_analytics": {"summary": jy_sum, "rows": jy_rows},
        "jy_archive": archive,
        "last_publish": last_publish,
        "fanwen_list": fanwen_export,
        "snapshot": snap_meta,
        "sample_cutoff": SAMPLE_CUTOFF,
        "evol": evol,
    }
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)
    print(f"wuku-data.json written: rules={len(rule_list)} works={len(work_rows)} fanwen={len(fanwen)} topics={len(topics)}")


if __name__ == "__main__":
    main()
