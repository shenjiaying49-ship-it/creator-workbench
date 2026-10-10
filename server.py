#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大号小红书自媒体工作台 - 本地服务
用法: python3 server.py [--port 8501]
"""
import json
import os
import sys
import time
import uuid
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
DATA = os.path.join(BASE, "data")
UPLOADS = os.path.join(DATA, "uploads")
CONFIG_PATH = os.path.join(BASE, "config.json")

os.makedirs(UPLOADS, exist_ok=True)


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
EXPERIMENT_PLATFORMS = ["公众号", "知乎", "即刻", "小红书"]

import publisher as _publisher
MATERIALS_PATH = os.path.join(DATA, "materials.json")
ANALYTICS_PATH = os.path.join(DATA, "analytics.json")
TRENDS_PATH = os.path.join(DATA, "trends.json")
ACCOUNT_PATH = os.path.join(DATA, "account_daily.json")
XHS_MCP = "http://localhost:18060/mcp"
XHS_LOCK = threading.Lock()  # xiaohongshu-mcp 单实例，并发搜索会互相打架


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
    # 旧轨（保留兼容）
    "X": {"hook": "首条", "thread": ["第2条", "..."], "hashtags": ["#AI"]},
    "Threads": {"posts": ["帖子1", "帖子2"]},
    "抖音": {"script": "口播稿", "film_tips": "拍摄提示一句话", "caption": "描述区文案+互动问题", "hashtags": ["#AI"]},
}
DEFAULT_PLATFORMS = ["公众号", "知乎", "即刻", "小红书"]


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
{style_note}

硬性要求：
1. 各平台内容必须是同一选题的「平台母语重写」，不是互相复制删减
2. 每个平台的钩子/结构/字数/标签习惯完全按上面规则执行，越界即错
3. 拆解类内容必须有数据锚点；没有公开数据的判断要标注「推测」
4. 每篇至少一个可截图的框架/表格（作品集素材）
5. 不要输出任何 JSON 之外的解释文字

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
                with urllib.request.urlopen(req, timeout=120) as resp:
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
            # 自动排期：完全由稿件库驱动。优先级：小红书旧稿待同步（按赞数降序）> 已生成组待发布 > 新选题素材
            import datetime as _dt
            pb = load_json(PLAYBOOKS_PATH, {})
            all_posts = load_json(POSTS_PATH, [])
            account = qs.get("account", ["Jocelyn"])[0] or "Jocelyn"
            posts = [p for p in all_posts if p.get("account") == account]

            def similar(a, b):
                """中文标题模糊匹配：短串的 8 字滑窗任一出现在长串里即算同题"""
                if not a or not b:
                    return False
                a, b = a.strip(), b.strip()
                if a in b or b in a:
                    return True
                short, long = (a, b) if len(a) <= len(b) else (b, a)
                if len(short) < 8:
                    return short and short in long
                return any(short[i:i + 8] in long for i in range(len(short) - 7))

            synced_source_ids = {p.get("source_post_id") for p in posts if p.get("source_post_id")}
            topics = []

            def add_topic(title, line, origin, platforms_needed, sort_key=0):
                title = (title or "").strip()
                if not title:
                    return
                if any(similar(title, t["title"]) for t in topics):
                    return
                topics.append({
                    "title": title, "content_line": line, "origin": origin,
                    "platforms": platforms_needed, "_sort": sort_key,
                })

            # 1) 小红书已发布、其他平台还没稿的旧稿 —— 按赞数降序（最爆的先同步）
            xhs_pending = [p for p in posts
                           if p.get("source") == "xhs_sync" and not p.get("group_id")
                           and p.get("status") == "已发布" and p.get("id") not in synced_source_ids]
            xhs_pending.sort(key=lambda p: -int((p.get("xhs_metrics", {}) or {}).get("likes") or 0))
            for p in xhs_pending:
                add_topic(p["title"], p.get("content_line", ""), "小红书旧稿待同步", ["X", "Threads", "抖音"],
                          sort_key=int((p.get("xhs_metrics", {}) or {}).get("likes") or 0))

            # 2) 已生成组里还没发完的平台
            groups = {}
            for p in posts:
                if p.get("group_id"):
                    groups.setdefault(p["group_id"], []).append(p)
            for gid, ps in groups.items():
                ps = sorted(ps, key=lambda q: q.get("created", ""))
                title = ps[0].get("topic") or ps[0].get("title", "")
                needed = [plat for plat in ("小红书", "X", "Threads", "抖音")
                          if not any(q.get("platform") == plat and q.get("status") == "已发布" for q in ps)]
                if needed:
                    add_topic(title, ps[0].get("content_line", ""), "已生成待发布", needed)

            # 3) 素材箱/草稿里的新选题
            for p in posts:
                if p.get("status") in ("素材", "草稿", "待确认") and not p.get("group_id"):
                    add_topic(p.get("topic") or p.get("title", ""), p.get("content_line", ""), "新选题",
                              ["小红书", "X", "Threads", "抖音"])

            def post_state(title, plat):
                best = ""
                for p in posts:
                    if similar(p.get("topic", ""), title) or similar(p.get("title", ""), title):
                        if p.get("platform") == plat or (p.get("platform") is None and plat == "小红书"):
                            s = p.get("status", "")
                            if s == "已发布":
                                return s
                            best = best or s
                return best

            today = _dt.date.today()
            monday = today + _dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
            wd_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            # 三套发布位轮换，同周内不同选题错峰，避免同天同平台撞车
            slots_variants = [
                [(1, "小红书", "19:30"), (2, "抖音", "12:30"), (3, "X", "10:30"), (3, "Threads", "21:30")],
                [(4, "小红书", "19:30"), (5, "抖音", "18:30"), (6, "X", "10:30"), (6, "Threads", "21:30")],
                [(1, "Threads", "21:30"), (3, "抖音", "18:00"), (4, "小红书", "12:00"), (5, "X", "20:00")],
            ]

            weeks = []
            n_weeks = min(8, max(4, -(-len(topics) // 3)))  # 每周 3 个选题，至少 4 周至多 8 周
            for w in range(n_weeks):
                week_topics = topics[w * 3:(w + 1) * 3]
                day_map = {}
                for i, t in enumerate(week_topics):
                    for wd, plat, tm in slots_variants[i % 3]:
                        if plat not in t["platforms"]:
                            continue
                        d = monday + _dt.timedelta(days=w * 7 + wd)
                        day_map.setdefault(d.isoformat(), []).append({
                            "platform": plat, "time": tm, "topic": t["title"],
                            "content_line": t["content_line"], "source": t["origin"],
                            "state": post_state(t["title"], plat),
                        })
                mon = monday + _dt.timedelta(days=w * 7)
                week_days = []
                for wd in range(7):
                    d = (mon + _dt.timedelta(days=wd)).isoformat()
                    week_days.append({
                        "date": d,
                        "weekday": wd_names[wd],
                        "items": day_map.get(d, []),
                        "routine": "生产日：稿件库一键生成+人工改定" if wd == 0 else ("复盘 15 分钟 + 下周选题" if wd == 6 else ""),
                    })
                weeks.append({"week": w + 1, "monday": mon.isoformat(), "days": week_days})

            return self._send_json({
                "start": monday.isoformat(),
                "weeks": weeks,
                "queue_total": len(topics),
                "pending_sync": len(xhs_pending),
                "daily_routine": pb.get("schedule_template", {}).get("日常", ""),
                "weekly_routine": {k: v for k, v in pb.get("schedule_template", {}).items() if k not in ("日常",)},
            })

        return super().do_GET()

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path

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
            x_body = "\n\n".join([p for p in [x.get("hook", "")] + list(x.get("thread") or []) if p])
            all_specs = [
                ("公众号", gzh.get("title", topic), gzh.get("body", ""), gzh.get("tags", []),
                 {"abstract": gzh.get("abstract", "")}),
                ("知乎", zh.get("title", topic), zh.get("body", ""), zh.get("tags", []), {}),
                ("即刻", topic, "\n— — —\n".join(jk.get("posts") or []), [], {"note": "多条独立动态，分开发"}),
                ("小红书", xhs.get("title", topic), xhs.get("body", ""), xhs.get("tags", []),
                 {"cards": xhs.get("cards", []), "first_comment": xhs.get("first_comment", "")}),
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
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True, "group_id": group_id, "result": data, "saved_ids": saved_ids})

        if path == "/api/studio/delete-group":
            body = self._read_json()
            posts = load_json(POSTS_PATH, [])
            posts = [p for p in posts if p.get("group_id") != body.get("group_id")]
            save_json(POSTS_PATH, posts)
            return self._send_json({"ok": True})

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
