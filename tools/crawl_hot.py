import json, subprocess, time, os

WB = "/Users/jyshen/claude folder/自我分析与规划/大号自媒体工作台"
MCP = "http://localhost:18060/mcp"

def call(name, args, timeout=70):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": args}})
    try:
        out = subprocess.run(["curl", "-s", "--max-time", str(timeout), "-X", "POST", MCP,
                              "-H", "Content-Type: application/json", "-d", payload],
                             capture_output=True, text=True, timeout=timeout + 10).stdout
        d = json.loads(out)
        txt = d["result"]["content"][0]["text"]
        try:
            return json.loads(txt)
        except Exception:
            return {"__err__": txt[:80]}
    except Exception as e:
        return {"__err__": str(e)[:80]}

# 1) 首页推荐流（真实热门笔记 + xsecToken）
feeds = None
for _try in range(6):
    r = call("list_feeds", {}, timeout=60)
    feeds = r.get("feeds") if isinstance(r, dict) else None
    if feeds:
        break
    print(f"list_feeds 重试 {_try+1}/6", flush=True)
    time.sleep(20)
print(f"feed {len(feeds)} 条", flush=True)
if not feeds:
    print("list_feeds 不可用"); raise SystemExit

# 按赞排序取高赞正文
ranked = []
for f in feeds:
    nc = f.get("noteCard", {}) or {}
    ii = nc.get("interactInfo", {}) or {}
    try:
        likes = int(ii.get("likedCount", 0) or 0)
    except Exception:
        likes = 0
    ranked.append({"id": f["id"], "xsec": f.get("xsecToken", ""),
                   "title": nc.get("displayTitle", ""), "likes": likes,
                   "user": (nc.get("user", {}) or {}).get("nickname", "")})
ranked.sort(key=lambda x: -x["likes"])

out = []
for i, e in enumerate(ranked[:10]):
    d = call("get_feed_detail", {"feed_id": e["id"], "xsec_token": e["xsec"]}, timeout=70)
    desc = ""
    if isinstance(d, dict) and "data" in d:
        desc = (d["data"].get("note", {}).get("desc") or "").strip()
    if desc:
        out.append({**e, "desc": desc[:900]})
        print(f"[{i+1}] 赞{e['likes']:>6} @{e['user'][:12]} {len(desc)}字 | {e['title'][:30]}", flush=True)
    time.sleep(3)
    json.dump(out, open(f"{WB}/data/hot_corpus.json", "w"), ensure_ascii=False, indent=1)

print(f"完成：{len(out)} 篇真实热门正文 → data/hot_corpus.json", flush=True)
