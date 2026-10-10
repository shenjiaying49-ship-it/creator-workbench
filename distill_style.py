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


def main():
    corpus = json.load(open("/tmp/viral_corpus_xhs.json"))
    samples = "\n".join(
        f"- 赞{c['likes']} @{c['user']}：《{c['title']}》"
        + (f"\n  正文片段：{c['desc'][:200]}" if c.get("desc") else "")
        for c in sorted(corpus, key=lambda x: -x["likes"])[:40])

    prompt = f"""你是爆款内容语言风格分析师。下面是从小红书实时爬取的真实爆帖（消费科技/增长/营销/出海领域，按赞排序）：

{samples}

任务：从这些真实爆帖中提炼「可执行的语言风格基因」，供内容引擎直接套用。要求每条规律都必须来自上面语料的真实模式（可引用原句佐证），不要泛泛而谈。

输出 JSON：
{{
  "小红书": {{
    "title_patterns": ["标题公式，每条带一个语料实例", "..."],
    "opening_patterns": ["开头句式，带实例", "..."],
    "sentence_rhythm": "句长节奏/标点/分行规律（一段话）",
    "vocabulary": {{"high_freq": ["语料高频词"], "avoid": ["语料中缺席的书面词"]}},
    "closing_patterns": ["结尾句式，带实例"],
    "emoji_and_format": "符号/排版使用规律",
    "psychology": "这些帖共同踩中的心理机制（一段话）"
  }},
  "知乎": {{
    "structure": "高赞回答的分层结构（结论前置→论证→案例→方法论）",
    "first_three_lines": "首三行怎么写（折叠机制决定生死）",
    "credibility_moves": ["建立可信度的动作", "..."],
    "tone": "语气规范（专业但有个人视角）"
  }},
  "公众号": {{
    "structure": "1500-3000字深度文的段落节奏",
    "hook_writing": "导语怎么写让人读8分钟",
    "quotable_design": "怎么设计可截图引用的金句/框架",
    "ending": "结尾栏目化写法"
  }},
  "即刻": {{
    "post_anatomy": "一条高互动动态的解剖（观察/数据/情绪配比）",
    "voice": "口语化到什么程度",
    "circle_strategy": "圈子互动策略"
  }},
  "meta": {{
    "cross_platform_core": "四个平台爆帖共同的语言内核（一段话）",
    "stability_rules": ["保证出品稳定度的 3-5 条铁律（每条一句话）"]
  }}
}}

只输出 JSON。"""

    print("提炼中…", flush=True)
    text = llm(prompt)
    data = parse_obj(text)
    if not data:
        print("解析失败，原文前400字：", text[:400])
        return
    out = os.path.join(BASE, "data", "style_skill.json")
    data["_meta"] = {
        "source": "小红书MCP实时爬取 %d 条领域爆帖（关键词：%s）" % (
            len(corpus), "、".join(sorted({c['keyword'] for c in corpus if c.get('keyword')} or {"登录账号全量笔记"}))),
        "distilled_at": __import__("time").strftime("%Y-%m-%d"),
    }
    json.dump(data, open(out, "w"), ensure_ascii=False, indent=2)
    print("已写入", out)

    # 同步生成 ZCode skill（~/.agents/skills/viral-style-gene/SKILL.md）
    skill_dir = os.path.expanduser("~/.agents/skills/viral-style-gene/references")
    os.makedirs(skill_dir, exist_ok=True)
    json.dump(data, open(os.path.join(skill_dir, "style_skill.json"), "w"), ensure_ascii=False, indent=2)

    xhs = data.get("小红书", {})
    meta = data.get("meta", {})
    skill_md = f"""---
name: viral-style-gene
description: 从真实爆帖提炼的四平台语言风格基因（小红书/知乎/公众号/即刻）。当用户要写小红书笔记、公众号长文、知乎回答、即刻动态，或要求内容「像爆帖」「有爆款感」「提高爆款率」时使用。数据来源：小红书 MCP 实时爬取的真实高赞笔记 + 已验证起号方法论。
---

# 爆帖风格基因（viral-style-gene）

> 提炼时间：{data['_meta']['distilled_at']} · 语料：{data['_meta']['source']}
> 完整数据见 references/style_skill.json；本文件是执行要点。

## 小红书（真实语料提炼）

**标题公式**
{chr(10).join('- ' + p for p in xhs.get('title_patterns', [])[:6])}

**开头句式**
{chr(10).join('- ' + p for p in xhs.get('opening_patterns', [])[:4])}

**句感节奏**：{xhs.get('sentence_rhythm', '')}

**词汇**
- 高频：{'、'.join((xhs.get('vocabulary', {}) or {}).get('high_freq', [])[:15])}
- 回避：{'、'.join((xhs.get('vocabulary', {}) or {}).get('avoid', [])[:10])}

**结尾**：{'; '.join(xhs.get('closing_patterns', [])[:3])}

**心理机制**：{xhs.get('psychology', '')}

## 知乎
- 结构：{(data.get('知乎', {}) or {}).get('structure', '')}
- 首三行：{(data.get('知乎', {}) or {}).get('first_three_lines', '')}
- 可信度动作：{'; '.join((data.get('知乎', {}) or {}).get('credibility_moves', [])[:4])}

## 公众号
- 结构：{(data.get('公众号', {}) or {}).get('structure', '')}
- 导语：{(data.get('公众号', {}) or {}).get('hook_writing', '')}
- 金句设计：{(data.get('公众号', {}) or {}).get('quotable_design', '')}

## 即刻
- 动态解剖：{(data.get('即刻', {}) or {}).get('post_anatomy', '')}
- 口语度：{(data.get('即刻', {}) or {}).get('voice', '')}

## 跨平台内核
{meta.get('cross_platform_core', '')}

## 稳定度铁律（每篇出品前过一遍）
{chr(10).join('- [ ] ' + r for r in meta.get('stability_rules', []))}

## 使用方法
1. 写稿前：读本文件对应平台的公式与铁律
2. 写完自检：逐条对照「稳定度铁律」
3. 刷新基因：cd 大号自媒体工作台 && .venv/bin/python distill_style.py（重新爬取+提炼，语料在 /tmp/viral_corpus_xhs.json）
"""
    skill_path = os.path.expanduser("~/.agents/skills/viral-style-gene/SKILL.md")
    open(skill_path, "w").write(skill_md)
    print("ZCode skill 已更新:", skill_path)
    print(json.dumps({k: (list(v.keys()) if isinstance(v, dict) else v) for k, v in data.items()},
                     ensure_ascii=False, indent=1)[:500])


if __name__ == "__main__":
    main()
