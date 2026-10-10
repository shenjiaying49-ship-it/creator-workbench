/* 大号自媒体工作台 - 主工作台逻辑 */
"use strict";

let cfg = { accounts: ["Jocelyn"] };
let materials = [];
let posts = [];
let currentEditingId = null;

// ---------- 工具 ----------
const $ = (id) => document.getElementById(id);

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2200);
}

async function api(path, body) {
  const opt = body !== undefined
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
  return r.json();
}

function countChars(s) {
  return (s || "").replace(/\s/g, "").length;
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

// ---------- 初始化 ----------
async function init() {
  cfg = await api("/api/config");
  const sel = $("accountSel");
  sel.innerHTML = (cfg.accounts || ["Jocelyn"]).map(a => `<option>${esc(a)}</option>`).join("");
  sel.value = localStorage.getItem("workbench_account") || cfg.accounts[0];
  sel.onchange = () => { localStorage.setItem("workbench_account", sel.value); reload(); };

  document.querySelectorAll(".sidebar .nav-item").forEach(el => {
    el.onclick = () => switchView(el.dataset.view);
  });

  $("finalDraft").addEventListener("input", updateWordCount);
  $("pmBody").addEventListener("input", () => {
    $("pmWordCount").textContent = countChars($("pmBody").value) + " 字";
  });

  await reload();

  // AI 接口状态提示
  const statusEl = $("aiStatus");
  if (statusEl) {
    if (cfg.llm && cfg.llm.api_key_set) {
      statusEl.textContent = "AI 已连接（自定义接口）";
      statusEl.style.color = "var(--green)";
    } else if (cfg.zcode_connected) {
      statusEl.textContent = "AI 已连接（ZCode 接口）";
      statusEl.style.color = "var(--green)";
    } else {
      statusEl.innerHTML = 'AI 未连接，<a href="#" onclick="alert(\'请在 config.json 填入 llm.api_key，或设置 ZCODE_API_KEY 环境变量后重启服务\');return false;">查看配置方法</a>';
      statusEl.style.color = "var(--dim)";
    }
  }
}

async function reload() {
  materials = await api("/api/materials");
  posts = await api("/api/posts?account=" + encodeURIComponent($("accountSel").value));
  renderMaterials();
  renderPosts();
  renderSchedule();
  updateMaterialHint();
  // 切账号时若趋势页可见，同步刷新趋势与人设关键词
  if (!$("view-trends").classList.contains("hidden")) loadTrends();
}

function switchView(v) {
  document.querySelectorAll(".sidebar .nav-item").forEach(el => el.classList.toggle("active", el.dataset.view === v));
  ["create", "trends", "posts", "schedule"].forEach(name => {
    $("view-" + name).classList.toggle("hidden", name !== v);
  });
  if (v === "trends") loadTrends();
}

// ---------- 素材箱 ----------
async function addMaterial() {
  const title = $("mTitle").value.trim();
  const content = $("mContent").value.trim();
  const type = $("mType").value;
  const fileInput = $("mFile");

  let fileUrl = null;
  if (fileInput.files.length) {
    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const data = await r.json();
    if (data.error) return toast(data.error);
    fileUrl = data.file;
    if (!title) $("mTitle").value = data.original_name;
  }

  if (!content && !fileUrl) return toast("请输入文本或选择文件");

  await api("/api/materials", {
    title: $("mTitle").value.trim(),
    content, type, tags: [type], file: fileUrl,
  });
  $("mTitle").value = ""; $("mContent").value = ""; fileInput.value = "";
  await reload();
  toast("素材已存入");
}

function renderMaterials() {
  const box = $("materialList");
  if (!materials.length) {
    box.innerHTML = '<div class="muted" style="padding:12px 0;">还没有素材，先添加一条。</div>';
    return;
  }
  const used = getUsedMaterialIds();
  box.innerHTML = materials.slice().reverse().map(m => `
    <div class="material-item">
      <input type="checkbox" class="m-check" data-id="${m.id}" ${used.includes(m.id) ? "checked" : ""} onchange="toggleUseMaterial()">
      <div class="m-body">
        <div class="m-title">${esc(m.title)}</div>
        <div class="m-preview">${esc((m.content || "").slice(0, 200))}${m.file ? ` 📎 <a href="${esc(m.file)}" target="_blank">查看文件</a>` : ""}</div>
        <div class="m-meta">
          <span class="tag ${esc(m.type)}">${esc(m.type)}</span>
          ${esc(m.created)}
          <button class="small danger" style="float:right;" onclick="delMaterial('${m.id}')">删除</button>
        </div>
      </div>
    </div>`).join("");
}

async function delMaterial(id) {
  if (!confirm("删除这条素材？")) return;
  await api("/api/materials/delete", { id });
  await reload();
}

// 已勾选素材：会话级（不跨刷新持久化，避免旧对标素材污染新流程）
let usedMaterialIds = [];

function getUsedMaterialIds() {
  return usedMaterialIds;
}

function toggleUseMaterial() {
  usedMaterialIds = [...document.querySelectorAll(".m-check:checked")].map(el => el.dataset.id);
  updateMaterialHint();
}

function getUsedMaterialsText() {
  const ids = usedMaterialIds;
  return materials.filter(m => ids.includes(m.id))
    .map(m => `【${m.title}】\n${(m.content || "").slice(0, 3000)}`)
    .join("\n\n---\n\n");
}

function updateMaterialHint() {
  const n = getUsedMaterialIds().length;
  $("cMaterialHint").textContent = n ? `已勾选 ${n} 条素材，生成时以素材为主` : "未勾选素材：AI 会自动抓对标爆帖内化为素材再创作";
  const btn = $("mainGenBtn");
  if (btn) btn.textContent = n ? "✍️ 以素材直接生成全文" : "✨ 生成角度建议";
}

// ---------- 创作流程 ----------
function setStep(n) {
  document.querySelectorAll(".step-pill").forEach(el => {
    const s = +el.dataset.step;
    el.classList.toggle("active", s === n);
    el.classList.toggle("done", s < n);
  });
  [1, 2].forEach(i => $("step" + i).classList.toggle("hidden", i !== n && i < n));
  // 两步式：进入精修时 step1 收起，回到第 1 步时两者都可见（step2 隐藏）
  if (n === 1) $("step2").classList.add("hidden");
}

// state: "loading" | "done" | "error"
function flowStatus(text, state = "loading") {
  const box = $("flowStatus");
  box.classList.remove("hidden", "flow-done", "flow-err");
  $("flowText").textContent = text;
  const spinner = $("flowSpinner");
  const check = $("flowCheck");
  if (state === "done") {
    box.classList.add("flow-done");
    spinner.style.display = "none";
    if (check) check.style.display = "";
    setTimeout(() => box.classList.add("hidden"), 5000); // 完成后 5 秒淡出
  } else if (state === "error") {
    box.classList.add("flow-err");
    spinner.style.display = "none";
    if (check) check.style.display = "none";
  } else {
    spinner.style.display = "";
    if (check) check.style.display = "none";
  }
}

async function generate(kind, payload) {
  const body = {
    kind,
    tone: $("cTone").value,
    is_ad: $("cIsAd").checked,
    format: $("cFormat").value,
    account: $("accountSel").value,
    ...payload,
  };
  if (body.kind_override) { body.kind = body.kind_override; delete body.kind_override; }
  const r = await api("/api/generate", body);
  if (r.error) {
    toast(r.error);
    return null;
  }
  return r.result;
}

// 形式切换：口播稿时显示时长选择
document.addEventListener("change", (e) => {
  if (e.target && e.target.id === "cFormat") {
    const wrap = $("cDurationWrap");
    if (wrap) wrap.style.display = e.target.value === "口播稿" ? "" : "none";
    updateDraftFmtTag();
  }
});

function parseJSONLoose(text) {
  if (!text) return null;
  try { return JSON.parse(text); } catch (e) {}
  const m = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (m) { try { return JSON.parse(m[1]); } catch (e) {} }
  const arr = text.match(/\[[\s\S]*\]/);
  if (arr) { try { return JSON.parse(arr[0]); } catch (e) {} }
  return null;
}

// ---------- 对标爆贴：内化能力（无 UI，静默运行） ----------
// 每次点生成时：自动搜站内对标爆帖 → LLM 按账号人设提炼规律 → 存为「对标」素材，自动勾选带入本次生成
let _benchmarkInFlight = null;

function autoBenchmark(topic) {
  // 已勾选手动素材时，以素材为主，不自动抓对标
  if (!topic || getUsedMaterialIds().length > 0) return;
  if (_benchmarkInFlight) return _benchmarkInFlight; // 同一选题去重
  _benchmarkInFlight = (async () => {
    try {
      const account = $("accountSel").value;
      const r = await api("/api/benchmark", { topic, account });
      if (r.error || !r.notes || !r.notes.length) return null;
      const a = r.analysis || {};
      const lines = [];
      lines.push(`【对标爆帖 · 站内搜「${r.keyword}」】`);
      lines.push("Top 笔记：");
      (r.notes || []).slice(0, 6).forEach(n => lines.push(`- 「${n.title}」赞:${n.likes || "-"}`));
      if (a.patterns && a.patterns.length) {
        lines.push("爆款规律：");
        a.patterns.forEach((p, i) => lines.push(`${i + 1}. ${p}`));
      }
      if (a.differentiation) lines.push(`差异化切入：${a.differentiation}`);
      if (a.angle) lines.push(`推荐角度：${a.angle}`);
      // 静默写入素材箱并勾选，后续生成正文时自动带上
      const saved = await api("/api/materials", {
        title: `对标爆帖 · ${r.keyword}（自动抓取）`,
        content: lines.join("\n"),
        type: "对标",
        tags: ["对标", "自动"],
      });
      if (!usedMaterialIds.includes(saved.id)) usedMaterialIds.push(saved.id);
      materials.push(saved);
      renderMaterials();
      updateMaterialHint();
      return saved;
    } catch (e) {
      return null; // 静默失败，不阻塞创作
    } finally {
      setTimeout(() => { _benchmarkInFlight = null; }, 60 * 1000); // 同选题 1 分钟内不重复抓
    }
  })();
  return _benchmarkInFlight;
}

// 主生成按钮：有勾选素材 → 素材为主直接出全文；无素材 → 出角度（点角度后自动出全文）
async function mainGenerate() {
  if (getUsedMaterialIds().length > 0) {
    return autoFullDraft();
  }
  return genTopic();
}

// 全文生成：起标题 → 写正文 → 落到精修区。每一步都有状态提示。
async function autoFullDraft() {
  const materialsText = getUsedMaterialsText();
  const topic = $("cTopic").value.trim();
  const fmt = $("cFormat").value;
  const isVoice = fmt === "口播稿";
  const mainBtn = $("mainGenBtn");
  mainBtn.disabled = true;

  try {
    // 1) 起标题（不展示候选，直接取第一个）
    flowStatus("正在按你的人设起标题…（约 10 秒）");
    const titleResult = await generate("title", {
      topic: topic || (materialsText.slice(0, 40) + "…"),
      materials: materialsText,
    });
    const titles = parseJSONLoose(titleResult);
    $("cTitle").value = (titles && titles[0] && titles[0].title) || topic || "未命名";
    flowStatus(`标题已定：「${$("cTitle").value}」（精修区可改）`, "done");

    // 2) 写正文
    updateDraftFmtTag();
    const est = isVoice ? "约 40-60 秒" : "约 30-60 秒";
    flowStatus(`正在写${isVoice ? "口播稿" : "正文"}…（${est}，以${materialsText ? "你勾选的素材" : "自动抓取的对标"}为主）`);
    const result = await generate("draft", {
      title: $("cTitle").value,
      topic,
      materials: materialsText,
      kind_override: isVoice ? "voicedraft" : undefined,
      duration: +($("cDuration")?.value || 60),
    });
    if (!result) { flowStatus("生成失败，请重试", "error"); return; }

    $("finalDraft").value = result;
    updateWordCount();
    setStep(2);
    flowStatus(`✓ 完成！标题和全文都在精修区，改完记得存稿`, "done");
  } finally {
    mainBtn.disabled = false;
  }
  $("step2").scrollIntoView({ behavior: "smooth", block: "start" });
}

// 无素材路径：AI 出角度建议，点任意角度直接进入全文生成
async function genTopic() {
  const topic = $("cTopic").value.trim();
  if (!topic) return toast("先填选题方向");
  const mainBtn = $("mainGenBtn");
  mainBtn.disabled = true;
  flowStatus("正在生成选题角度…（同时后台自动抓站内对标爆帖内化为素材）");
  try {
    autoBenchmark(topic); // 静默：抓对标存素材箱
    const result = await generate("topic", { topic, materials: getUsedMaterialsText() });
    if (!result) { flowStatus("生成失败，请重试", "error"); return; }
    const items = parseJSONLoose(result);
    flowStatus("✓ 角度已出：点任意角度，自动写全文", "done");
    if (!items) {
      $("topicResult").innerHTML = `<div class="gen-result">${esc(result)}</div>`;
      return;
    }
    $("topicResult").innerHTML = '<div class="muted" style="margin:8px 0 6px;font-size:12px;">点任意角度 → 自动起标题并写全文：</div>' + items.map((it, i) => `
      <div class="title-candidate" data-insight="${esc(it.insight || "")}" onclick="pickAndWrite(${i})">
        <div class="t">角度 ${i + 1}：${esc(it.insight || "")}</div>
        <div class="r">切入场景：${esc(it.scene || "")}</div>
        <div class="r"><span class="tag line">${esc(it.content_line || "")}</span> ${esc(it.reason || "")}</div>
      </div>`).join("");
    window._topicAngles = items;
  } finally {
    mainBtn.disabled = false;
  }
}

// 点角度 → 用该角度作为选题直接出全文
function pickAndWrite(i) {
  const it = (window._topicAngles || [])[i];
  if (!it) return;
  document.querySelectorAll("#topicResult .title-candidate").forEach((e, j) => e.classList.toggle("selected", j === i));
  // 把角度拼进选题，正文生成时带着方向
  $("cTopic").value = ($("cTopic").value.split("：")[0]) + "：" + (it.insight || "");
  if (it.content_line) $("cLine").value = it.content_line;
  // 直接进入全文生成（genTopic 已静默抓过对标，会作为素材带入）
  autoFullDraft();
}

// 精修区格式标签随所选内容形式更新
function updateDraftFmtTag() {
  const fmt = $("cFormat").value;
  const tag = $("draftFmtTag");
  if (tag) tag.textContent = fmt === "口播稿" ? "口播稿" : (fmt === "视频" ? "视频脚本" : "图文");
}

// 内容形式分段选择：同步隐藏的 cFormat + 时长显隐 + 精修区标签
function setFormat(fmt) {
  $("cFormat").value = fmt;
  document.querySelectorAll(".fmt-btn").forEach(b => b.classList.toggle("active", b.dataset.fmt === fmt));
  const wrap = $("cDurationWrap");
  if (wrap) wrap.style.display = fmt === "口播稿" ? "" : "none";
  updateDraftFmtTag();
}

async function polishDraft() {
  const draft = $("finalDraft").value.trim();
  if (!draft) return toast("精修区还没有内容");
  const instruction = $("polishInstruction").value.trim();
  const btn = document.querySelector('button[onclick="polishDraft()"]');
  const orig = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "打磨中…（约10秒）"; }
  flowStatus("AI 正在打磨正文…（约 10 秒）");
  try {
    const result = await generate("polish", { draft, instruction });
    if (!result) { flowStatus("打磨失败，请重试", "error"); return; }
    $("finalDraft").value = result;
    updateWordCount();
    flowStatus("✓ 打磨完成，正文已更新", "done");
    toast("已打磨");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = orig; }
  }
}

function updateWordCount() {
  const n = countChars($("finalDraft").value);
  const el = $("wordCount");
  el.textContent = n + " 字" + (n > 1000 ? "（超出 1000 字上限）" : "");
  el.classList.toggle("over", n > 1000);
}

async function savePost(status) {
  const title = $("cTitle").value.trim();
  const body = $("finalDraft").value.trim();
  if (!title || !body) return toast("标题和正文都要有");
  await api("/api/posts/save", {
    account: $("accountSel").value,
    title,
    body,
    topic: $("cTopic").value.trim(),
    content_line: $("cLine").value,
    format: $("cFormat").value,
    tags: $("cTags").value.trim(),
    is_ad: $("cIsAd").checked,
    status,
    material_ids: getUsedMaterialIds(),
  });
  await reload();
  toast(`已存为「${status}」，去稿件库查看`);
}

// ---------- 稿件库 ----------
const STATUS_ORDER = ["素材", "草稿", "待确认", "已发布"];
const STATUS_COLOR = { 素材: "#86868b", 草稿: "#9a6a1a", 待确认: "#1d5c3f", 已发布: "#2e7d52" };

function renderPosts() {
  const box = $("postGroups");
  if (!posts.length) {
    box.innerHTML = '<div class="panel"><div class="muted">还没有稿件，去创作流程写一篇。</div></div>';
    return;
  }
  box.innerHTML = STATUS_ORDER.map(st => {
    const list = posts.filter(p => p.status === st);
    if (!list.length) return "";
    return `<div class="status-group">
      <h3><span class="status-dot" style="background:${STATUS_COLOR[st]}"></span>${st}（${list.length}）</h3>
      ${list.slice().reverse().map(p => `
        <div class="post-card">
          <div class="p-main">
            <div class="p-title">${esc(p.title)}</div>
            <div class="p-meta">
              <span class="tag line">${esc(p.content_line || "")}</span>
              ${p.format === "视频" ? '<span class="tag 灵感">视频</span>' : ""}
              ${p.is_ad ? '<span class="tag 商单">商单</span>' : ""}
              ${countChars(p.body)} 字 · ${esc(p.updated || p.created || "")}
            </div>
          </div>
          <div class="p-actions">
            <button class="small" onclick="openPost('${p.id}')">编辑</button>
            ${st === "已发布" ? `<button class="small" onclick="goAnalytics('${p.id}')">补数据</button>` : ""}
          </div>
        </div>`).join("")}
    </div>`;
  }).join("");
}

function openPost(id) {
  const p = posts.find(x => x.id === id);
  if (!p) return;
  currentEditingId = id;
  $("pmPostTitle").value = p.title || "";
  $("pmBody").value = p.body || "";
  $("pmLine").value = p.content_line || "流量线";
  $("pmFormat").value = p.format || "图文";
  $("pmStatus").value = p.status || "草稿";
  $("pmTags").value = p.tags || "";
  $("pmWordCount").textContent = countChars(p.body) + " 字";
  $("postModal").classList.remove("hidden");
}

function closeModal() {
  $("postModal").classList.add("hidden");
  currentEditingId = null;
}

async function savePostModal() {
  if (!currentEditingId) return;
  await api("/api/posts/save", {
    id: currentEditingId,
    title: $("pmPostTitle").value.trim(),
    body: $("pmBody").value,
    content_line: $("pmLine").value,
    format: $("pmFormat").value,
    status: $("pmStatus").value,
    tags: $("pmTags").value.trim(),
  });
  closeModal();
  await reload();
  toast("已保存");
}

async function deletePost() {
  if (!currentEditingId || !confirm("确认删除这篇稿件？")) return;
  await api("/api/posts/delete", { id: currentEditingId });
  closeModal();
  await reload();
}

function goAnalytics(postId) {
  localStorage.setItem("analytics_focus_post", postId);
  localStorage.setItem("analytics_account", $("accountSel").value);
  location.href = "analytics.html";
}

// ---------- 趋势灵感 ----------
const TREND_SOURCE_COLOR = {
  Pinterest: "#a8433c", X: "#1d1d1f", Instagram: "#8f5a80",
  YouTube: "#b04a3a", 全网: "#9a6a1a",
};

async function loadTrends() {
  const account = $("accountSel").value;
  const data = await api("/api/trends?account=" + encodeURIComponent(account));
  window._trendsCache = data;
  // 人设关键词默认从账号档案取
  const profile = (cfg.account_profiles || {})[account];
  if (profile && profile.identity && $("trendIdentity")) {
    $("trendIdentity").value = profile.identity;
  }
  renderTrends(data);
}

function renderTrends(data) {
  $("trendUpdated").textContent = data.updated
    ? "上次刷新：" + data.updated + "（热点由 AI 基于人设关键词生成，建议每天刷新一次）"
    : "还没有热点数据，点「刷新热点」生成第一组。";
  const box = $("trendList");
  const items = data.items || [];
  if (!items.length) {
    box.innerHTML = '<div class="panel"><div class="muted">暂无趋势。点上方「刷新热点」，AI 会按人设关键词抓取一组热点并附 3 个解读角度。</div></div>';
    return;
  }
  box.innerHTML = items.map(t => `
    <div class="panel trend-card">
      <div class="trend-head">
        <span class="tag" style="background:${TREND_SOURCE_COLOR[t.source] || "#666"};color:#fff;">${esc(t.source || "")}</span>
        <span class="tag line">${esc(t.category || "")}</span>
        <div class="trend-title">${esc(t.title || "")}</div>
        <div style="margin-left:auto;display:flex;gap:6px;">
          <button class="small" onclick="useTrend('${t.id}')">拿去创作</button>
          <button class="small danger" onclick="delTrend('${t.id}')">删</button>
        </div>
      </div>
      <div class="trend-summary">${esc(t.summary || "")}</div>
      <div class="trend-angles">
        ${(t.angles || []).map((a, i) => `
          <div class="trend-angle" onclick="useTrendAngle('${t.id}', ${i})" title="点击直接用这个角度开写">
            <b>解读 ${i + 1}</b>　${esc(a)}
          </div>`).join("")}
      </div>
    </div>`).join("");
}

async function refreshTrends() {
  const btn = $("trendBtn");
  btn.disabled = true;
  btn.textContent = "生成中（约 30-60 秒）…";
  const account = $("accountSel").value;
  const identity = $("trendIdentity").value.trim();
  const r = await api("/api/trends/refresh", { identity, count: 6, account });
  btn.disabled = false;
  btn.textContent = "刷新热点";
  if (r.error) {
    toast(r.error.split("\n")[0]);
    return;
  }
  window._trendsCache = r;
  renderTrends(r);
  toast("已更新 " + (r.items || []).length + " 条热点");
}

function useTrend(id) {
  const items = (window._trendsCache || {}).items || [];
  const t = items.find(x => x.id === id);
  const title = t ? t.title : "";
  useTrendAngleRaw(title, title);
}

function useTrendAngle(id, idx) {
  const items = (window._trendsCache || {}).items || [];
  const t = items.find(x => x.id === id);
  if (!t) return;
  useTrendAngleRaw(t.title, (t.angles || [])[idx] || t.title);
}

function useTrendAngleRaw(trendTitle, angle) {
  switchView("create");
  $("cTopic").value = trendTitle + "：" + angle;
  setStep(1);
  toast("已带入创作流程，点「生成角度建议」开始");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function delTrend(id) {
  await api("/api/trends/delete", { id, account: $("accountSel").value });
  await loadTrends();
}

// ---------- 排期 ----------
function renderSchedule() {
  const now = Date.now();
  const recent = posts.filter(p => {
    const t = new Date((p.created || "").replace(" ", "T")).getTime();
    return t && now - t < 30 * 864e5;
  });
  const published = recent.filter(p => p.status === "已发布");
  const pending = posts.filter(p => p.status === "待确认");

  const lines = cfg.content_lines || ["流量线", "收藏线", "人设线"];
  const target = cfg.ratio_target || {};
  const counts = {};
  lines.forEach(l => counts[l] = 0);
  published.forEach(p => { counts[p.content_line] = (counts[p.content_line] || 0) + 1; });
  const total = published.length || 1;
  const colors = { 流量线: "#1d5c3f", 收藏线: "#2e7d52", 人设线: "#9a6a1a" };

  $("ratioBar").innerHTML = lines.map(l =>
    `<div style="width:${(counts[l] / total * 100).toFixed(1)}%;background:${colors[l] || "#999"};"></div>`).join("");
  $("ratioLegend").innerHTML = lines.map(l =>
    `${l} ${counts[l]}/${published.length}（目标 ${target[l] || "-"}%）`).join(" · ");

  const row = (p) => `<div class="schedule-row">
    <span class="muted mono" style="width:90px;">${(p.created || "").slice(0, 10)}</span>
    <span class="tag line">${esc(p.content_line || "")}</span>
    <span style="flex:1;">${esc(p.title)}</span>
  </div>`;

  $("schedulePublished").innerHTML = published.length
    ? published.slice().reverse().map(row).join("")
    : '<div class="muted">近 30 天暂无已发布稿件</div>';
  $("schedulePending").innerHTML = pending.length
    ? pending.map(row).join("")
    : '<div class="muted">没有待发稿件</div>';
}

init();
