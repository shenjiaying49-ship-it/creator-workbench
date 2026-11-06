#!/usr/bin/env python3
"""小红书卡片渲染器：结构化卡片 JSON → 品牌化 HTML → PNG（Chrome headless）
设计语言对齐 ai-daily-news：暖纸底 · 紫主色 · 大字排版 · 持穗署名水印
用法: python3 render_cards.py <cards.json> <outdir>
cards.json: {"title": "...", "sub": "...", "cards": [{"h": "卡头", "b": ["要点", ...], "num": "01"}], "end": "结尾卡文案", "pen": "持穗/Rohini"}
"""
import json
import os
import subprocess
import sys
import tempfile

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W, H = 1242, 1656  # 3:4 小红书标准

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { width:1242px; font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; background:#faf6f0; color:#2a2233; }
.page { width:1242px; height:1656px; padding:110px 96px; display:flex; flex-direction:column; position:relative; background:#faf6f0; }
.page.cover { background:linear-gradient(160deg,#faf6f0 55%,#f0e6f6 100%); }
.accent { color:#660874; }
.kicker { font-size:30px; letter-spacing:.35em; color:#843990; font-weight:600; margin-bottom:34px; }
.cover { justify-content:center; }
.cover h1 { font-size:88px; line-height:1.35; font-weight:800; letter-spacing:.01em; }
.cover .sub { margin-top:64px; font-size:40px; line-height:1.75; color:#5a4f66; }
.cover .tagrow { margin-top:56px; display:flex; gap:20px; flex-wrap:wrap; }
.cover .tagrow span { font-size:30px; padding:14px 30px; border:2px solid #843990; color:#660874; border-radius:999px; font-weight:600; }
.cover .pen { position:absolute; bottom:96px; left:96px; font-size:30px; color:#843990; font-weight:600; }
.cover .issue { position:absolute; bottom:96px; right:96px; font-size:28px; color:#b3a6bd; }
.card .num { font-size:150px; font-weight:800; color:#efe4f4; line-height:1; position:absolute; top:70px; right:80px; }
.card h2 { font-size:64px; font-weight:800; line-height:1.35; margin-bottom:46px; padding-top:26px; }
.card h2::before { content:""; display:block; width:88px; height:12px; background:#660874; border-radius:6px; margin-bottom:30px; }
.card li { font-size:40px; line-height:1.75; color:#3d3348; margin-bottom:30px; padding-left:44px; position:relative; list-style:none; }
.card li::before { content:""; position:absolute; left:0; top:26px; width:16px; height:16px; border-radius:50%; background:#843990; }
.card li b { color:#660874; }
.card .foot { margin-top:auto; display:flex; justify-content:space-between; align-items:center; font-size:28px; color:#b3a6bd; border-top:1px solid #e8dfe9; padding-top:30px; }
.end { justify-content:center; align-items:flex-start; }
.end h2 { font-size:76px; font-weight:800; line-height:1.4; margin-bottom:50px; }
.end p { font-size:42px; line-height:1.8; color:#5a4f66; }
.end .pen { margin-top:70px; font-size:34px; color:#843990; font-weight:700; }
"""


def build_html(data):
    cards_html = []
    # 封面
    tags = "".join(f"<span>{t}</span>" for t in data.get("tags", []))
    cards_html.append(f'<div class="page cover"><div class="kicker">持穗 · 增长与商业化</div><h1>{data["title"]}</h1><div class="sub">{data.get("sub", "")}</div>{f"<div class=tagrow>{tags}</div>" if tags else ""}<div class="pen">{data.get("pen", "持穗/Rohini")}</div><div class="issue">{data.get("issue", "")}</div></div>')
    # 内容卡
    for i, c in enumerate(data.get("cards", [])):
        items = "".join(f"<li>{p}</li>" for p in c.get("b", []))
        cards_html.append(
            f'<div class="page card"><div class="num">{c.get("num", f"{i+1:02d}")}</div>'
            f'<h2>{c["h"]}</h2><ul>{items}</ul>'
            f'<div class="foot"><span>{data.get("pen", "持穗/Rohini")}</span><span>{i+2}/{len(data.get("cards", [])) + 2}</span></div></div>')
    # 结尾卡
    cards_html.append(
        f'<div class="page end"><h2>{data.get("end_h", "看完这组卡片")}</h2><p>{data.get("end", "")}</p>'
        f'<div class="pen">—— {data.get("pen", "持穗/Rohini")}</div></div>')
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>" + CSS + "</style></head><body>"
            + "".join(cards_html) + "</body></html>")


def main():
    data = json.load(open(sys.argv[1]))
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    html = build_html(data)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        html_path = f.name
    # 每页一张图：Chrome headless 逐页截图（full-page 截一次会拼成长图，按页渲染用 --screenshot 单页文件逐个来）
    # 简单可靠做法：每页一个 HTML 文件单独截
    pages = [p for p in range(len(data.get("cards", [])) + 2)]
    outputs = []
    for idx in pages:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            doc = ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>" + CSS +
                   f"body{{width:{W}px}} .page:nth-child({idx+1}){{display:flex}} .page{{display:none}}</style></head><body>"
                   + html.split("<body>")[1])
            f.write(doc)
            phtml = f.name
        out = os.path.join(outdir, f"card-{idx+1:02d}.png")
        subprocess.run([CHROME, "--headless", "--disable-gpu", f"--screenshot={out}",
                        f"--window-size={W},{H}", "--default-background-color=FFFFFFFF",
                        "--hide-scrollbars", "file://" + phtml],
                       capture_output=True, timeout=60)
        if os.path.exists(out) and os.path.getsize(out) > 10000:
            outputs.append(out)
        os.unlink(phtml)
    os.unlink(html_path)
    print(json.dumps({"ok": len(outputs) > 0, "rendered": len(outputs), "files": outputs}))


if __name__ == "__main__":
    main()
