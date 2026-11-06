#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大号小红书自媒体工作台 - 本地服务
用法: python3 server.py [--port 8501]
"""
import json
import growth
import os
import re
import sys
import time
import datetime
import uuid
import threading
import subprocess
import urllib.request
import urllib.error
import ssl
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
WUKU_DRAFTS_PATH = os.path.join(BASE, "data", "wuku_drafts.json")
WUKU_SLOT_PLATFORM = {
    "干货": ("小红书图文笔记", "小红书"),
    "复盘": ("小红书图文笔记", "小红书"),
    "攻略": ("小红书图文笔记", "小红书"),
    "口播": ("抖音口播短视频", "口播"),
    "海外": ("Threads 主帖 + X 短版", "Threads"),
    "栏目": ("公众号文章", "公众号"),
}

DATA = os.path.join(BASE, "data")
UPLOADS = os.path.join(DATA, "uploads")
CONFIG_PATH = os.path.join(BASE, "config.json")

os.makedirs(UPLOADS, exist_ok=True)

def wuku_style_context():
    """平台风格 skill（规则库已验证条目）+ 本人已发内容（风格/选题参考）。"""
    data = load_json(os.path.join(STATIC, "wuku-data.json"), {})
    skill_text = ""
    for r in data.get("rules", []):
        name = (r.get("n") or "").replace(" ", "")
        if "风格" in name and "skill" in name.lower():
            skill_text += "【%s｜置信度:%s】%s\n" % (r.get("n"), r.get("conf", ""), (r.get("x") or "")[:600])
    my_titles = []
    try:
        snap = load_json(os.path.join(BASE, "data", "xhs_jocelyn_snapshot.json"), {})
        for n in sorted(snap.get("notes", []), key=lambda x: -(x.get("likes") or 0))[:12]:
            my_titles.append("《%s》（赞%d 藏%d）" % (n.get("title"), n.get("likes") or 0, n.get("collects") or 0))
    except Exception:
        pass
    for w in data.get("works", [])[:6]:
        if isinstance(w, dict) and w.get("src", "").startswith("回填"):
            my_titles.append("《%s》（%s，播放%s）" % (w.get("t"), w.get("pf"), w.get("plays")))
    return skill_text, "；".join(my_titles)

WUKU_WORKS_TABLE = "tblyQYdwdkiiKUtY"
WUKU_CHECKLIST = """【发布前终检清单（活人感三问 + 平台风格 skill + 起号攻略，已内化）】
1. 活人感：正文是否残留未填的 [待填]；有没有至少 1 处只有她本人能写的真实细节或判断（AI 通用话术=不合格）
2. 标题：含具体锚点（公司/产品/带单位数字）；小红书标题 ≤20 字；关键词前置；另给 1 个 A/B 备选标题
3. 钩子：口播=前 3 秒必须让人留下来；图文=首行 30 字内出钩（收益承诺/反差/身份点名，必须成立）
4. 结构：1-2 句一段；1-3 处「X 不是 A，而是 B」判断句；有可截图带走的金句
5. 转粉路径：结尾有没有引导进主页/关注的钩子（主页转粉率是核心指标）；置顶笔记搭配建议一句
6. 互动：结尾是提问式轻指令（禁止「你怎么看」）
7. 黑名单词零出现：赋能/抓手/闭环/生态位/颗粒度/综上所述/值得注意的是；感叹号 0 个
8. 利他性：读者能带走至少一样东西（可抄的清单/步骤/避坑/资源），纯情绪输出=不合格
9. 发布时间：对照黄金发布时间表，给今天这条的最优发布时段建议"""

WUKU_GZH_GENE = "播客对话体：开头 时间+场合+事件+情绪定调，第二段交代来源；一二三编号大节，节标题=不骑墙判断句；每节 ≥2 处直接引语 + 短判断独立成段；每段至少一个可点名实体/数字；禁导览腔（我们来看看/值得注意的是）；引语必须真实，禁编造。"
WUKU_FORM_DESC = {
    ("小红书+抖音", "视频"): "小红书+抖音双发口播：一条 200-300 字口播稿（60-90 秒，两平台同素材）+ 小红书标题/标签/封面 + 抖音标题/文案/话题 + 拍摄剪辑提示",
    ("小红书", "图文"): "小红书图文笔记：标题 ≤20 字 + 正文（1-2 句一段）+ 5-10 个话题标签",
    ("小红书", "视频"): "小红书口播短视频：200-300 字口播稿（60-90 秒）+ 封面标题 + 标签 + 拍摄/剪辑提示",
    ("抖音", "视频"): "抖音口播短视频：200-300 字口播稿（60-90 秒）+ 分镜/拍摄与剪辑提示 + 文案标题",
    ("Threads+X", "图文"): "Threads 中文主帖（≤300 字，第一秒能懂）+ X 短版 + 首评补链接/步骤",
    ("公众号", "图文"): "公众号文章：标题 + 播客对话体正文（开头两段写实，后续给分节框架与每节引语位）",
}
WUKU_FORM_EXTRA = {
    "视频": "9. 视频形式：口播 200-300 字（60-90 秒）；开头 3 秒钩子成立；给了拍摄/剪辑提示（硬切无转场、口播与画面一一对应）",
    "图文": "9. 图文形式：标题 ≤20 字且关键词前置；话题标签 5-10 个；清单/收藏导向结构",
}

def wuku_rules():
    return load_json(os.path.join(STATIC, "wuku-data.json"), {}).get("rules", [])

def wuku_grab(*kws):
    out = []
    for r in wuku_rules():
        n = (r.get("n") or "").replace(" ", "")
        if any(k in n for k in kws):
            out.append("【%s｜%s】%s" % (r.get("n"), r.get("conf", ""), (r.get("x") or "")[:800]))
    return "\n".join(out)

def wuku_skill_block(platform, form):
    """按 平台×形式 路由到她规则库里对应的 skill；判定为口播时小红书+抖音双发。"""
    if platform == "小红书+抖音":
        blk = (wuku_grab("口播风格skill") + "\n" + wuku_grab("剪辑skill") + "\n" + wuku_grab("小红书风格skill")
               + "\n【双发差异要求】口播视频素材两平台通用；小红书：标题 ≤20 字+5-10 个话题标签+封面提示；抖音：标题带数字/悬念钩子+文案更短+3-5 个话题")
    elif platform == "抖音":
        blk = wuku_grab("口播风格skill") + "\n" + wuku_grab("剪辑skill")
    elif platform == "Threads+X":
        blk = wuku_grab("Threads风格skill") + "\n【Threads 口吻补充（她认可的腔调）】读者称呼「蜜蜜/脆蜜」，自称「主包」，括号内心 OS 每 2-3 段一个"
    elif platform == "公众号":
        blk = "【公众号风格 gene｜viral-style-gene】" + WUKU_GZH_GENE
    else:
        blk = wuku_grab("小红书风格skill")
        if form == "视频":
            blk += "\n" + wuku_grab("口播风格skill") + "\n" + wuku_grab("剪辑skill")
    return blk.strip() or "（该平台暂无已验证 skill，按通用铁律：具体锚点、第一人称在场、无黑名单词）"

def wuku_form_stats():
    try:
        import statistics
        snap = load_json(os.path.join(BASE, "data", "xhs_jocelyn_snapshot.json"), {})
        notes = snap.get("notes", [])
        v = [n.get("likes") or 0 for n in notes if n.get("type") == "video"]
        g = [n.get("likes") or 0 for n in notes if n.get("type") != "video"]
        return "她账号历史（小红书快照 %s）：图文 %d 篇中位赞 %d；视频 %d 篇中位赞 %d" % (
            snap.get("crawled_at"), len(g), int(statistics.median(g)) if g else 0, len(v), int(statistics.median(v)) if v else 0)
    except Exception:
        return ""

def wuku_persona():
    path = os.path.join(DATA, "wuku_persona.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return "按用户提供的账号定位和真实材料写作；经历、数字未知时标[待填]，不编造。"


def wuku_build_prompt(slot, topic, hook, why):
    """底稿一律先按小红书图文写，同时判定这条更适合视频还是图文。"""
    _, my_refs = wuku_style_context()
    return """%s

今天的选题：
- 选题：%s
- 开头钩子方向：%s
- 选题理由（可用于取材的真实背景）：%s
- 槽位类型：%s（口播槽位天然偏视频；攻略/清单类偏图文收藏）

【小红书风格 skill（已验证，底稿必须严格执行）】
%s

【形式判定依据】%s

【范文库里的同类真实范文（学它们的钩子、结构和节奏，禁止抄内容）】
%s

【我发过的内容（风格与选题参考，向它们的语感看齐）】
%s

硬性要求：
1. 先产出小红书图文底稿：标题 + 正文 + 话题标签（后续会按其他平台 skill 改写，所以底稿内容要完整）
2. 事实红线：除「选题理由」明确给出的信息外，一切具体经历细节一律写 [待填：需要什么]，禁止编造看似真实的细节
3. 利他性：每篇必须让读者带走可抄的东西（清单/步骤/避坑/资源），纯情绪输出不合格
4. 钩子前置：图文=首行 30 字内出钩；视频口播=前 3 秒钩子，必须让人留下来看完
5. 她的口吻：具体锚点、第一人称在场、自嘲但不卑微、每段 1-2 句；正文 1-3 处「X 不是 A，而是 B」判断句
6. 判定这条内容更适合「视频」还是「图文」：结合选题性质与她账号历史数据，给一句理由
只输出 JSON：{"form":"视频|图文","form_reason":"一句话理由","title":"标题","body":"正文全文","tags":["标签"],"notes":"封面/发布提示一句话"}""" % (
        wuku_persona(), topic, hook or "（无）", why or "（无）", slot,
        wuku_skill_block("小红书", "图文"), wuku_form_stats(), wuku_relevant_fanwen(topic), my_refs or "（暂无）")

def wuku_relevant_fanwen(topic, k=3, form=None):
    """按选题与范文库的相关性挑真实范文；视频形式优先口播稿/视频脚本类成稿。"""
    data = load_json(os.path.join(STATIC, "wuku-data.json"), {})
    chars = set(topic or "")
    scored = []
    for f in data.get("fanwen_list", []):
        hay = set((f.get("t", "") or "") + (f.get("why", "") or "") + (f.get("pts", "") or "") + (f.get("ex", "") or "")[:200])
        bonus = 8 if (form == "视频" and f.get("ct") in ("口播稿", "视频脚本")) else 0
        scored.append((len(hay & chars) + bonus, f))
    scored.sort(key=lambda x: -x[0])
    picked = [f for s, f in scored[:k] if s > 2] or [f for s, f in scored[:2]]
    return "\n\n".join(
        "《%s》（%s · %s，收藏于%s）\n可复用点：%s\n成稿片段（学这个语感与信息密度）：%s" % (f["t"], f.get("pf", "-"), f.get("ct", "-"), f.get("d", ""), f.get("pts", ""), (f.get("ex") or "")[:420])
        for f in picked)

def wuku_parse_json(text):
    try:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None

def wuku_normalize_draft(dr):
    """兼容 LLM 自由发挥的分平台结构（xiaohongshu/douyin/koubo_script），拍平成编辑框可读格式。"""
    if not isinstance(dr, dict):
        return {"title": "", "body": str(dr)[:2000], "tags": [], "notes": ""}
    if "koubo_script" in dr or "xiaohongshu" in dr:
        xh = dr.get("xiaohongshu") if isinstance(dr.get("xiaohongshu"), dict) else {}
        dy = dr.get("douyin") if isinstance(dr.get("douyin"), dict) else {}
        k = dr.get("koubo_script")
        if isinstance(k, str):
            k = {"body": k}
        k = k if isinstance(k, dict) else {}
        secs = ["【口播稿】"]
        if k.get("hook"):
            secs.append("开头钩子：" + k["hook"])
        if k.get("body"):
            secs.append(k["body"])
        secs.append("")
        secs.append("—— 小红书 ——")
        if xh.get("title"):
            secs.append("标题：" + xh["title"])
        if xh.get("body"):
            secs.append(xh["body"])
        xh_tags = xh.get("tags") or xh.get("topics") or []
        if xh_tags:
            secs.append("标签：" + " ".join(xh_tags))
        if xh.get("cover"):
            secs.append("封面：" + xh["cover"])
        secs.append("")
        secs.append("—— 抖音 ——")
        if dy.get("title"):
            secs.append("标题：" + dy["title"])
        if dy.get("body"):
            secs.append(dy["body"])
        if dy.get("tags"):
            secs.append("话题：" + " ".join(dy["tags"]))
        notes = dr.get("notes") or "；".join(x for x in [xh.get("notes"), dy.get("notes")] if x)
        return {"title": xh.get("title") or dy.get("title") or "", "body": "\n".join(secs), "tags": xh_tags, "notes": notes or ""}
    return dr

def wuku_generate_draft(qs):
    slot = qs.get("slot", ["复盘"])[0]
    topic = qs.get("topic", [""])[0]
    hook = qs.get("hook", [""])[0]
    why = qs.get("why", [""])[0]
    date = qs.get("date", [""])[0]
    regen = qs.get("regen", ["0"])[0] == "1"
    key = "%s|%s" % (date, slot)
    cache = load_json(WUKU_DRAFTS_PATH, {})
    if not regen and key in cache:
        return dict(cache[key], cached=True)
    text, err = call_llm(wuku_build_prompt(slot, topic, hook, why), get_config())
    if err or not text:
        return {"ok": False, "error": err or "empty response"}
    draft = wuku_normalize_draft(wuku_parse_json(text) or {"title": topic, "body": text, "tags": [], "notes": "", "form": "图文", "form_reason": ""})
    if "form" not in draft:
        draft["form"] = "图文"
    out = {"ok": True, "draft": draft, "slot": slot, "date": date, "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    cache[key] = out
    # 重生成底稿时清掉该日的平台改写缓存
    for k in [k for k in cache if k.startswith("adapt:%s|%s|" % (date, slot))]:
        cache.pop(k, None)
    try:
        save_json(WUKU_DRAFTS_PATH, cache)
    except Exception:
        pass
    return out

def wuku_adapt(body):
    """把（可能已被她编辑过的）小红书底稿按目标 平台×形式 的 skill 改写：喂成稿范例、要求亲身经历与足量干货。"""
    text = (body.get("text") or "").strip()
    platform = body.get("platform") or "小红书"
    form = body.get("form") or "图文"
    topic = body.get("topic") or ""
    if form == "视频":
        platform = "小红书+抖音"   # 口播判定 → 双发
    if platform == "抖音":
        form = "视频"
    if platform in ("Threads+X", "公众号"):
        form = "图文"
    if not text:
        return {"ok": False, "error": "底稿为空"}
    date, slot = body.get("date", ""), body.get("slot", "")
    akey = "adapt:%s|%s|%s|%s" % (date, slot, platform, form)
    if date and slot and not body.get("regen"):
        cached = load_json(WUKU_DRAFTS_PATH, {}).get(akey)
        if cached and cached.get("ok"):
            return dict(cached, cached=True)
    desc = WUKU_FORM_DESC.get((platform, form), WUKU_FORM_DESC[("小红书", "图文")])
    skill = wuku_skill_block(platform, form)
    fanshi = wuku_relevant_fanwen(topic or text[:60], 3, form=form)
    length_rule = ("干货类口播写足 500-700 字（约 2-2.5 分钟）：钩子→亲身经历→3-4 个要点（每个要点配具体操作/数字/案例）→利他收尾。规则库里 60-90 秒/200-300 字是旧口径，本次以这条为准"
                   if form == "视频" else "图文写足 800-1000 字，清单体每条都要有可执行细节")
    prompt = """%s

任务：把下面这篇底稿改写并扩写成「%s」，这是要真正发出去的成稿。

【目标平台×形式的风格 skill（严格执行）】
%s

【她的同类成稿范例——逐句学这个语感、密度和说人话的方式，禁止学成 AI 腔】
%s

【底稿（她可能已经手改过，事实以此为准）】
%s

改写硬性要求：
1. 长度：%s。现在的稿子太短太干瘪，必须扩写
2. 亲身经历：把「她的真实经历素材」和「选题理由」里的具体经历织进正文（哪个项目、哪段实习、哪个系统、什么场景），让读者看到是真人在讲真事；素材里实在没有的细节才留 [待填：需要什么]
3. 干货密度：每个要点给到可照做的程度（工具名、步骤、数字、对比），不许一句话带过
4. 利他性与钩子不变：读者带走可抄的东西；口播=前 3 秒钩子、图文=首行 30 字
5. 反 AI 腔：像跟朋友发微信语音那样说话——口语连接词、自嘲、突然插入的具体物件和金额；禁止「首先/其次/总之」模板腔、禁止空泛排比、禁止「赋能/助力/让…更简单」；可用「说实话」「但我要告诉你」「这事儿」这类口头词
只输出 JSON：{"title":"标题","body":"成稿全文","tags":["标签"],"notes":"拍摄/发布提示一句话"}""" % (wuku_persona(), desc, skill, fanshi, text[:3500], length_rule)
    out, err = call_llm(prompt, get_config())
    if err or not out:
        return {"ok": False, "error": err or "empty"}
    draft = wuku_normalize_draft(wuku_parse_json(out) or {"title": "", "body": out, "tags": [], "notes": ""})
    res = {"ok": True, "draft": draft, "platform": platform, "form": form, "created": datetime.datetime.now().strftime("%H:%M")}
    if date and slot:
        cache = load_json(WUKU_DRAFTS_PATH, {})
        cache[akey] = res
        try:
            save_json(WUKU_DRAFTS_PATH, cache)
        except Exception:
            pass
    return res

def wuku_check_text(body):
    """对当前编辑框里的文本，按所选 平台×形式 的 skill 做发布前终检。"""
    text = (body.get("text") or "").strip()
    platform = body.get("platform") or "小红书"
    form = body.get("form") or "图文"
    if not text:
        key = "%s|%s" % (body.get("date", ""), body.get("slot", ""))
        entry = load_json(WUKU_DRAFTS_PATH, {}).get(key)
        if not entry or not entry.get("ok"):
            return {"ok": False, "error": "编辑框为空，先生成或粘贴稿子"}
        dr = entry["draft"]
        text = (dr.get("title") or "") + "\n\n" + (dr.get("body") or "")
    extra = WUKU_FORM_EXTRA.get(form, "")
    if platform == "小红书+抖音":
        extra = "10. 双发：口播素材两平台通用；小红书标题 ≤20 字+标签 5-10 个；抖音标题带数字/悬念钩子；两平台发布差异已分别给出"
    if platform == "Threads+X":
        extra = "9. Threads 形式：主帖 ≤300 字、第一秒能懂；有 X 短版；无硬广感（native）"
    if platform == "公众号":
        extra = "9. 公众号形式：对话体与直接引语；每段有锚点；无导览腔"
    prompt = """你是 Jocelyn 的发布前终检员。目标：%s（%s）。逐项过清单给判定。

【该平台×形式的风格 skill】
%s

%s
%s

【待检稿件（她编辑后的当前版本）】
%s

每项给 ok(true/false) 与一句话 note（不合格必须给具体改法）；全部通过 verdict="可发"，有硬伤 verdict="改后发"。
只输出 JSON：{"verdict":"可发|改后发","when":"今天这条的最优发布时段+一句理由（对照黄金时间表）","items":[{"name":"清单项简称","ok":true,"note":"…"}]}""" % (
        platform, form, wuku_skill_block(platform, form), WUKU_CHECKLIST, extra, text[:3500])
    out, err = call_llm(prompt, get_config())
    if err or not out:
        return {"ok": False, "error": err or "empty"}
    data = wuku_parse_json(out)
    if not data:
        return {"ok": False, "error": "解析失败：" + out[:200]}
    return {"ok": True, "check": data, "platform": platform, "form": form, "checked_at": datetime.datetime.now().strftime("%H:%M")}

def wuku_lark_upsert(table_id, payload, record_id=None):
    cmd = ["lark-cli", "base", "+record-upsert", "--base-token", (os.environ.get("WUKU_BASE_TOKEN") or get_config().get("wuku", {}).get("base_token", "")),
           "--table-id", table_id, "--json", json.dumps(payload, ensure_ascii=False)]
    if record_id:
        cmd += ["--record-id", record_id]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(BASE))
    return r.returncode == 0

def wuku_publish(body):
    """发布打卡 → 全文存档 data/wuku_archive.json + Base 作品库登记（双发拆两平台）。"""
    text = (body.get("text") or "").strip()
    platform = body.get("platform") or "小红书"
    form = body.get("form") or "图文"
    date = body.get("date") or datetime.datetime.now().strftime("%Y-%m-%d")
    slot = body.get("slot") or ""
    if form == "视频" and platform == "小红书":
        platform = "小红书+抖音"
    plats = ["小红书", "抖音"] if platform == "小红书+抖音" else [platform]
    key = "%s|%s" % (date, slot)
    cache = load_json(WUKU_DRAFTS_PATH, {})
    entry = cache.get(key)
    title = (entry.get("draft", {}).get("title") or "").strip() if entry and entry.get("draft") else ""
    if not title:
        for ln in text.split("\n"):
            ln = ln.strip()
            if ln and not ln.startswith("【") and not ln.startswith("——") and not ln.startswith("#"):
                title = re.sub(r"^(标题[:：])\s*", "", ln)[:40]
                break
    if not title:
        title = "未命名发布"
    apath = os.path.join(BASE, "data", "wuku_archive.json")
    items = load_json(apath, [])
    created = []
    for pf in plats:
        items = [i for i in items if not (i.get("date") == date and i.get("platform") == pf)]
        items.append({"date": date, "platform": pf, "title": title, "body": text, "form": form})
        created.append(pf)
        try:
            raw = subprocess.run(["lark-cli", "base", "+record-list", "--base-token", (os.environ.get("WUKU_BASE_TOKEN") or get_config().get("wuku", {}).get("base_token", "")),
                                  "--table-id", WUKU_WORKS_TABLE, "--limit", "200"],
                                 capture_output=True, text=True, timeout=60, cwd=str(BASE)).stdout
            meta = json.loads(raw)
            with open(meta["record_file"]) as f:
                rows = [json.loads(l) for l in f if l.strip()]
            os.remove(meta["record_file"])
            mf = meta["record_file"].replace(".ndjson", ".manifest.json")
            if os.path.exists(mf):
                os.remove(mf)
            exists = any((r.get("作品标题") or "") == title and (r.get("平台") or [""])[0] == pf for r in rows)
            if not exists:
                wuku_lark_upsert(WUKU_WORKS_TABLE, {"作品标题": title, "平台": pf, "发布时间": date + " 21:00:00"})
        except Exception as e:
            print("publish base skip:", e)
    save_json(apath, items)
    return {"ok": True, "platforms": created, "title": title}

def wuku_backfill(body):
    if body.get("metrics"):
        text = json.dumps(body["metrics"], ensure_ascii=False)
    else:
        text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "先把创作者中心的数据文字贴进来"}
    prompt = """从这段创作者数据文字里解析出结构化指标。缺失的字段填 null，不要编造。
只输出 JSON：{"标题":"笔记标题或最像标题的短语","平台":"抖音/小红书/B站/视频号/公众号 之一","发布日期":"YYYY-MM-DD，缺省今天","播放量":0,"点赞":0,"评论":0,"收藏转发":0,"涨粉":0,"完播率":0.0}

原始文字：
%s""" % text[:1200]
    out, err = call_llm(prompt, get_config())
    if err or not out:
        return {"ok": False, "error": err or "empty"}
    import re as _re
    try:
        m = _re.search(r"\{.*\}", out, _re.S)
        metrics = json.loads(m.group(0))
    except Exception:
        return {"ok": False, "error": "解析失败：" + out[:200]}
    title = metrics.get("标题") or "未命名"
    plat = metrics.get("平台") or "小红书"
    date = metrics.get("发布日期") or datetime.datetime.now().strftime("%Y-%m-%d")
    fields = {}
    mapping = [("播放量", "播放量"), ("点赞", "点赞数"), ("评论", "评论数"), ("收藏转发", "收藏/转发数"), ("涨粉", "涨粉数")]
    for src_k, dst_k in mapping:
        v = metrics.get(src_k)
        if isinstance(v, (int, float)):
            fields[dst_k] = int(v)
    cr = metrics.get("完播率")
    if isinstance(cr, (int, float)) and 0 < cr <= 1:
        fields["完播率"] = round(cr, 2)
    elif isinstance(cr, (int, float)) and cr > 1:
        fields["完播率"] = round(cr / 100.0, 2)
    # 找已有记录按标题近似匹配
    raw = subprocess.run(["lark-cli", "base", "+record-list", "--base-token", (os.environ.get("WUKU_BASE_TOKEN") or get_config().get("wuku", {}).get("base_token", "")),
                          "--table-id", WUKU_WORKS_TABLE, "--limit", "200"],
                         capture_output=True, text=True, timeout=60, cwd=str(BASE))
    rid = None
    try:
        meta = json.loads(raw.stdout)
        with open(meta["record_file"]) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        os.remove(meta["record_file"])
        plat_now = fields.get("平台", "")
        for row in rows:
            t = row.get("作品标题") or ""
            same_plat = (row.get("平台") or [""])[0] == plat_now
            if t and (t in title or title in t) and same_plat:
                rid = row["record_id"]
                fields.setdefault("作品标题", t)
                break
    except Exception:
        pass
    fields["平台"] = plat
    if rid:
        fields["最近更新"] = None
        fields.pop("最近更新", None)
        ok = wuku_lark_upsert(WUKU_WORKS_TABLE, fields, record_id=rid)
        action = "更新已有记录"
    else:
        create = {"作品标题": title, "发布时间": date + " 00:00:00"}
        create.update(fields)
        ok = wuku_lark_upsert(WUKU_WORKS_TABLE, create)
        action = "新建记录"
    if not ok:
        return {"ok": False, "error": "写入多维表格失败（看 server 日志）"}
    return {"ok": True, "action": action, "title": title, "metrics": fields}

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_config():
    return load_json(CONFIG_PATH, {})


def parse_json_array(text):
    """从 LLM 输出中提取 JSON 数组（容错：代码块 / 首尾噪声）"""
    if not text:
        return None
    try:
        v = json.loads(text)
        return v if isinstance(v, list) else None
    except Exception:
        pass
    import re
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            v = json.loads(m.group(1))
            return v if isinstance(v, list) else None
        except Exception:
            pass
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            v = json.loads(m.group(0))
            return v if isinstance(v, list) else None
        except Exception:
            pass
    return None


POSTS_PATH = os.path.join(DATA, "posts.json")
PLAYBOOKS_PATH = os.path.join(DATA, "platform_playbooks.json")
STRATEGY_PATH = os.path.join(DATA, "jocelyn_strategy.json")
OPS_PATH = os.path.join(DATA, "daily_ops.json")
FOLLOWERS_PATH = os.path.join(DATA, "followers.json")
STYLE_PATH = os.path.join(DATA, "style_skill.json")
DOUYIN_TOPICS_PATH = os.path.join(DATA, "douyin_topics.json")
EXPERIMENT_PLATFORMS = ["公众号", "知乎", "即刻", "小红书"]

import publisher as _publisher
MATERIALS_PATH = os.path.join(DATA, "materials.json")
ANALYTICS_PATH = os.path.join(DATA, "analytics.json")
TRENDS_PATH = os.path.join(DATA, "trends.json")
ACCOUNT_PATH = os.path.join(DATA, "account_daily.json")
SCHEDULE_PATH = os.path.join(DATA, "schedule.json")  # 已确认排期（日期钉选，同步落草稿箱）
XHS_MCP = "http://localhost:18060/mcp"
XHS_LOCK = threading.Lock()  # xiaohongshu-mcp 单实例，并发搜索会互相打架


def _title_similar(a, b):
    """选题判重：包含 / 8 字窗口命中即算同一个选题"""
    if not a or not b:
        return False
    a, b = a.strip(), b.strip()
    if a in b or b in a:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 8:
        return short in long
    return any(short[i:i + 8] in long for i in range(len(short) - 7))


def xhs_search(keyword, limit=8, retries=3):
    """通过 xiaohongshu-mcp 搜索站内笔记（read-only），返回 [{title, likes, user}]
    平台风控 + 单实例并发冲突会导致间歇性失败：全局锁串行 + 自动重试；仍失败则降级"""
    last_err = None
    with XHS_LOCK:
        for attempt in range(retries):
            body = json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "search_feeds", "arguments": {"keyword": keyword}},
            }).encode("utf-8")
            req = urllib.request.Request(XHS_MCP, data=body, headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                inner = json.loads(data["result"]["content"][0]["text"])
                out = []
                for f in inner.get("feeds", []):
                    nc = f.get("noteCard", {}) or {}
                    out.append({
                        "title": nc.get("displayTitle", "") or "",
                        "likes": (nc.get("interactInfo", {}) or {}).get("likedCount", "") or "",
                        "user": (nc.get("user", {}) or {}).get("nickname", "") or "",
                    })
                    if len(out) >= limit:
                        break
                if out:
                    return out, None
                last_err = "搜索返回为空"
            except Exception as e:
                last_err = f"小红书搜索不可用: {e}"
            time.sleep(4)
    return [], last_err


def benchmark_prompt(account, topic, notes):
    positioning = ACCOUNT_POSITIONING.get(account, "")
    lines = "\n".join(f"- 「{n['title']}」 赞:{n['likes']} @{n['user']}" for n in notes)
    return f"""{positioning}

以下是站内搜索「{topic}」拿到的真实爆贴列表（按热度排序）：

{lines}

任务：作为这个账号的内容策划，从上面爆贴中提炼「可复用的爆款规律」，供我方创作同选题内容时参考。输出 JSON 对象，字段：
- patterns：数组，3-4 条。每条一句话，指出这批爆贴共同的选题结构/标题钩子/内容套路（要具体，如「都用真实数字做成本对比钩子」）
- differentiation：1-2 句话，基于账号人设，指出差异化切入角度（别人没做、只有我们能做的）
- angle：1 句话，给出本次创作的推荐切入角度（能直接当选题用）
- reference_titles：数组，从上面挑出最值得对标的 2 篇标题原文

只输出 JSON。"""

# ---------------- LLM Prompt 模板 ----------------

STYLE_GUIDE = """你是一位小红书大号（个人成长/AI 观察方向）的资深写手。账号人设：有过高强度工作经历，现在重回校园，把这段时间当作 gap 沉淀期，写真实、有活人感的个人体验与行业观察。

写作硬规则：
1. 第一人称、具体场景引入，不居高临下，不说教
2. 无 emoji、无分隔线、无加粗短句堆砌；段落自然连贯，每段 1-3 句
3. 总字数严格控制在 1000 字以内（含标点）
4. 禁用词：天花板、YYDS、绝绝子、封神、宝藏、谁懂啊、家人们、狠狠、闭眼入、我宣布、被问爆了、松弛感、这谁顶得住
5. 不用「不是……而是……」「表面是 X，背后是 Y」这类模板句式
6. 结尾不用问号收束，用一句观察或判断收束
7. 商单内容必须「不说满」：技术表述以品牌确认口径为准，不夸大效果，不编造数据"""

TITLE_GUIDE = """标题方法论：
- 造场景，不要概括观点；从用户处境切入；留一点未完成
- 杠杆混用：数字、我、你、具体动作、轻微反差、半句话
- 6-18 字为宜，像真人会点的话，不像文章摘要
- 禁用词同正文规则"""


FORMAT_GUIDES = {
    "图文": "",
    "视频": """
【视频模式】本篇以短视频/视频笔记形式发布，正文即口播文案与脚本，额外要求：
1. 正文结构按脚本走：3 秒钩子开场 → 主体内容 → 结尾一句收束 + 引导关注
2. 在正文最后单独输出「【拍摄提示】」一段：分镜建议、画面/字幕节奏、是否需要真人出镜（各一句话）
3. 语言更口语，句子更短，适合念出来""",
    "口播稿": "",
}

# 账号内容定位（视频/口播稿生成时按账号注入）
ACCOUNT_POSITIONING = {
    "Jocelyn": """账号内容定位：AI × 创业 × 商务 × 出海方向的个人 IP。
- 人设：前字节 AI 行业从业者，现 Marketing 研一，双视角观察 AI 行业与出海创业
- 内容四象限：AI 行业观察（模型/产品/热点观点拆解）、创业实录（真实决策、算账、取舍）、商务思维（营销/增长/品牌打法拆解）、出海见闻（AI 出海、海外市场、跨境对比）
- 受众：AI 从业者、想做出海的创业者、学生党里的 AI 重度用户
- 口吻：见过一线的过来人，讲判断和依据，不贩卖焦虑，不说空话""",
    "留子手串": """账号内容定位：海外留子手作中药手串创业实录。
- 人设：海外在读留学生，在宿舍手作中药手串（非遗合香珠），从 0 开始晒账本搞钱
- 内容三线：真实搞钱（成本/定价/利润全公开）、手作过程（搓珠 vlog、配方解构）、避坑科普（真假鉴别、材质对比）
- 受众：对手作/养生饰品感兴趣的人、想小成本创业的留学生
- 口吻：敢晒真账本的实在人，先信任后成交""",
    "Yuki.AI": """账号内容定位：AI 资讯与实用工具。
- 内容：AI 工具测评、AI 求职、量化降本、科技热点观点
- 口吻：日更实用向，具体、可复现""",
}

VOICEDRAFT_GUIDE = """口播稿方法论（源自个人爆款口播拆解，1:1 复刻专属风格）：

【固定人设（必须死守）】
普通草根/学生/实操创业者，亲身踩坑、亲自拿到结果、无私分享干货；语气平等、真诚、接地气，没有优越感、没有说教感、不灌鸡汤，只讲真实、落地、能直接照搬的内容。

【开篇硬性结构（3 秒留人，必须反差/钩子）】
1. 先用【真实数据/实操结果/大众痛点】做开篇背书（战绩钩子：涨粉/变现/项目成果；反差钩子：别人焦虑我抓机会、别人踩坑我有捷径；痛点钩子：自制力差/不会 X/单一收入风险）
2. 直接戳破 90% 人的固有错误认知，制造认知反差
3. 一句话预告：本期全程无广、纯实操、保姆级可复刻干货

【正文固定逻辑（强制四段式）】
1. 纠偏破局：推翻行业/大众误区，讲清底层正确逻辑
2. 个人佐证：带入自己踩坑、试错、实操经历，增加真实可信度
3. 分层干货：分 1/2/3 点输出，只讲动作、步骤、工具、方法、避坑，拒绝空泛理论，小白零基础能直接抄作业
4. 认知升华：收尾输出一句记忆点金句（如「收入结构才是关键」「AI 放大认知」「普通人靠杠杆破局」式），拔高维度，破除用户焦虑；随后预埋下期内容预告，引导收藏、关注、互动

【语言语感强制要求】
全程短句、快节奏、断句清晰，适配字幕朗读；口语自然流畅，像和朋友聊天；穿插个人真实感受、踩坑心得；高频金句收尾强化记忆点。

【绝对禁忌（违者不合格）】
禁止官方话术、禁止书面长句、禁止晦涩专业术语、禁止空洞鸡汤、禁止高高在上教学感、禁止悬浮不落地的理论。

【价值内核】
所有干货拒绝理论空谈，统一输出：普通人/小白怎么做、零基础怎么上手、懒人捷径、避坑要点。始终围绕「低门槛、高性价比、不用资源、不用资金、不用天赋」。

【格式要求】
1. 用【开头 0-5s】【中段一：认知铺垫】【中段二：核心干货】【收尾】分段标注（可带时间轴）
2. 按语速约 4.5 字/秒估算，成稿必须落在目标时长内，结尾单独标出「预计时长：约 X 秒」
3. 口播稿正文之后，单独输出【画面分镜】——按上面每个段落，逐段给出画面需求：
   - 画面：出镜方式（真人全脸/半身/画外音）+ 主画面内容（实景拍摄/产品特写/屏幕录制/B-roll/图文卡）
   - 字幕：关键词高亮、数据贴纸、重点字加粗等字幕呈现方式
   - 道具/素材：本段需要提前准备的道具、截图、素材、场景布置
   每段 2-3 行，写清「观众这一秒在屏幕上看到什么」
4. 接着输出【拍摄提示】2 行以内：整体出镜建议（穿着/背景/机位）和字幕节奏总原则
5. 最后单独一行输出建议标签（# 开头，5-8 个）"""


def voicedraft_prompt(payload):
    """口播稿生成（用户爆款口播方法论 + 工作台账号定位）"""
    account = payload.get("account", "Jocelyn")
    positioning = ACCOUNT_POSITIONING.get(account, "")
    topic = payload.get("topic", "")
    title = payload.get("title", "")
    materials = payload.get("materials", "")
    tone = payload.get("tone", "活人感")
    duration = payload.get("duration", 60)
    is_ad = payload.get("is_ad", False)

    ad_note = ""
    if is_ad:
        ad_note = "\n\n【商单模式】这是商单口播。技术表述留有余地（「以品牌确认口径为准」），不说满；「全程无广」预告改为「本期由 XX 赞助但观点真实」口径，正文后附【需向品牌确认的技术口径】清单。"

    return f"""请完全复刻我个人专属的短视频口播文风、人设、节奏、结构，生成一篇适配小红书的完整真人出镜口播逐字稿，严格对标我的爆款风格，不跑偏、不AI感、不书面化。

{positioning}

{VOICEDRAFT_GUIDE}

六、本次创作主题
标题：{title or topic}
选题方向：{topic}
目标时长：约 {duration} 秒
文风偏好：{tone}{ad_note}

参考素材（个人真实经历，优先用作「个人佐证」段）：
{materials or "（无素材，基于选题方向与账号定位发挥，个人经历部分给出可替换的【填入你的经历】占位提示）"}

不要输出其他解释。"""

TREND_PROMPT = """你是一位熟悉海外社交平台（Pinterest、X、Instagram、YouTube）趋势的内容策划，服务对象是一个小红书账号，人设关键词：{identity}。

任务：给出 {count} 条当前（{date}前后）值得跟的热点趋势，要求：
1. 来源覆盖 Pinterest / X / Instagram / YouTube，标注每条的主要来源平台
2. 优先与账号人设相关的趋势（品牌、AI 热点、艺术方向），也可以是全网都在发的破圈热点
3. 每条趋势给出 3 个「热点解读」角度：这个热点可以怎么和账号人设结合，写出小红书笔记的切入方向（一句话一个角度）

用 JSON 数组输出，每项字段：
- title：热点名称（一句话）
- source：主要来源平台（Pinterest / X / Instagram / YouTube / 全网）
- category：分类（品牌 / AI热点 / 艺术 / 破圈热点）
- summary：热点概况（两句话以内）
- angles：数组，恰好 3 个解读角度（每个一句话，能直接当选题方向用）

只输出 JSON。"""


def build_prompt(kind, payload):
    materials = payload.get("materials", "")
    topic = payload.get("topic", "")
    title = payload.get("title", "")
    tone = payload.get("tone", "活人感")
    is_ad = payload.get("is_ad", False)
    fmt = payload.get("format", "图文")

    ad_note = ""
    if is_ad:
        ad_note = "\n\n【商单模式】这是商单内容。必须：1) 技术表述留有余地（如「以品牌确认口径为准」）；2) 不说「数据不上传云端」「完全离线」这类说满的话；3) 在正文后附一段【需向品牌确认的技术口径】清单。"

    fmt_note = FORMAT_GUIDES.get(fmt, "")

    if kind == "trends":
        identity = payload.get("identity", "")
        if not identity:
            profiles = get_config().get("account_profiles", {})
            account = payload.get("account", "")
            identity = profiles.get(account, {}).get("identity", "品牌、AI 热点、艺术、个人成长")
        return TREND_PROMPT.format(
            identity=identity,
            count=payload.get("count", 6),
            date=time.strftime("%Y-%m-%d"),
        )
    if kind == "voicedraft":
        return voicedraft_prompt(payload)

    if kind == "topic":
        return f"""{STYLE_GUIDE}

任务：基于以下素材，为选题「{topic}」生成 3 个内容角度建议。每个角度包含：核心洞察（一句话）、切入场景、内容线判断（流量线/收藏线/人设线）、为什么适合这个账号。

素材：
{materials or "（无素材，仅根据选题方向发挥）"}

文风偏好：{tone}{ad_note}

用 JSON 数组输出，每项含 angle_id、insight、scene、content_line、reason 字段。只输出 JSON。"""
    elif kind == "title":
        return f"""{STYLE_GUIDE}
{TITLE_GUIDE}

任务：为以下选题生成 5 个标题候选，风格各异（犀利吐槽/人话口吻/反常识/悬念/数字）。每个标题给出一句理由。

选题方向：{topic}
参考素材：
{materials or "（无）"}
文风偏好：{tone}

用 JSON 数组输出，每项含 title、style、reason 字段。只输出 JSON。"""
    elif kind == "draft":
        material_primary = ""
        if materials and materials != "（无）":
            material_primary = """
【素材为主】上面的素材是作者本人手写的内容，是这篇稿子的主体。要求：
1. 保留素材的观点、结构、语气、具体细节和真实经历，不要替换观点、不要另起炉灶
2. 你的工作是把它变成一篇合格的小红书稿：优化开头钩子、段落节奏、口语化表达、结尾收束
3. 素材里的第一人称经历原样保留，不虚构新增细节
"""
        return f"""{STYLE_GUIDE}
{fmt_note}
任务：基于以下素材和标题，写一篇小红书{"视频脚本/口播文案" if fmt == "视频" else "长文"}初稿。

标题：{title}
素材：
{materials or "（无）"}
文风偏好：{tone}{ad_note}
{material_primary}
要求：严格 1000 字以内。先输出正文全文，然后在末尾单独一段输出建议标签（# 开头，5-8 个）。不要输出其他解释。"""
    elif kind == "polish":
        draft = payload.get("draft", "")
        instruction = payload.get("instruction", "")
        return f"""{STYLE_GUIDE}
{fmt_note}
任务：根据修改意见打磨下面这篇小红书稿子。

原稿：
{draft}

修改意见：{instruction or "提升活人感，删减冗余说理，保持 1000 字以内"}
文风偏好：{tone}{ad_note}

输出完整修改后的正文，末尾保留标签行。不要输出解释。"""
    return ""


def parse_json_obj(text):
    """从 LLM 输出中提取 JSON 对象（容错：代码块 / 首尾噪声 / 尾逗号）"""
    if not text:
        return None
    candidates = [text]
    import re
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        candidates.append(m.group(1))
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        for attempt in (c, re.sub(r",\s*([}\]])", r"\1", c)):
            try:
                v = json.loads(attempt)
                if isinstance(v, dict):
                    return v
            except Exception:
                pass
    return None


def format_advice(title, content_line):
    """图文 vs 视频建议：规则来自四平台 playbook + 账号已验证的爆款形态"""
    t = title or ""
    collect_kw = ["清单", "攻略", "教程", "方法", "工具", "对比", "指南", "避坑", "怎么", "如何", "定价", "表格", "SOP", "步骤", "测评"]
    story_kw = ["离职", "决定", "故事", "经历", "亲嘴", "生活", "日常", "逃回", "裸辞", "重新", "为什么", "为啥", "怪谈", "勇敢"]
    has_collect = any(k in t for k in collect_kw)
    has_story = any(k in t for k in story_kw)
    if has_collect and not has_story:
        return {"recommend": "图文", "reason": "清单/方法类信息密度高，图文可收藏、制作快；抖音用口播二发即可"}
    if has_story:
        return {"recommend": "视频", "reason": "故事/情绪类口播感染力强，适合真人出镜；小红书可同素材发图文版"}
    if content_line == "人设线":
        return {"recommend": "视频", "reason": "人设线靠语气和真实感，视频优于图文；不想出镜就图文+生活实拍图"}
    if content_line == "收藏线":
        return {"recommend": "图文", "reason": "收藏线核心是「存下来」，图文收藏率高（找Kimi 361藏已验证）"}
    return {"recommend": "图文", "reason": "观点/热点类图文快反最快；若含强情绪可加拍 45 秒口播版发抖音"}


PLATFORM_STRUCT = {
    # 双轨（持穗/Rohini 主轨）
    "公众号": {"title": "...", "abstract": "摘要一句话（会显示在会话列表）", "body": "1500-3000字深度正文", "tags": ["..."]},
    "知乎": {"title": "问句式标题", "body": "1500-3000字回答正文（首三行必须是结论）", "tags": ["..."]},
    "即刻": {"posts": ["动态1（写作过程观察/数据/金句，口语化）", "动态2", "动态3"]},
    "小红书": {"title": "≤20字", "body": "150-300字导览正文", "cards": ["卡片1：钩子总览（大字标题+核心数据）", "卡片2：...", "卡片3：...", "卡片4：..."], "tags": ["..."], "first_comment": "完整拆解在公众号：持穗"},
    "朋友圈": {"text": "≤120字两段内：一句钩子+能带走什么+去哪看", "comment": "发出后自评一句（补充信息位，可选)"},
    # 旧轨（保留兼容）
    "X": {"hook": "首条", "thread": ["第2条", "..."], "hashtags": ["#AI"]},
    "Threads": {"posts": ["帖子1", "帖子2"]},
    "抖音": {"script": "口播稿", "film_tips": "拍摄提示一句话", "caption": "描述区文案+互动问题", "hashtags": ["#AI"]},
}
DEFAULT_PLATFORMS = ["公众号", "知乎", "即刻", "小红书", "朋友圈"]


def studio_prompt(account, topic, material_text, content_line, platforms=None):
    """一键多平台生产：一个选题 → 各平台定制终稿。平台结构由 PLATFORM_STRUCT 驱动。"""
    cfg = get_config()
    prof = cfg.get("account_profiles", {}).get(account, {})
    identity = prof.get("identity", "")
    pen = prof.get("pen_name", "")
    pb = load_json(PLAYBOOKS_PATH, {})
    plats = pb.get("platforms", {})
    names = platforms or DEFAULT_PLATFORMS
    rules = "\n".join(f"【{n}】{json.dumps(plats.get(n, {}), ensure_ascii=False)}" for n in names)
    # 爆帖风格基因（distill_style.py 从真实爆帖提炼，自动注入）
    style = load_json(STYLE_PATH, {})
    style_note = ""
    for n in names:
        s = style.get(n)
        if s:
            style_note += f"\n【{n}·爆帖风格基因】{json.dumps(s, ensure_ascii=False)}"
    if style.get("meta", {}).get("stability_rules"):
        style_note += "\n【稳定度铁律】" + "；".join(style["meta"]["stability_rules"])
    # 语气示范：真实爆款原文 few-shot（去AI味的核心手段——模仿真实语气节奏，不抄内容）
    for n in names:
        ex = (style.get(n) or {}).get("exemplar")
        if not ex:
            ex = ((style.get(n) or {}).get("register_variants") or {}).get("蜜蜜导师体", {}).get("exemplar")
        if ex and ex.get("text"):
            style_note += f"\n【{n}·语气示范（{ex.get('provenance','真实爆款原文')}。{ex.get('usage','模仿语气节奏，禁止抄写内容')}）】\n" + ex["text"][:900]
    # 人设定稿（人设线：任何生成必须符合 persona.md 的内核/表达/红线）
    persona_note = ""
    try:
        with open(os.path.join(DATA, "persona.md"), "r", encoding="utf-8") as f:
            persona_txt = f.read()
        if persona_txt:
            persona_note = "\n\n【人设定稿（必须符合，红线一条不许碰）】\n" + persona_txt[:3500]
    except Exception:
        pass
    struct = {
        "core_angle": "本次核心观点一句话（各平台共用）",
    }
    for n in names:
        if n in PLATFORM_STRUCT:
            struct[n] = PLATFORM_STRUCT[n]
    pen_note = f"\n统一署名：{pen}（每个平台的结尾/卡片署名都用它）" if pen else ""
    return f"""你是一次性内容生产引擎。同一个选题，为 {len(names)} 个平台各产出一份【可直接发布、无需再加工】的终稿。中间过程不要输出，只输出最终 JSON。

账号：{account}
人设：{identity}{pen_note}
选题类型：{content_line or '未指定（按内容自然判断）'}
选题：{topic}
{('原稿内容（在其基础上改写适配，不丢核心信息，原文数据必须保留）：' + material_text[:2200]) if material_text else ''}

平台规则（必须严格遵守）：

{rules}
{style_note}{persona_note}

硬性要求：
1. 各平台内容必须是同一选题的「平台母语重写」，不是互相复制删减
2. 每个平台的钩子/结构/字数/标签习惯完全按上面规则执行，越界即错
3. 拆解类内容必须有数据锚点；没有公开数据的判断要标注「推测」
4. 每篇至少一个可截图的框架/表格（作品集素材）
5. 利他性（一票否决）：每篇必须给读者可直接带走的价值——可抄的方法/清单/判断框架/信息差。写完自问「读者看完赚到了什么」，答不上来就重写
6. 平台格式严禁串用：编号连帖（1/2/3）只属于 X；Threads 是单条独立短帖（无编号无标签堆砌）；小红书是笔记（蜜蜜体+标签+首评导流），绝不能出现推文串格式；各平台只用自己的规则与语气
6. 不要输出任何 JSON 之外的解释文字

输出 JSON 对象，结构：
{json.dumps(struct, ensure_ascii=False, indent=1)}"""


def call_llm(prompt, config):
    """调用 LLM，三层回退：
    1. config.json 里配置的自定义接口（用户手动填入），超时/失败自动降级 fallback_models
    2. ZCode 云接口（zcode.z.ai，用 ZCODE_API_KEY 环境变量）
    3. 报错提示
    """
    temperature = config.get("llm", {}).get("temperature", 0.7)

    # 1) 用户自定义接口（主模型 + 降级模型链）
    llm = config.get("llm", {})
    api_key = llm.get("api_key", "")
    base_url = llm.get("base_url", "https://openrouter.ai/api/v1/chat/completions")
    if api_key:
        models = [llm.get("model", "kimi-k2.5")] + list(llm.get("fallback_models", []))
        last_err = None
        for model in models:
            body = json.dumps({
                "model": model,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8")
            req = urllib.request.Request(base_url, data=body, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key,
            }, method="POST")
            try:
                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        return data["choices"][0]["message"]["content"], None
                except Exception as e:
                    if "CERTIFICATE" not in str(e).upper():
                        raise
                    # 网关证书过期时降级为不校验（仅此内部工具链使用）
                    ctx = ssl._create_unverified_context()
                    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        return data["choices"][0]["message"]["content"], None
            except urllib.error.HTTPError as e:
                last_err = f"LLM({model}) HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}"
            except Exception as e:
                last_err = f"LLM({model}) 调用失败: {e}"
        return None, last_err

    # 2) ZCode 云接口
    model = llm.get("model", "zcode")
    body = json.dumps({
        "model": model,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    zcode_key = os.environ.get("ZCODE_API_KEY", "")
    zcode_url = os.environ.get("ZCODE_BASE_URL", "https://zcode.z.ai") + "/v1/chat/completions"
    if zcode_key:
        req = urllib.request.Request(zcode_url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + zcode_key,
        }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"], None
        except urllib.error.HTTPError as e:
            return None, f"ZCode 接口 HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
        except Exception as e:
            return None, f"ZCode 接口调用失败: {e}"

    # 3) 都不可用
    return None, ("未找到可用的 AI 接口。请任选其一：\n"
                  "1) 在 config.json 里填入 llm.api_key（OpenRouter 或任意 OpenAI 兼容接口）\n"
                  "2) 设置环境变量 ZCODE_API_KEY 后重启本服务（接 ZCode 云接口）")


# ---------------- HTTP Handler ----------------


def _fetch_original_text(url):
    """抓原文：GitHub 仓库→README；一般网页→正文提取。返回 (ok, title, text_or_error)"""
    import subprocess as _sp
    import re as _re
    import html as _h
    try:
        if "github.com/" in url and "/releases" not in url:
            parts = url.rstrip("/").split("github.com/")[1].split("/")
            repo = "/".join(parts[:2])
            for br in ("main", "master"):
                raw_url = f"https://raw.githubusercontent.com/{repo}/{br}/README.md"
                r = _sp.run(["curl", "-sL", "--max-time", "20", raw_url],
                            capture_output=True, text=True, timeout=25)
                if r.stdout and not r.stdout.startswith("404"):
                    t = r.stdout.strip()[:4500]
                    return (True, repo, t) if len(t) >= 200 else (False, repo, "README 太短或抓取失败")
            return False, repo, "README 拉取失败（仓库可能无 README）"
        r = _sp.run(["curl", "-sL", "--max-time", "20", url,
                     "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"],
                    capture_output=True, text=True, timeout=25)
        page = r.stdout or ""
        mt = _re.search(r"<title[^>]*>(.*?)</title>", page, _re.S | _re.I)
        title = _h.unescape(_re.sub(r"\s+", " ", mt.group(1))).strip()[:120] if mt else url[:80]
        page = _re.sub(r"<(script|style)[\s\S]*?</\1>", "", page)
        page = _re.sub(r"<[^>]+>", " ", page)
        text = _h.unescape(_re.sub(r"[ \t]+", " ", page))
        text = _re.sub(r"\n\s*\n+", "\n", text).strip()[:4500]
        if len(text) < 200:
            return False, title, "原文抓到了但内容太少（站点反爬），请打开链接手动复制正文"
        return True, title, text
    except Exception as e:
        return False, url[:80], f"抓取失败: {str(e)[:80]}"


def _resolve_topic_source(post):
    """解析选题的素材来源 URL：source_url 字段 > note 里的 owner/repo > GitHub 搜索裸仓库名"""
    import re as _re
    import subprocess as _sp
    if post.get("source_url"):
        return post["source_url"]
    note = post.get("note") or ""
    m = _re.search(r"(https?://[^\s）)]+)", note)
    if m:
        return m.group(1)
    m2 = _re.search(r"真实锚点[：:]\s*([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)", note)
    if m2:
        return "https://github.com/" + m2.group(1)
    m3 = _re.search(r"真实锚点[：:]\s*([A-Za-z0-9_.\-]{3,40})", note)
    name = None
    if m3:
        name = m3.group(1)
    else:
        # 兜底：标题开头的 ASCII 词当仓库名（如「claude-mem 9.7万星：…」）
        mt = _re.match(r"^([A-Za-z][A-Za-z0-9_.\-]{2,40})(?:\s|：|:|$)", post.get("title") or "")
        if mt:
            name = mt.group(1)
    if name:
        try:
            r = _sp.run(["curl", "-s", "--max-time", "15",
                         f"https://api.github.com/search/repositories?q={name}&per_page=1"],
                        capture_output=True, text=True, timeout=20)
            items = json.loads(r.stdout).get("items", [])
            if items:
                return items[0]["html_url"]
        except Exception:
            pass
    return None

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def end_headers(self):
        # 开发期：静态资源（JS/CSS/HTML）不缓存，确保改完即生效
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    def _send_json(self, obj, code=200):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _read_json(self):
        try:
            return json.loads(self._read_body().decode("utf-8") or "{}")
        except Exception:
            return {}

    # ---------- GET ----------
    def do_GET(self):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)
        if growth.handle(self, "GET", path, BASE, call_llm, get_config):
            return

        if path == "/api/config":
            cfg = get_config()
            safe = dict(cfg)
            if safe.get("llm", {}).get("api_key"):
                safe["llm"] = dict(safe["llm"])
                safe["llm"]["api_key_set"] = True
                safe["llm"].pop("api_key", None)
            safe["zcode_connected"] = bool(os.environ.get("ZCODE_API_KEY"))
            return self._send_json(safe)

        if path == "/api/materials":
            return self._send_json(load_json(MATERIALS_PATH, []))

        if path == "/api/posts":
            posts = load_json(POSTS_PATH, [])
            account = qs.get("account", [None])[0]
            if account:
                posts = [p for p in posts if p.get("account") == account]
            # 附加图文/视频形式建议
            for p in posts:
                p["format_advice"] = format_advice(p.get("topic") or p.get("title", ""), p.get("content_line", ""))
            return self._send_json(posts)

        if path == "/api/playbooks":
            return self._send_json(load_json(PLAYBOOKS_PATH, {}))

        if path == "/api/publish/status":
            return self._send_json({"x_auto": _publisher.x_configured()})

        if path == "/api/ops/today":
            # 今日运营任务卡（auto_ops 引擎每日生成，落 data/daily_ops.json）
            ops = load_json(OPS_PATH, {})
            return self._send_json(ops)

        if path == "/api/wuku/draft":
            # 五库日报初稿：按当天选题+平台风格 skill 生成（带按日缓存）
            return self._send_json(wuku_generate_draft(qs))

        if path == "/api/wuku/check":
            # 发布前 AI 终检（GET 兼容：检缓存底稿）
            return self._send_json(wuku_check_text({k: v[0] for k, v in qs.items()}))

        if path.startswith("/data/uploads/"):
            # 上传文件与成品配图的静态服务
            fname = os.path.basename(path)
            dest = os.path.join(UPLOADS, fname)
            if os.path.exists(dest):
                ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                         "pdf": "application/pdf", "webp": "image/webp"}.get(fname.rsplit(".", 1)[-1].lower(), "application/octet-stream")
                with open(dest, "rb") as f:
                    raw = f.read()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(raw)
                return
            return self._send_json({"error": "文件不存在"}, 404)

        if path == "/api/cases/latest":
            # 海外营销案例库：HN 实抓（growth/marketing/pricing/launch）+ Product Hunt 发布动作；X 明日配额恢复后并入
            import urllib.request as _u2
            import re as _re2
            cases = []
            queries = ["growth marketing", "marketing case study", "pricing strategy", "product launch"]
            import time as _t
            _now = int(_t.time())
            for q in queries:
                try:
                    # 最近 60 天 + 有热度，按时间倒序（用户要最新的）
                    req = _u2.Request(
                        f"https://hn.algolia.com/api/v1/search_by_date?query={urllib.parse.quote(q)}&tags=story&hitsPerPage=6&numericFilters=points>5,created_at_i>{_now - 60 * 86400}",
                        headers={"User-Agent": "Mozilla/5.0"})
                    with _u2.urlopen(req, timeout=12) as r:
                        d = json.loads(r.read().decode())
                    for h in d.get("hits", []):
                        ts = h.get("created_at", "")[:10]
                        cases.append({
                            "title": (h.get("title") or "")[:90],
                            "source": "HackerNews", "meta": f"{h.get('points', 0)}分·{ts}",
                            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                        })
                except Exception:
                    continue
            try:
                req = _u2.Request("https://www.producthunt.com/feed", headers={"User-Agent": "Mozilla/5.0"})
                with _u2.urlopen(req, timeout=12) as r:
                    rss = r.read().decode("utf-8", "ignore")
                for t, u in zip(
                        _re2.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", rss)[1:6],
                        _re2.findall(r"<link>(.*?)</link>", rss)[1:6] or [""] * 5):
                    cases.append({"title": t[:90], "source": "ProductHunt",
                                  "meta": "最新发布动作", "url": u})
            except Exception:
                pass
            # 去重（按标题前 40 字）
            seen, uniq = set(), []
            for c in cases:
                k = c["title"][:40]
                if k not in seen:
                    seen.add(k)
                    uniq.append(c)
            return self._send_json({"cases": uniq[:18]})

        if path == "/api/hot/today":
            # 今日热点：从自家AI日报最新期实抓（GitHub trending + 论文），生成可直接入库的热点选题
            import datetime as _dt
            import re as _re
            import urllib.request as _u
            latest = None
            for back in range(0, 5):
                d = _dt.date.today() - _dt.timedelta(days=back)
                url = f"https://raw.githubusercontent.com/shenjiaying49-ship-it/ai-daily-news/main/daily-{d.isoformat()}.html"
                try:
                    req = _u.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with _u.urlopen(req, timeout=12) as r:
                        latest = (d.isoformat(), r.read().decode("utf-8", "ignore"))
                    break
                except Exception:
                    continue
            if not latest:
                return self._send_json({"error": "最近 5 天都没拉到日报（管线可能停更）"}, 502)
            dstr, html = latest
            text = _re.sub(r"<[^>]+>", "\n", _re.sub(r"<script[\s\S]*?</script>", "", html))
            import html as _h
            lines = [_h.unescape(l.strip()) for l in text.split("\n") if l.strip()]
            hots = []
            for i, l in enumerate(lines):
                if _re.match(r"^★\s*[\d,]+", l):
                    for j in range(i - 1, max(0, i - 6), -1):
                        c = lines[j]
                        if len(c) > 4 and not _re.search(r"(↗|★|arXiv|http)", c):
                            hots.append({"name": c[:70], "stat": l[:60]})
                            break
                if len(hots) >= 6:
                    break
            return self._send_json({"date": dstr, "hots": hots})

        if path == "/api/experiment":
            # 一个月实验看板：周度粉丝快照 + 涨粉归因 + 四类选题对比 + 三选一决策
            snaps = load_json(FOLLOWERS_PATH, [])
            posts = load_json(POSTS_PATH, [])
            account = qs.get("account", ["持穗Rohini"])[0] or "持穗Rohini"
            my = [p for p in posts if p.get("account") == account]

            # 周度序列（按平台）
            by_date = {}
            for s in snaps:
                by_date.setdefault(s.get("date", ""), {})[s.get("platform", "")] = {
                    "followers": s.get("followers", 0), "reads": s.get("reads", 0),
                    "wechat": s.get("wechat", 0)}
            dates = sorted(by_date)
            series = {p: [] for p in EXPERIMENT_PLATFORMS}
            for d in dates:
                for p in EXPERIMENT_PLATFORMS:
                    v = by_date[d].get(p)
                    series[p].append({"date": d, **v} if v else {"date": d, "followers": None, "reads": 0, "wechat": 0})

            # 周环比
            deltas = {}
            if len(dates) >= 2:
                a, b = by_date[dates[-2]], by_date[dates[-1]]
                for p in EXPERIMENT_PLATFORMS:
                    fa, fb = (a.get(p) or {}).get("followers"), (b.get(p) or {}).get("followers")
                    deltas[p] = (fb - fa) if (fa is not None and fb is not None) else None

            # 已发布篇目（含四类标记）与归因提示
            published = [{"title": (p.get("topic") or p.get("title", ""))[:36],
                          "platform": p.get("platform", ""), "line": p.get("content_line", ""),
                          "date": (p.get("updated") or p.get("created") or "")[:10]}
                         for p in my if p.get("status") == "已发布"]

            # 四类选题对比（按 analytics 的阅读/互动）
            analytics = load_json(ANALYTICS_PATH, [])
            type_stats = {}
            for a_ in analytics:
                pid = a_.get("post_id")
                post = next((p for p in my if p.get("id") == pid), None)
                if not post:
                    continue
                t = post.get("content_line", "") or "未分类"
                b = type_stats.setdefault(t, {"count": 0, "views": 0, "likes": 0, "collects": 0})
                b["count"] += 1
                for k in ("views", "likes", "collects"):
                    try:
                        b[k] += int(str(a_.get(k) or 0).replace(",", "") or 0)
                    except Exception:
                        pass

            cfg = get_config()
            return self._send_json({
                "dates": dates,
                "series": series,
                "deltas": deltas,
                "published": published,
                "type_stats": type_stats,
                "verticals": cfg.get("vertical_candidates", {}),
                "platforms": EXPERIMENT_PLATFORMS,
            })

        if path == "/api/analytics":
            return self._send_json(load_json(ANALYTICS_PATH, []))

        if path == "/api/trends":
            account = qs.get("account", [""])[0] or "Jocelyn"
            data = load_json(TRENDS_PATH, {})
            # 兼容旧格式（单账号平铺）
            if "items" in data:
                data = {"Jocelyn": data}
            return self._send_json(data.get(account, {"updated": "", "items": []}))

        if path == "/api/account":
            account = qs.get("account", [None])[0]
            snaps = load_json(ACCOUNT_PATH, [])
            snaps = [s for s in snaps if not account or s.get("account", "Jocelyn") == account]
            return self._send_json(snaps[-1] if snaps else {})

        if path == "/api/summary":
            return self._send_json(self._summary(qs.get("account", [None])[0]))

        if path == "/api/studio/schedule":
            # 选题日历：只排新选题（已发布、旧稿待同步一律不再排）；确认过的排期钉在日期上并落草稿箱
            import datetime as _dt
            all_posts = load_json(POSTS_PATH, [])
            account = qs.get("account", ["持穗Rohini"])[0] or "持穗Rohini"
            posts = [p for p in all_posts if p.get("account") == account]
            confirmed = [c for c in load_json(SCHEDULE_PATH, [])
                         if c.get("account", account) == account]

            # 已发布的选题一律不再进日历
            published_titles = [(p.get("topic") or p.get("title") or "").strip()
                                for p in posts if p.get("status") == "已发布"]

            topics = []
            def add_topic(title, line, origin, state):
                title = (title or "").strip()
                if not title:
                    return
                if any(_title_similar(title, t) for t in published_titles):
                    return
                if any(_title_similar(title, t["title"]) for t in topics):
                    return
                topics.append({"title": title, "line": line or "方法类", "origin": origin, "state": state})

            # 1) 已生成待发（整组无一篇发布过的）
            groups = {}
            for p in posts:
                if p.get("group_id"):
                    groups.setdefault(p["group_id"], []).append(p)
            for gid, ps in groups.items():
                ps = sorted(ps, key=lambda q: q.get("created", ""))
                if not any(q.get("status") == "已发布" for q in ps):
                    add_topic(ps[0].get("topic") or ps[0].get("title", ""),
                              ps[0].get("content_line", ""), "已生成待发", "已生成")
            # 2) 新选题（素材/草稿/待确认，且不属于任何组）
            for p in posts:
                if p.get("status") in ("素材", "草稿", "待确认") and not p.get("group_id"):
                    add_topic(p.get("topic") or p.get("title", ""),
                              p.get("content_line", ""), "新选题", "待生成")
            # 3) 已确认的从浮动池移除（钉在日期上，不再轮换）
            for c in confirmed:
                topics = [t for t in topics if not _title_similar(t["title"], c.get("topic", ""))]

            # 内容线轮换：同类不连发，顺序优先
            ordered = []
            pool = list(topics)
            prev_line = ""
            while pool:
                pick = next((t for t in pool if t["line"] != prev_line), pool[0])
                ordered.append(pick)
                prev_line = pick["line"]
                pool.remove(pick)

            today = _dt.date.today()
            wd_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            # 每日主发平台提示（按 playbook 发布位；同一选题仍会四平台齐发，这里只提示重心）
            day_focus = {0: "深度轨：公众号/知乎", 1: "轻轨：小红书卡片版", 2: "深度轨：公众号/抖音",
                         3: "深度轨：知乎", 4: "轻轨：小红书卡片版", 5: "轻轨：抖音口播", 6: "复盘"}
            days = []
            di = 0
            for off in range(28):
                d = today + _dt.timedelta(days=off)
                if d.weekday() == 6:
                    days.append({"date": d.isoformat(), "weekday": "周日", "rest": True,
                                 "topic": "复盘 15 分钟：看涨粉数据 + 定下周选题", "line": "", "state": "",
                                 "focus": "复盘", "confirmed": False})
                    continue
                conf = next((c for c in confirmed if c.get("date") == d.isoformat()), None)
                if conf:
                    days.append({"date": d.isoformat(), "weekday": wd_names[d.weekday()], "rest": False,
                                 "topic": conf.get("topic", ""), "line": conf.get("line", ""),
                                 "origin": "已确认", "state": "已确认", "focus": day_focus[d.weekday()],
                                 "confirmed": True})
                    continue
                t = ordered[di % len(ordered)] if ordered else None
                di += 1
                days.append({"date": d.isoformat(), "weekday": wd_names[d.weekday()], "rest": False,
                             "topic": t["title"] if t else "（选题用完，去热点/案例库补充）",
                             "line": t["line"] if t else "", "origin": t["origin"] if t else "",
                             "state": t["state"] if t else "", "focus": day_focus[d.weekday()],
                             "confirmed": False})
            return self._send_json({"start": today.isoformat(), "days": days,
                                    "queue_total": len(ordered),
                                    "confirmed_total": len(confirmed),
                                    "confirmed": sorted(confirmed, key=lambda c: c.get("date", "")),
                                    "line_rotation": "只排新选题（已发布/旧稿不再排）· 同类内容不连发 · 周日复盘 · 确认后钉日期并入草稿箱"})

        return super().do_GET()

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path
        if growth.handle(self, "POST", path, BASE, call_llm, get_config):
            return

        if path == "/api/wuku/backfill":
            # 贴创作者中心文字 → LLM 解析 → 回填作品库
            return self._send_json(wuku_backfill(self._read_json()))

        if path == "/api/wuku/check":
            # 对编辑框当前文本按 平台×形式 skill 终检
            return self._send_json(wuku_check_text(self._read_json()))

        if path == "/api/wuku/adapt":
            # 小红书底稿 → 目标平台×形式 改写
            return self._send_json(wuku_adapt(self._read_json()))

        if path == "/api/wuku/publish":
            # 发布打卡 → 全文归档 + Base 作品库登记
            return self._send_json(wuku_publish(self._read_json()))

        if path == "/api/materials":
            body = self._read_json()
            items = load_json(MATERIALS_PATH, [])
            item = {
                "id": uuid.uuid4().hex[:8],
                "created": time.strftime("%Y-%m-%d %H:%M"),
                "type": body.get("type", "文本"),
                "tags": body.get("tags", []),
                "title": body.get("title", "")[:80] or "未命名素材",
                "content": body.get("content", ""),
                "file": body.get("file"),
            }
            items.append(item)
            save_json(MATERIALS_PATH, items)
            return self._send_json(item)

        if path == "/api/materials/delete":
            body = self._read_json()
            items = load_json(MATERIALS_PATH, [])
            items = [m for m in items if m.get("id") != body.get("id")]
            save_json(MATERIALS_PATH, items)
            return self._send_json({"ok": True})

        if path == "/api/upload":
            # multipart 简易解析：前端用 FormData，单字段 file
            ctype = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ctype:
                return self._send_json({"error": "需要 multipart 上传"}, 400)
            raw = self._read_body()
            boundary = ctype.split("boundary=")[-1].encode()
            parts = raw.split(b"--" + boundary)
            for part in parts:
                if b"filename=" in part:
                    head, _, content = part.partition(b"\r\n\r\n")
                    content = content.rstrip(b"\r\n-")
                    fname = "file"
                    for seg in head.decode("utf-8", "ignore").split(";"):
                        seg = seg.strip()
                        if seg.startswith("filename="):
                            fname = seg.split("=", 1)[1].strip().strip('"')
                    safe_name = os.path.basename(fname) or "file"
                    # 中文文件名安全化
                    name, ext = os.path.splitext(safe_name)
                    safe_name = uuid.uuid4().hex[:8] + (ext or "")
                    dest = os.path.join(UPLOADS, safe_name)
                    with open(dest, "wb") as f:
                        f.write(content)
                    return self._send_json({
                        "ok": True,
                        "file": "/data/uploads/" + safe_name,
                        "original_name": fname,
                    })
            return self._send_json({"error": "未找到文件"}, 400)

        if path == "/api/generate":
            body = self._read_json()
            kind = body.get("kind", "draft")
            prompt = build_prompt(kind, body)
            if not prompt:
                return self._send_json({"error": "未知的生成类型"}, 400)
            text, err = call_llm(prompt, get_config())
            if err:
                return self._send_json({"error": err}, 500)
            return self._send_json({"result": text})

        if path == "/api/cases/fetch_original":
            body = self._read_json()
            url = (body.get("url") or "").strip()
            if not url:
                return self._send_json({"error": "缺少 url"}, 400)
            ok, title, text_or_err = _fetch_original_text(url)
            if not ok:
                return self._send_json({"error": text_or_err}, 422)
            return self._send_json({"ok": True, "title": title, "text": text_or_err})

        if path == "/api/studio/generate":
            # 一键多平台：一个选题 → 各平台终稿，直接落库。platforms 可传子集（如旧稿同步只出 X/Threads/抖音）
            body = self._read_json()
            account = body.get("account", "Jocelyn")
            topic = (body.get("topic") or "").strip()
            content_line = body.get("content_line", "")
            material_text = (body.get("material_text") or "").strip()
            platforms = body.get("platforms") or None
            source_post_id = body.get("source_post_id", "")
            if not topic:
                return self._send_json({"error": "请填写选题"}, 400)
            # 链接即素材：识别输入里的 URL，自动抓原文
            import re as _reu
            urls = _reu.findall(r"https?://[^\s，。；）)""']+", (topic + " " + material_text))[:2]
            fetched_note = ""
            source_url_hit = ""
            if urls:
                fetched_parts = []
                for u in urls:
                    ok_u, title_u, text_u = _fetch_original_text(u)
                    if ok_u:
                        fetched_parts.append(f"【抓取素材：{title_u}（{u}）】\n{text_u[:3500]}")
                        source_url_hit = source_url_hit or u
                if fetched_parts:
                    fetched_note = f"（已自动抓取 {len(fetched_parts)} 个链接的原文作素材）"
                    material_text = ("\n\n".join(fetched_parts) + "\n\n" + material_text)[:6500]
                    topic = _reu.sub(r"https?://[^\s，。；）)""']+", "", topic).strip() or topic
            prompt = studio_prompt(account, topic, material_text, content_line, platforms)
            text, err = call_llm(prompt, get_config())
            data = parse_json_obj(text)
            if not data and not err:
                # 模型偶发格式跑偏：自动重试一次
                text, err = call_llm(prompt + "\n\n（上一次输出无法解析。这次严格只输出 JSON 对象，不要任何前后缀文字。）", get_config())
                data = parse_json_obj(text)
            if err:
                return self._send_json({"error": err}, 500)
            if not data:
                return self._send_json({"error": "AI 返回格式异常，请重试一次", "raw": (text or "")[:400]}, 502)

            xhs = data.get("小红书") or {}
            x = data.get("X") or {}
            th = data.get("Threads") or {}
            dy = data.get("抖音") or {}
            gzh = data.get("公众号") or {}
            zh = data.get("知乎") or {}
            jk = data.get("即刻") or {}
            pyq = data.get("朋友圈") or {}
            x_body = "\n\n".join([p for p in [x.get("hook", "")] + list(x.get("thread") or []) if p])
            all_specs = [
                ("公众号", gzh.get("title", topic), gzh.get("body", ""), gzh.get("tags", []),
                 {"abstract": gzh.get("abstract", "")}),
                ("知乎", zh.get("title", topic), zh.get("body", ""), zh.get("tags", []), {}),
                ("即刻", topic, "\n— — —\n".join(jk.get("posts") or []), [], {"note": "多条独立动态，分开发"}),
                ("小红书", xhs.get("title", topic), xhs.get("body", ""), xhs.get("tags", []),
                 {"cards": xhs.get("cards", []), "first_comment": xhs.get("first_comment", "")}),
                ("朋友圈", topic[:40], pyq.get("text", ""), [],
                 {"moment_comment": pyq.get("comment", "")}),
                ("X", (x.get("hook") or topic)[:60], x_body, x.get("hashtags", []), {}),
                ("Threads", topic, "\n— — —\n".join(th.get("posts") or []), [],
                 {"note": "两条独立短帖，分两次发"}),
                ("抖音", topic, dy.get("script", ""), dy.get("hashtags", []),
                 {"film_tips": dy.get("film_tips", ""), "caption": dy.get("caption", "")}),
            ]
            specs = [s for s in all_specs if not platforms or s[0] in platforms]
            group_id = uuid.uuid4().hex[:8]
            now = time.strftime("%Y-%m-%d %H:%M")
            posts = load_json(POSTS_PATH, [])
            saved_ids = []
            for plat, title, pbody, tags, extra in specs:
                p = {
                    "id": uuid.uuid4().hex[:8],
                    "account": account,
                    "title": title or topic,
                    "body": pbody,
                    "topic": topic,
                    "content_line": content_line,
                    "tags": tags,
                    "is_ad": False,
                    "status": "待确认",
                    "platform": plat,
                    "group_id": group_id,
                    "created": now,
                    "updated": now,
                }
                if source_post_id:
                    p["source_post_id"] = source_post_id
                    p["source"] = "xhs_sync"
                p.update(extra)
                posts.append(p)
                saved_ids.append(p["id"])
            if source_url_hit:
                for p in posts:
                    if p.get("group_id") == group_id and not p.get("source_url"):
                        p["source_url"] = source_url_hit
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True, "group_id": group_id, "result": data, "saved_ids": saved_ids,
                                    "fetched": fetched_note, "source_url": source_url_hit})

        if path == "/api/studio/delete-group":
            body = self._read_json()
            posts = load_json(POSTS_PATH, [])
            posts = [p for p in posts if p.get("group_id") != body.get("group_id")]
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True})

        if path == "/api/studio/schedule/confirm":
            # 确认排期：钉住日期 + 落草稿箱（已生成的组不重复建稿；素材稿升级为草稿并打排期日）
            body = self._read_json()
            date = (body.get("date") or "").strip()
            topic = (body.get("topic") or "").strip()
            line = (body.get("line") or "").strip()
            account = body.get("account") or "持穗Rohini"
            if not date or not topic:
                return self._send_json({"error": "缺少日期或选题"}, 400)
            items = load_json(SCHEDULE_PATH, [])
            items = [c for c in items if not (
                c.get("account", account) == account and (c.get("topic") == topic or c.get("date") == date))]
            items.append({"date": date, "topic": topic, "line": line, "account": account,
                          "confirmed_at": time.strftime("%Y-%m-%d %H:%M")})
            save_json(SCHEDULE_PATH, items)

            posts = load_json(POSTS_PATH, [])
            now = time.strftime("%Y-%m-%d %H:%M")
            post_id = ""
            for p in posts:
                if (p.get("account") == account and not p.get("group_id")
                        and (p.get("topic") or p.get("title") or "").strip() == topic):
                    if p.get("status") == "已发布":
                        return self._send_json({"error": "这个选题已经发布过了，不能重复排期"}, 400)
                    if p.get("status") == "素材":
                        p["status"] = "草稿"
                    p["schedule_date"] = date
                    p["updated"] = now
                    post_id = p["id"]
                    break
            if not post_id:
                has_group = any(p.get("account") == account and p.get("group_id")
                                and (p.get("topic") or "").strip() == topic for p in posts)
                if not has_group:
                    post_id = uuid.uuid4().hex[:8]
                    posts.append({"id": post_id, "account": account, "title": topic, "topic": topic,
                                  "content_line": line or "方法类", "body": "", "tags": [], "is_ad": False,
                                  "status": "草稿", "schedule_date": date, "created": now, "updated": now})
                else:
                    # 组稿已生成：把排期日打到组里每篇，草稿箱卡片显示 📅 徽章（稿子不重复建）
                    for p in posts:
                        if (p.get("account") == account and p.get("group_id")
                                and (p.get("topic") or "").strip() == topic):
                            p["schedule_date"] = date
                            p["updated"] = now
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True, "post_id": post_id, "confirmed_total": len(items)})

        if path == "/api/studio/schedule/unconfirm":
            # 取消确认：日期释放回浮动池，草稿箱里的稿子保留（只去掉排期日）
            body = self._read_json()
            date = (body.get("date") or "").strip()
            items = load_json(SCHEDULE_PATH, [])
            items = [c for c in items if c.get("date") != date]
            save_json(SCHEDULE_PATH, items)
            posts = load_json(POSTS_PATH, [])
            for p in posts:
                if p.get("schedule_date") == date and p.get("status") != "已发布":
                    p.pop("schedule_date", None)
                    p["updated"] = time.strftime("%Y-%m-%d %H:%M")
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True, "confirmed_total": len(items)})

        if path == "/api/posts/link":
            # 记录发布链接：发布后把各平台帖子链接贴回来，存档到稿件上
            body = self._read_json()
            pid = (body.get("post_id") or "").strip()
            url = (body.get("url") or "").strip()
            if not pid or not url:
                return self._send_json({"error": "缺少 post_id 或链接"}, 400)
            posts = load_json(POSTS_PATH, [])
            hit = None
            for p in posts:
                if p.get("id") == pid:
                    p["published_link"] = url
                    p["updated"] = time.strftime("%Y-%m-%d %H:%M")
                    hit = p
                    break
            if not hit:
                return self._send_json({"error": "稿件不存在"}, 404)
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True, "post_id": pid, "published_link": url})

        if path == "/api/posts/prepare_material":
            # 选题确认 → 自动解析来源并抓原文，存进该稿 body 作为生成素材
            body = self._read_json()
            posts = load_json(POSTS_PATH, [])
            post = next((p for p in posts if p.get("id") == body.get("post_id")), None)
            if not post:
                return self._send_json({"error": "稿件不存在"}, 404)
            if post.get("body") and len(post["body"]) > 200:
                return self._send_json({"ok": True, "cached": True, "len": len(post["body"]), "url": post.get("source_url", "")})
            url = _resolve_topic_source(post)
            if not url:
                return self._send_json({"error": "解析不到素材来源（选题缺 URL/仓库名锚点），请点「编辑原稿」手动粘贴素材"}, 422)
            ok, title, text = _fetch_original_text(url)
            if not ok:
                return self._send_json({"error": text, "url": url}, 422)
            post["body"] = text
            post["source_url"] = url
            post["source_title"] = title
            post["updated"] = time.strftime("%Y-%m-%d %H:%M")
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True, "cached": False, "len": len(text), "url": url, "title": title})

        if path == "/api/publish":
            # 发布：X 自动（twikit）/ Threads 预填链接 / 抖音创作者中心 / 小红书手动
            body = self._read_json()
            posts = load_json(POSTS_PATH, [])
            post = next((p for p in posts if p.get("id") == body.get("post_id")), None)
            if not post:
                return self._send_json({"error": "稿件不存在"}, 404)
            platform = body.get("platform", "")
            res = _publisher.publish(post, platform)
            if res.get("ok"):
                post["status"] = "已发布"
                post["updated"] = time.strftime("%Y-%m-%d %H:%M")
                save_json(POSTS_PATH, posts)
            return self._send_json(res)

        if path == "/api/followers":
            # 周度粉丝快照录入（4平台 × 粉丝/阅读/新增微信）
            body = self._read_json()
            date = body.get("date") or time.strftime("%Y-%m-%d")
            snaps = load_json(FOLLOWERS_PATH, [])
            for p in EXPERIMENT_PLATFORMS:
                if p not in body:
                    continue
                v = body[p] or {}
                snaps = [s for s in snaps if not (s.get("date") == date and s.get("platform") == p)]
                snaps.append({"date": date, "platform": p,
                              "followers": v.get("followers", 0), "reads": v.get("reads", 0),
                              "wechat": v.get("wechat", 0)})
            save_json(FOLLOWERS_PATH, snaps)
            return self._send_json({"ok": True, "snapshots": len(snaps)})

        if path == "/api/posts/fetch_original":
            # 按需抓取小红书原帖正文（跨号：xsec 取自补抓缓存）
            body = self._read_json()
            posts = load_json(POSTS_PATH, [])
            post = next((p for p in posts if p.get("id") == body.get("post_id")), None)
            if not post or not post.get("xhs_id"):
                return self._send_json({"error": "该稿件没有小红书原文可抓（选题占位请直接粘贴素材）"}, 400)
            xsec_map = load_json(os.path.join(DATA, "xsec_cache.json"), {})
            xt = xsec_map.get(post["xhs_id"], "")
            if not xt:
                return self._send_json({"error": "xsec 缓存缺失，等后台补抓完成或直接粘贴"}, 409)
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "get_feed_detail",
                                             "arguments": {"feed_id": post["xhs_id"], "xsec_token": xt}}})
            try:
                out = subprocess.run(["curl", "-s", "--max-time", "70", "-X", "POST", XHS_MCP,
                                      "-H", "Content-Type: application/json", "-d", payload],
                                     capture_output=True, text=True, timeout=80).stdout
                d = json.loads(out)
                inner = json.loads(d["result"]["content"][0]["text"])
                desc = (inner.get("data", {}).get("note", {}).get("desc") or "").strip()
            except Exception as e:
                return self._send_json({"error": f"MCP 调用失败: {str(e)[:80]}"}, 502)
            if not desc:
                return self._send_json({"error": "跨号抓取被限流，可直接粘贴原文"}, 502)
            post["body"] = desc
            post["updated"] = time.strftime("%Y-%m-%d %H:%M")
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True, "body": desc})

        if path == "/api/douyin/analyze":
            # 抖音爆款复刻：豆包+transcript-exporter 产出 → 选题库 → 会爆选题
            body = self._read_json()
            account = body.get("account", "持穗Rohini")
            corpus = (body.get("corpus") or "").strip()
            if len(corpus) < 50:
                return self._send_json({"error": "素材太短，请贴完整的豆包产出"}, 400)
            # 闸1：必须是视频数据（标题+互动数字+逐字稿特征），否则拒绝——宁可不产出也不编
            import re as _re
            nums = _re.findall(r"[赞播评转][^\d]{0,4}([\d,.]+\s*[万wW]?)", corpus) or _re.findall(r"([\d,.]+\s*[万wW]?)[^\n]{0,6}[赞播放评转]", corpus)
            has_scripts = ("逐字稿" in corpus) or ("文案" in corpus and len(corpus) > 300)
            if len(nums) < 3 or not has_scripts:
                return self._send_json({"error": "这段内容不像 transcript-exporter 的产出（需要至少 3 条带赞数/播放数的视频记录 + 逐字稿/文案）。请先用豆包+transcript-exporter 整理博主主页，把它的完整输出贴进来——没有真实数据我不会硬编选题"}, 400)
            cfg = get_config()
            identity = cfg.get("account_profiles", {}).get(account, {}).get("identity", "")
            prompt = f"""你是抖音爆款选题分析师。下面是用 transcript-exporter skill 从抖音博主主页整理的选题库原始数据（标题/文案/逐字稿片段/互动数据）。目标账号人设：{identity}（人设内核：一人AI编辑部主编，研一操盘手+一队AI员工；内容必须有强利他性——读者看完能带走东西）。

原始数据：
{corpus[:6000]}

任务：从这批真实爆款数据里提炼「按同样打法会爆」的选题，适配目标账号人设。输出 JSON：
{{
  "topics": [
    {{
      "title": "选题标题（口播视频用，10-22字，具体有锚点）",
      "score": 9,
      "why": "为什么这条会爆：引用原始数据里的模式（哪类标题/结构互动最好，带数字证据）",
      "reader_value": "读者看完带走什么（一句话，必须是可执行方法/清单/判断依据，不许空话）",
      "reference": "同风格参考要点：从原始逐字稿里提取的结构骨架（开头钩子怎么进/节奏/收尾），供脚本生成直接套用"
    }}
  ]
}}

要求：
1. 每个选题必须带 source_video（从原始数据里逐字复制的视频标题）和 source_likes（该条数据里的真实赞/播放数），并在 why 里引用原始数据的具体模式
2. 只准从原始数据出现过的视频/结构/钩子里推导——数据里没有的模式不许出现
3. 如果原始数据不足以支撑 3 个以上可信选题，就输出 {{"topics": [], "note": "原因"}}——空结果好过编造
4. reader_value 必须具体到读者能照做。只输出 JSON。"""
            text, err = call_llm(prompt, get_config())
            if err:
                return self._send_json({"error": err}, 500)
            data = parse_json_obj(text)
            if not data:
                return self._send_json({"error": "AI 返回格式异常，重试一次", "raw": (text or "")[:300]}, 502)
            import re as _re2
            def _norm(t):
                return _re2.sub(r"\s+", "", t or "")
            corpus_norm = _norm(corpus)
            topics, dropped = [], []
            for t in (data.get("topics") or []):
                src = _norm(t.get("source_video", ""))
                likes = str(t.get("source_likes", "")).replace(",", "")
                if src and src in corpus_norm and (not likes or likes in corpus.replace(",", "")):
                    topics.append(t)
                else:
                    dropped.append(t.get("title", "?"))
            if len(topics) < 2:
                return self._send_json({"error": f"数据不足以产出可信选题（核验后仅 {len(topics)} 条有真实来源）。请贴完整豆包产出：每条视频的标题+赞数+逐字稿", "dropped": dropped[:4]}, 422)
            load = load_json(DOUYIN_TOPICS_PATH, {"topics": []})
            load["topics"] = topics
            load["updated"] = time.strftime("%Y-%m-%d %H:%M")
            save_json(DOUYIN_TOPICS_PATH, load)
            return self._send_json({"ok": True, "topics": topics, "total": corpus.count("赞") + corpus.count("点赞")})

        if path == "/api/publish/settings":
            body = self._read_json()
            cfg = get_config()
            pub = cfg.setdefault("publish", {}).setdefault("x", {})
            if body.get("username"):
                pub["username"] = body["username"].strip()
            if body.get("email"):
                pub["email"] = body["email"].strip()
            if body.get("password"):
                pub["password"] = body["password"]
            # 密码填了新值时作废旧 cookies，下次发布重新登录
            if body.get("password") and os.path.exists(_publisher.X_COOKIES):
                try:
                    os.remove(_publisher.X_COOKIES)
                except Exception:
                    pass
            save_json(CONFIG_PATH, cfg)
            return self._send_json({"ok": True, "x_auto": bool(pub.get("username") and pub.get("password"))})

        if path == "/api/trends/refresh":
            body = self._read_json()
            prompt = build_prompt("trends", body)
            text, err = call_llm(prompt, get_config())
            if err:
                return self._send_json({"error": err}, 500)
            items = parse_json_array(text)
            if items is None:
                return self._send_json({"error": "AI 返回格式异常，请重试", "raw": text[:500]}, 500)
            account = body.get("account", "") or "Jocelyn"
            store = load_json(TRENDS_PATH, {})
            if "items" in store:  # 旧格式迁移
                store = {"Jocelyn": store}
            store[account] = {
                "updated": time.strftime("%Y-%m-%d %H:%M"),
                "items": [dict(t, id=uuid.uuid4().hex[:8]) for t in items if isinstance(t, dict)],
            }
            save_json(TRENDS_PATH, store)
            return self._send_json(store[account])

        if path == "/api/trends/delete":
            body = self._read_json()
            account = body.get("account", "") or "Jocelyn"
            store = load_json(TRENDS_PATH, {})
            if "items" in store:
                store = {"Jocelyn": store}
            data = store.get(account, {"updated": "", "items": []})
            data["items"] = [t for t in data.get("items", []) if t.get("id") != body.get("id")]
            store[account] = data
            save_json(TRENDS_PATH, store)
            return self._send_json({"ok": True})

        if path == "/api/benchmark":
            body = self._read_json()
            topic = (body.get("topic") or "").strip()
            account = body.get("account", "") or "Jocelyn"
            if not topic:
                return self._send_json({"error": "先填选题方向"}, 400)
            # 从选题里提取搜索词：取前 12 字或冒号前部分
            keyword = topic.split("：")[0].split(":")[0][:12]
            notes, err = xhs_search(keyword)
            if err:
                # 降级：搜索不可用时不阻塞，提示但返回成功（前端显示降级提示）
                return self._send_json({
                    "keyword": keyword,
                    "notes": [],
                    "analysis": None,
                    "degraded": True,
                    "error": err,
                })
            if not notes:
                return self._send_json({"keyword": keyword, "notes": [], "analysis": None,
                                        "error": "没搜到相关笔记，换个关键词试试"})
            text, llm_err = call_llm(benchmark_prompt(account, keyword, notes), get_config())
            analysis = None
            if not llm_err:
                import re as _re
                m = _re.search(r"\{[\s\S]*\}", text)
                if m:
                    try:
                        analysis = json.loads(m.group(0))
                    except Exception:
                        analysis = None
            return self._send_json({
                "keyword": keyword,
                "notes": notes,
                "analysis": analysis,
                "raw": text if analysis is None else None,
            })

        if path == "/api/posts/save":
            body = self._read_json()
            posts = load_json(POSTS_PATH, [])
            pid = body.get("id")
            if pid:
                for p in posts:
                    if p.get("id") == pid:
                        p.update(body)
                        p["updated"] = time.strftime("%Y-%m-%d %H:%M")
                        break
                else:
                    return self._send_json({"error": "稿件不存在"}, 404)
            else:
                body["id"] = uuid.uuid4().hex[:8]
                body["created"] = time.strftime("%Y-%m-%d %H:%M")
                body["updated"] = body["created"]
                posts.append(body)
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True, "id": body["id"]})

        if path == "/api/posts/delete":
            body = self._read_json()
            posts = load_json(POSTS_PATH, [])
            posts = [p for p in posts if p.get("id") != body.get("id")]
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True})

        if path == "/api/analytics/save":
            body = self._read_json()
            rows = load_json(ANALYTICS_PATH, [])
            rid = body.get("post_id")
            for r in rows:
                if r.get("post_id") == rid:
                    r.update(body)
                    break
            else:
                rows.append(body)
            save_json(ANALYTICS_PATH, rows)
            return self._send_json({"ok": True})

        if path == "/api/config":
            body = self._read_json()
            cfg = get_config()
            if "llm" in body:
                cfg.setdefault("llm", {}).update(body["llm"])
            save_json(CONFIG_PATH, cfg)
            return self._send_json({"ok": True})

        return self._send_json({"error": "not found"}, 404)

    # ---------- 聚合统计 ----------
    def _summary(self, account=None):
        posts = load_json(POSTS_PATH, [])
        analytics = load_json(ANALYTICS_PATH, [])
        if account:
            posts = [p for p in posts if p.get("account") == account]
            ids = {p["id"] for p in posts}
            analytics = [a for a in analytics if a.get("post_id") in ids]

        def n(x):
            try:
                return int(str(x).replace(",", ""))
            except Exception:
                return 0

        lines = {}
        for a in analytics:
            post = next((p for p in posts if p.get("id") == a.get("post_id")), None)
            line = (post or {}).get("content_line", "未分类")
            b = lines.setdefault(line, {"views": 0, "likes": 0, "collects": 0, "comments": 0, "followers": 0, "count": 0})
            b["views"] += n(a.get("views"))
            b["likes"] += n(a.get("likes"))
            b["collects"] += n(a.get("collects"))
            b["comments"] += n(a.get("comments"))
            b["followers"] += n(a.get("followers"))
            b["count"] += 1

        total_views = sum(n(a.get("views")) for a in analytics)
        total_likes = sum(n(a.get("likes")) for a in analytics)
        total_collects = sum(n(a.get("collects")) for a in analytics)
        total_followers = sum(n(a.get("followers")) for a in analytics)
        total_profile = sum(n(a.get("profile_visits")) for a in analytics)
        total_impressions = sum(n(a.get("impressions")) for a in analytics)
        total_shares = sum(n(a.get("shares")) for a in analytics)

        best = None
        for a in analytics:
            if not best or n(a.get("views")) > n(best.get("views")):
                post = next((p for p in posts if p.get("id") == a.get("post_id")), {})
                best = dict(a)
                best["title"] = post.get("title", "")

        trend = sorted(
            [{"date": (next((p for p in posts if p.get("id") == a.get("post_id")), {}) or {}).get("created", "")[:10],
              "views": n(a.get("views")), "followers": n(a.get("followers"))} for a in analytics],
            key=lambda x: x["date"],
        )

        # 最热（按赞）：小红书公开数据实时同步，观看量缺失时也能反映真实爆款
        hottest = None
        for a in analytics:
            if not hottest or n(a.get("likes")) > n(hottest.get("likes")):
                post = next((p for p in posts if p.get("id") == a.get("post_id")), {})
                hottest = dict(a)
                hottest["title"] = post.get("title", "")

        return {
            "totals": {
                "posts": len([p for p in posts if p.get("status") == "已发布"]),
                "views": total_views,
                "impressions": total_impressions,
                "likes": total_likes,
                "collects": total_collects,
                "shares": total_shares,
                "followers": total_followers,
                "profile_visits": total_profile,
            },
            "by_line": lines,
            "best": best,
            "hottest": hottest,
            "trend": trend,
            "funnel": {
                "views": total_views,
                "engagement": total_likes + total_collects,
                "profile_visits": total_profile,
                "followers": total_followers,
            },
        }


def main():
    port = 8501
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    # 多线程：单个卡住的请求（LLM/MCP 超时）不再堵死整个服务
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(f"大号自媒体工作台已启动: http://127.0.0.1:{port}")
    print("数据分析页: http://127.0.0.1:%d/analytics.html" % port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
