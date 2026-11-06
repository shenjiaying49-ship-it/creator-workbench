#!/usr/bin/env python3
"""五库 · 每周日自动提炼：范文库「本周待分析」+ 作品库数据 → LLM 提炼 3-5 条规则
→ 回写豆包规则库（置信度=待验证）→ 已提炼范文状态改「已提炼」。
launchd com.wuku.distill 每周日 20:30 运行；--dry-run 只生成不写库。"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wuku_sync import pull, TABLES, BASE  # noqa: E402

DRY = "--dry-run" in sys.argv
BASE_TOKEN = os.environ.get("WUKU_BASE_TOKEN") or json.loads((BASE / "config.json").read_text()).get("wuku", {}).get("base_token", "")
CONF = json.load(open(BASE / "config.json")).get("llm", {})


def llm(prompt):
    models = [CONF.get("model", "kimi-k2.5")] + list(CONF.get("fallback_models", []))
    err = "no key"
    for m in models:
        body = json.dumps({"model": m, "temperature": 0.4,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(CONF["base_url"], data=body, headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + CONF.get("api_key", ""),
        }, method="POST")
        try:
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    return json.loads(resp.read().decode())["choices"][0]["message"]["content"], None
            except Exception as e:
                if "CERTIFICATE" not in str(e).upper():
                    raise
                import ssl
                ctx = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=180, context=ctx) as resp:
                    return json.loads(resp.read().decode())["choices"][0]["message"]["content"], None
        except Exception as e:
            err = "%s: %s" % (m, e)
    return None, err


def upsert(table_id, payload, record_id=None):
    cmd = ["lark-cli", "base", "+record-upsert", "--base-token", BASE_TOKEN,
           "--table-id", table_id, "--json", json.dumps(payload, ensure_ascii=False)]
    if record_id:
        cmd += ["--record-id", record_id]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(BASE))
    if r.returncode != 0 or '"ok": false' in r.stdout.lower() or '"code"' in r.stdout and '"msg":"success"' not in r.stdout:
        print("upsert warn:", r.stdout[:200], r.stderr[:200])
        return False
    return True


def main():
    fanwen = pull(TABLES["fanwen"])
    rules = pull(TABLES["rules"])
    works = pull(TABLES["works"])

    cutoff = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
    if "--backlog" in sys.argv:
        batch = [r for r in fanwen if (r.get("状态") or [""])[0] == "待分析"][:12]
    else:
        batch = [r for r in fanwen
                 if (r.get("状态") or [""])[0] == "待分析" and (r.get("收藏日期") or "")[:10] >= cutoff][:12]
    if not batch:
        print("本周没有新的「待分析」范文，无需提炼")
        return

    entries = "\n\n".join(
        "[%d] 《%s》\n为什么收藏：%s\n可复用点：%s\n内容摘录：%s" % (
            i + 1, r.get("范文标题"), r.get("为什么值得收藏", "") or "",
            r.get("可复用的点", "") or "", (r.get("逐字稿/口播稿") or "")[:700])
        for i, r in enumerate(batch))
    existing = "；".join((r.get("规则名称") or "") for r in rules[-30:])
    work_lines = "\n".join(
        "- 《%s》播放%s 评级%s" % (w.get("作品标题"), w.get("播放量"), (w.get("数据评级") or [""])[0])
        for w in works if (w.get("发布时间") or "")[:10] >= "2026-10-15")  # 模板示例作品不计

    prompt = """你是 Jocelyn 的内容策略顾问。以下是本周收集的范文（附收藏理由与摘录）和她的作品数据，请完成两件事：
1. 提炼 3-5 条可复用的爆款共性，每条写成「在什么场景、做什么动作、预期效果」的可执行规则
2. 结合本周作品数据，指出哪条规律被验证或证伪（写进对应规则的理由里）

【本周范文】
%s

【她已有的规则（不要重复提炼，只补新的）】
%s

【她的作品数据】
%s

只输出 JSON 数组，不要其他文字：
[{"规则名称":"…","规则内容":"场景+动作+预期","规则类别":"开头Hook/选题规律/标题公式/互动设计/完播技巧/发布策略/内容结构/写作模板/运营方法 之一","适用场景":"…","证据来源":"范文《…》等","置信度":"待验证"}]""" % (entries, existing or "（暂无）", work_lines or "（本周无发布）")

    text, err = llm(prompt)
    if not text:
        print("LLM 失败:", err)
        sys.exit(1)
    try:
        import re
        m = re.search(r"\[.*\]", text, re.S)
        parsed = json.loads(m.group(0))
    except Exception as e:
        print("解析失败:", e, text[:300])
        sys.exit(1)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("提炼出 %d 条规则%s" % (len(parsed), "（dry-run 不写库）" if DRY else ""))
    for rule in parsed[:5]:
        print(" · [%s] %s" % (rule.get("置信度", "待验证"), rule.get("规则名称")))
        if DRY:
            continue
        upsert(TABLES["rules"], {
            "规则名称": rule.get("规则名称", "未命名"),
            "规则内容": rule.get("规则内容", ""),
            "规则类别": rule.get("规则类别", "写作模板"),
            "置信度": "待验证",
            "适用场景": rule.get("适用场景", ""),
            "证据来源": rule.get("证据来源", ""),
            "首次沉淀日期": now,
            "最近更新日期": now,
            "使用次数": 0,
            "效果备注": "周日自动提炼（LLM 自评：%s），待作品数据验证" % rule.get("置信度", "待验证"),
        })
    for r in batch:
        print(" 范文标记已提炼：%s" % r.get("范文标题"))
        if DRY:
            continue
        upsert(TABLES["fanwen"], {"状态": "已提炼"}, record_id=r["record_id"])
    print("done at", now)


if __name__ == "__main__":
    main()
