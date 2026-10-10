/* 数据分析页逻辑 */
"use strict";

const $ = (id) => document.getElementById(id);
let posts = [];
let analytics = [];
let summary = null;
let sortKey = "date";
let sortAsc = false;

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

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function n(x) {
  const v = parseInt(String(x).replace(/,/g, ""), 10);
  return isNaN(v) ? 0 : v;
}

async function init() {
  const cfg = await api("/api/config");
  const sel = $("accountSel");
  sel.innerHTML = (cfg.accounts || ["Jocelyn"]).map(a => `<option>${esc(a)}</option>`).join("");
  sel.value = localStorage.getItem("analytics_account") || localStorage.getItem("workbench_account") || cfg.accounts[0];
  sel.onchange = () => { localStorage.setItem("analytics_account", sel.value); reload(); };
  await reload();

  document.querySelectorAll(".data-table th[data-k]").forEach(th => {
    th.onclick = () => {
      const k = th.dataset.k;
      sortAsc = sortKey === k ? !sortAsc : false;
      sortKey = k;
      renderTable();
    };
  });
}

async function reload() {
  const account = $("accountSel").value;
  posts = await api("/api/posts?account=" + encodeURIComponent(account));
  analytics = await api("/api/analytics");
  summary = await api("/api/summary?account=" + encodeURIComponent(account));

  renderPostSelect();
  renderStatCards();
  renderAccountBox();
  renderTable();
  renderCharts();

  const focus = localStorage.getItem("analytics_focus_post");
  if (focus && [...$("aPost").options].some(o => o.value === focus)) {
    $("aPost").value = focus;
    localStorage.removeItem("analytics_focus_post");
    $("aPost").scrollIntoView({ behavior: "smooth", block: "center" });
    toast("已定位到该稿件，录入数据后点保存");
  }
}

function renderPostSelect() {
  const published = posts.filter(p => p.status === "已发布");
  $("aPost").innerHTML = published.length
    ? published.slice().reverse().map(p => `<option value="${p.id}">${esc((p.created || "").slice(0, 10))} · ${esc(p.title)}</option>`).join("")
    : '<option value="">（暂无已发布稿件）</option>';
}

async function saveAnalytics() {
  const postId = $("aPost").value;
  if (!postId) return toast("先选择稿件");
  await api("/api/analytics/save", {
    post_id: postId,
    account: $("accountSel").value,
    node: $("aNode").value,
    views: $("aViews").value,
    likes: $("aLikes").value,
    collects: $("aCollects").value,
    comments: $("aComments").value,
    shares: $("aShares").value,
    followers: $("aFollowers").value,
    profile_visits: $("aProfile").value,
  });
  toast("数据已保存");
  await reload();
}

function renderStatCards() {
  const t = summary.totals || {};
  const cards = [
    ["已发布", t.posts ?? 0],
    ["总曝光", (t.impressions ?? 0) || "—"],
    ["总观看", t.views ?? 0],
    ["总互动（赞+藏）", (t.likes ?? 0) + (t.collects ?? 0)],
    ["总分享", t.shares ?? 0],
    ["累计涨粉", t.followers ?? 0],
  ];
  $("statCards").innerHTML = cards.map(([k, v]) =>
    `<div class="stat-card"><div class="v">${typeof v === "number" ? Number(v).toLocaleString() : v}</div><div class="k">${k}</div></div>`).join("");
}

async function renderAccountBox() {
  const account = $("accountSel").value;
  const snap = await api("/api/account?account=" + encodeURIComponent(account));
  const box = $("accountBox");
  if (!snap || !snap.date) { box.style.display = "none"; return; }
  box.style.display = "";
  $("accountPeriod").textContent = `（创作者后台 · ${snap.period || snap.date} 抓取）`;
  const items = [
    ["总粉丝", snap.followers_total],
    ["本周观看", snap.views_week],
    ["本周曝光", snap.impressions_week],
    ["本周互动", snap.interactions_week],
    ["主页访客", snap.profile_visits],
    ["主页转粉率", snap.profile_to_follower_rate != null ? (snap.profile_to_follower_rate * 100).toFixed(1) + "%" : "—"],
    ["封面点击率", snap.ctr_week != null ? (snap.ctr_week * 100).toFixed(1) + "%" : "—"],
    ["平均观看时长", snap.avg_watch_seconds_week != null ? snap.avg_watch_seconds_week + " 秒" : "—"],
  ];
  $("accountGrid").innerHTML = items.map(([k, v]) =>
    `<div class="stat-card"><div class="v" style="font-size:20px;">${v ?? "—"}</div><div class="k">${k}</div></div>`).join("");
  const hints = [];
  if (snap.followers_percentile != null && snap.followers_percentile <= 20) {
    hints.push(`涨粉只超过 ${snap.followers_percentile}% 同类创作者，而观看超过 ${snap.views_percentile}%——流量没问题，瓶颈在「关注理由」。`);
  }
  if (snap.fan_interests && snap.fan_interests.length) {
    hints.push(`粉丝兴趣画像：${snap.fan_interests.slice(0, 4).join(" / ")}。`);
  }
  $("accountHint").textContent = hints.join(" ");
}

function rowsWithMeta() {
  return analytics.map(a => {
    const p = posts.find(x => x.id === a.post_id) || {};
    const views = n(a.views), likes = n(a.likes), collects = n(a.collects);
    return {
      date: (p.created || "").slice(0, 10),
      title: p.title || "（已删除稿件）",
      line: p.content_line || "未分类",
      impressions: n(a.impressions),
      views, likes, collects,
      ctr: parseFloat(a.ctr) || 0,
      comments: n(a.comments), shares: n(a.shares),
      followers: n(a.followers),
      rate: views ? ((likes + collects) / views * 100) : 0,
    };
  });
}

function renderTable() {
  const rows = rowsWithMeta();
  const best = summary.best || {};
  const hot = summary.hottest || {};
  if (best.title || hot.title) {
    const b = best.title ? `表现最好：<span class="best-badge">${esc(best.title)}</span>（观看 ${n(best.views).toLocaleString()}）` : "";
    const h = hot.title ? `最热：<span class="best-badge">${esc(hot.title)}</span>（赞 ${n(hot.likes).toLocaleString()}，小红书实时同步）` : "";
    $("bestHint").innerHTML = [b, h].filter(Boolean).join(" · ");
  } else {
    $("bestHint").textContent = "录入数据后，这里会标出表现最好的一篇。";
  }
  rows.sort((a, b) => {
    const va = a[sortKey], vb = b[sortKey];
    const cmp = typeof va === "number" ? va - vb : String(va).localeCompare(String(vb));
    return sortAsc ? cmp : -cmp;
  });
  $("dataTable").querySelector("tbody").innerHTML = rows.map(r => `
    <tr>
      <td class="mono">${esc(r.date)}</td>
      <td>${esc(r.title)}</td>
      <td><span class="tag line">${esc(r.line)}</span></td>
      <td>${r.impressions ? r.impressions.toLocaleString() : "—"}</td>
      <td>${r.views ? r.views.toLocaleString() : "—"}</td>
      <td>${r.ctr ? r.ctr.toFixed(1) + "%" : "—"}</td>
      <td>${r.likes}</td>
      <td>${r.collects}</td>
      <td>${r.comments}</td>
      <td>${r.shares}</td>
      <td>${r.followers}</td>
      <td>${r.rate ? r.rate.toFixed(1) + "%" : "—"}</td>
    </tr>`).join("") || '<tr><td colspan="12" class="muted">暂无数据</td></tr>';
}

function renderCharts() {
  if (typeof echarts === "undefined") return;

  // 趋势
  const trend = (summary.trend || []).filter(t => t.date);
  const trendChart = echarts.init($("chartTrend"));
  trendChart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: ["观看", "涨粉"] },
    grid: { left: 40, right: 40, top: 40, bottom: 30 },
    xAxis: { type: "category", data: trend.map(t => t.date) },
    yAxis: [{ type: "value", name: "观看" }, { type: "value", name: "涨粉" }],
    series: [
      { name: "观看", type: "bar", data: trend.map(t => t.views), itemStyle: { color: "#1d5c3f" } },
      { name: "涨粉", type: "line", yAxisIndex: 1, data: trend.map(t => t.followers), itemStyle: { color: "#9a6a1a" } },
    ],
  });

  // 漏斗：有曝光数据时从曝光开始，展示 曝光→观看（封面点击率）→互动→关注
  const f = summary.funnel || {};
  const t0 = summary.totals || {};
  const funnelChart = echarts.init($("chartFunnel"));
  const funnelData = [];
  if (t0.impressions) funnelData.push({ name: "曝光", value: t0.impressions });
  funnelData.push(
    { name: "观看", value: f.views || 0 },
    { name: "赞藏互动", value: f.engagement || 0 },
  );
  if (f.profile_visits) funnelData.push({ name: "主页访问", value: f.profile_visits });
  funnelData.push({ name: "关注", value: f.followers || 0 });
  funnelChart.setOption({
    tooltip: { trigger: "item", formatter: "{b}: {c}" },
    series: [{
      type: "funnel",
      left: "10%", width: "80%",
      label: { formatter: "{b}\n{c}" },
      itemStyle: { borderColor: "#fff", borderWidth: 2 },
      data: funnelData,
      color: ["#144631", "#1d5c3f", "#2e7d52", "#7ba98c", "#9a6a1a"],
    }],
  });

  // 内容线对比
  const byLine = summary.by_line || {};
  const lineNames = Object.keys(byLine);
  const avgViews = lineNames.map(l => byLine[l].count ? Math.round(byLine[l].views / byLine[l].count) : 0);
  const collectRate = lineNames.map(l => byLine[l].views ? +(byLine[l].collects / byLine[l].views * 100).toFixed(1) : 0);
  const followerRate = lineNames.map(l => byLine[l].views ? +(byLine[l].followers / byLine[l].views * 100).toFixed(2) : 0);
  const lineChart = echarts.init($("chartLine"));
  lineChart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: ["平均观看", "收藏率%", "转粉率%"] },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: { type: "category", data: lineNames },
    yAxis: [{ type: "value", name: "观看" }, { type: "value", name: "%" }],
    series: [
      { name: "平均观看", type: "bar", data: avgViews, itemStyle: { color: "#1d5c3f" } },
      { name: "收藏率%", type: "bar", yAxisIndex: 1, data: collectRate, itemStyle: { color: "#2e7d52" } },
      { name: "转粉率%", type: "bar", yAxisIndex: 1, data: followerRate, itemStyle: { color: "#9a6a1a" } },
    ],
  });

  window.onresize = () => { trendChart.resize(); funnelChart.resize(); lineChart.resize(); };
}

init();
