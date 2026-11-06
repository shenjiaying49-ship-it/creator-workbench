"""爆帖风格提炼：小红书真实语料 + 各平台方法论 → style_skill.json
输入: /tmp/viral_corpus_xhs.json（MCP 爬的真实爆帖）
输出: data/style_skill.json（注入 studio_prompt + 固化为 ZCode skill）
"""
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


def llm(prompt):
    cfg = json.load(open(os.path.join(BASE, "config.json")))
    c = cfg["llm"]
    body = json.dumps({"model": c["model"], "temperature": 0.4,
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 4000}).encode()
    req = urllib.request.Request(c["base_url"], data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + c["api_key"]}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"]


def parse_obj(text):
    import re
    for cand in [text] + re.findall(r"```(?:json)?\s*([\s\S]*?)```", text) + re.findall(r"\{[\s\S]*\}", text):
        for t in [cand, re.sub(r",\s*([}\]])", r"\1", cand or "")]:
            try:
                v = json.loads(t)
                if isinstance(v, dict):
                    return v
            except Exception:
                pass
    return None


def normalize_gene(g):
    """LLM 偶尔把规则输出成 {rule, example, ...} 对象——统一拍平成字符串，保证注入和 SKILL 生成拿到统一样式"""
    if not isinstance(g, dict):
        return {}
    for key in ("executable_rules", "evidence", "stability_rules"):
        vals = g.get(key)
        if not isinstance(vals, list):
            g[key] = []
            continue
        out = []
        for v in vals:
            if isinstance(v, str):
                if v.strip():
                    out.append(v.strip())
            elif isinstance(v, dict):
                main = v.get("rule") or v.get("text") or v.get("pattern") or ""
                extras = [f"{k}：{x}" for k, x in v.items()
                          if k not in ("rule", "text", "pattern") and isinstance(x, (str, int, float))]
                s = str(main).strip()
                if s and extras:
                    s += "（" + "；".join(extras) + "）"
                if s:
                    out.append(s)
        g[key] = out
    return g


def main():
    corpus = json.load(open("/tmp/viral_corpus_xhs.json"))
    samples = "\n".join(
        f"- 赞{c['likes']}（{c.get('source', '未知')}）《{c['title']}》"
        + (f"\n  正文片段：{c['desc'][:200]}" if c.get("desc") else "")
        for c in sorted(corpus, key=lambda x: -x["likes"])[:40])

    prompt = f"""你是爆款内容语言风格分析师。下面是从小红书实时爬取的真实爆帖（消费科技/增长/营销/出海领域，按赞排序）：

{samples}

任务：提炼「四平台可执行的语言风格基因」，供内容引擎直接套用。小红书部分每条规则必须由上面语料的真实模式支撑（在 evidence 里引用原句并带赞数），不要泛泛而谈；知乎/公众号/即刻结合公认高赞模式与已验证方法论。目标账号人设：持穗/Rohini，消费科技增长与商业化拆解（作品集导向，写给未来雇主和同行看）。

输出 JSON：
{{
  "小红书": {{
    "executable_rules": ["8-14 条可直接执行的规则：标题公式（对比高赞 vs 低赞找区分性特征）、开头句式、句子节奏与排版、词汇白名单/黑名单、结尾句式、心理机制，每条带语料实例和赞数"],
    "evidence": ["语料原句引用（带赞数），至少 6 条；标注统计口径"],
    "stability_rules": ["3-8 条出品前自查铁律，每条一句话"]
  }},
  "知乎": {{
    "executable_rules": ["8-12 条：结论前置（首三行定生死）、利益相关声明、分层论证、数据锚点、可截图框架、亲历叙事、观点不骑墙、热榜借势"],
    "evidence": ["方法论文档要点或公认高赞模式来源说明"],
    "stability_rules": ["3-4 条出品前自查铁律"]
  }},
  "公众号": {{
    "executable_rules": ["8-12 条：标题公式、导语钩子、段落节奏、数据下钻、金句设计、中英混排、克制语气+学生人设、边界诚实、结尾栏目化"],
    "evidence": ["方法论文档要点来源说明"],
    "stability_rules": ["3-4 条出品前自查铁律"]
  }},
  "即刻": {{
    "executable_rules": ["8-12 条：动态解剖配比（观察/数据/情绪）、口语化刻度、开头进具体场景、数据可验证、金句+互动钩、圈子互动策略"],
    "evidence": ["方法论文档要点来源说明"],
    "stability_rules": ["3-4 条出品前自查铁律"]
  }},
  "meta": {{
    "cross_platform_core": "四个平台爆帖共同的语言内核（一句话）",
    "stability_rules": ["四平台稳定性铁律去重合并后的 5-6 条（每条一句话）"]
  }}
}}

只输出 JSON。"""

    print("提炼中…", flush=True)
    text = llm(prompt)
    data = parse_obj(text)
    if not data:
        print("解析失败，原文前400字：", text[:400])
        return
    # 先拍平规则（LLM 偶发输出 {rule, example} 对象），再落盘
    for plat in ["小红书", "知乎", "公众号", "即刻"]:
        data[plat] = normalize_gene(data.get(plat, {}) or {})
    if isinstance(data.get("meta"), dict):
        data["meta"] = {
            "cross_platform_core": str(data["meta"].get("cross_platform_core", "")),
            "stability_rules": [v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                                for v in data["meta"].get("stability_rules", []) if v],
        }
    out = os.path.join(BASE, "data", "style_skill.json")
    src_parts = sorted({c.get("source", "未知") for c in corpus})
    data["_meta"] = {
        "source": "小红书真实语料 %d 条（来源：%s）" % (len(corpus), "、".join(src_parts)),
        "distilled_at": __import__("time").strftime("%Y-%m-%d"),
    }
    json.dump(data, open(out, "w"), ensure_ascii=False, indent=2)
    print("已写入", out)

    # 同步生成 ZCode skill（~/.agents/skills/viral-style-gene/SKILL.md）
    skill_dir = os.path.expanduser("~/.agents/skills/viral-style-gene/references")
    os.makedirs(skill_dir, exist_ok=True)
    json.dump(data, open(os.path.join(skill_dir, "style_skill.json"), "w"), ensure_ascii=False, indent=2)

    meta = data.get("meta", {})
    platform_sections = []
    for plat in ["小红书", "知乎", "公众号", "即刻"]:
        rules = (data.get(plat) or {}).get("executable_rules", [])
        if not rules:
            continue
        platform_sections.append(f"## {plat}\n\n" + "\n".join("- " + r for r in rules))
    skill_md = f"""---
name: viral-style-gene
description: 从真实爆帖提炼的四平台语言风格基因（小红书/知乎/公众号/即刻）。当用户要写小红书笔记、知乎回答、公众号长文、即刻动态，或要求内容「像爆帖」「有爆款感」「提高爆款率」时使用。
---

# 爆帖风格基因（viral-style-gene）

> 提炼时间：{data['_meta']['distilled_at']} · 语料：{data['_meta']['source']}
> 完整规则与语料证据见 references/style_skill.json；本文件是执行要点。

## 跨平台语言内核

{meta.get('cross_platform_core', '')}

{chr(10).join(platform_sections)}

## 稳定度铁律（每篇出品前过一遍）

{chr(10).join('- [ ] ' + r for r in meta.get('stability_rules', []))}

## 使用方法

1. 写稿前：读本文件对应平台的规则与铁律；需要证据出处时读 references/style_skill.json
2. 写完自检：逐条对照「稳定度铁律」
3. 工作台生成：大号自媒体工作台的「一键生成」已自动把这些基因注入生成提示词（server.py studio_prompt 读取 data/style_skill.json）

## 刷新基因

数据源变化时刷新一次（重爬语料后重跑语料脚本）：

```bash
cd 大号自媒体工作台 && .venv/bin/python distill_style.py
```

脚本读 /tmp/viral_corpus_xhs.json（语料：Jocelyn 快照 30 篇 + 登录账号笔记正文）→ 重新提炼四平台基因 → 覆盖 data/style_skill.json 与本 skill。
"""
    skill_path = os.path.expanduser("~/.agents/skills/viral-style-gene/SKILL.md")
    open(skill_path, "w").write(skill_md)
    print("ZCode skill 已更新:", skill_path)
    print(json.dumps({k: (list(v.keys()) if isinstance(v, dict) else v) for k, v in data.items()},
                     ensure_ascii=False, indent=1)[:500])


if __name__ == "__main__":
    main()
