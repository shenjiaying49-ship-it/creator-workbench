import json, subprocess, time, os

WB = "/Users/jyshen/claude folder/自我分析与规划/大号自媒体工作台"
MCP = "http://localhost:18060/mcp"
JOC_UID = "68e087800000000037031373"

def call(name, args, timeout=170):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": args}})
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), "-X", "POST", MCP,
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

def get_fresh_token(retries=5):
    for i in range(retries):
        r = call("list_feeds", {}, timeout=60)
        feeds = r.get("feeds") if isinstance(r, dict) else None
        if feeds:
            for f in feeds:
                if f.get("xsecToken"):
                    return f["xsecToken"]
        time.sleep(8)
    return None

# ---------- 1) Jocelyn 跨号回填 ----------
token = get_fresh_token()
joc_feeds = None
if token:
    for i in range(3):
        r = call("user_profile", {"user_id": JOC_UID, "xsec_token": token, "tab": "note"}, timeout=170)
        if isinstance(r, dict) and r.get("feeds"):
            joc_feeds = r["feeds"]
            break
        time.sleep(12)

posts = json.load(open(f"{WB}/data/posts.json"))
by_xhs = {p.get("xhs_id"): p for p in posts if p.get("xhs_id")}
ok = 0
if joc_feeds:
    for f in joc_feeds:
        fid, xt = f["id"], f.get("xsecToken", "")
        p = by_xhs.get(fid)
        if not p or (p.get("body") and len(p["body"]) > 50):
            continue
        d = call("get_feed_detail", {"feed_id": fid, "xsec_token": xt}, timeout=75)
        desc = ""
        if isinstance(d, dict) and "data" in d:
            desc = (d["data"].get("note", {}).get("desc") or "").strip()
        if desc:
            p["body"] = desc
            ok += 1
            json.dump(posts, open(f"{WB}/data/posts.json", "w"), ensure_ascii=False, indent=2)
        time.sleep(4)
    cache = json.load(open(f"{WB}/data/xsec_cache.json")) if os.path.exists(f"{WB}/data/xsec_cache.json") else {}
    for f in joc_feeds:
        if f.get("xsecToken"):
            cache[f["id"]] = f["xsecToken"]
    json.dump(cache, open(f"{WB}/data/xsec_cache.json", "w"), ensure_ascii=False, indent=1)

# ---------- 2) Yuki.AI 自号全量入库 ----------
r = call("get_my_profile", {}, timeout=170)
feeds = r.get("feeds") if isinstance(r, dict) else None
yuki_ok = 0
if feeds:
    posts = json.load(open(f"{WB}/data/posts.json"))
    have = {p.get("xhs_id") for p in posts if p.get("account") == "Yuki.AI"}
    for f in feeds:
        fid, xt = f["id"], f.get("xsecToken", "")
        if fid in have:
            continue
        nc = f.get("noteCard", {}) or {}
        try:
            likes = int((nc.get("interactInfo", {}) or {}).get("likedCount", 0) or 0)
        except Exception:
            likes = 0
        d = call("get_feed_detail", {"feed_id": fid, "xsec_token": xt}, timeout=75)
        desc = ""
        if isinstance(d, dict) and "data" in d:
            desc = (d["data"].get("note", {}).get("desc") or "").strip()
        posts.append({
            "id": "yk" + fid[-6:], "account": "Yuki.AI",
            "title": nc.get("displayTitle", ""), "body": desc,
            "topic": nc.get("displayTitle", ""), "content_line": "",
            "tags": [], "is_ad": False, "status": "已发布", "platform": "小红书",
            "source": "xhs_sync", "xhs_id": fid, "xhs_metrics": {"likes": likes},
            "created": time.strftime("%Y-%m-%d %H:%M"), "updated": time.strftime("%Y-%m-%d %H:%M"),
        })
        yuki_ok += 1
        json.dump(posts, open(f"{WB}/data/posts.json", "w"), ensure_ascii=False, indent=2)
        time.sleep(2.5)

print(f"RESULT: jocelyn={ok} yuki={yuki_ok}", flush=True)
