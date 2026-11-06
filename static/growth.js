'use strict';
const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state, active='today', busy=false;
const labels={views:'观看',likes:'赞',collects:'收藏',comments:'评论',followers:'新增关注',profile_visits:'主页访问'};
const num=v=>v===null||v===undefined?'—':Number(v).toLocaleString('zh-CN');
const statusName={proposed:'待讨论',confirmed:'已确认',done:'已完成',cancelled:'已搁置'};
async function api(path,body){const r=await fetch('/api/growth'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,version:state?.version})});const d=await r.json();if(!r.ok||d.error)throw Error(d.error||'请求失败');return d;}
function notice(s){$('notice').textContent=s;}
function tab(id){active=id;document.querySelectorAll('.tab').forEach(x=>x.hidden=x.id!==id);document.querySelectorAll('nav [data-tab]').forEach(x=>x.classList.toggle('active',x.dataset.tab===id));}
async function load(){state=await api('');render();}
async function mutation(path,body,success){if(busy)return;busy=true;const buttons=[...document.querySelectorAll('form button,.actions button')];buttons.forEach(b=>b.disabled=true);try{await api(path,body);await load();notice(success);return true;}catch(e){notice(e.message);if(e.message.includes('页面已更新'))await load();return false;}finally{busy=false;buttons.forEach(b=>b.disabled=false);}}
function planButtons(p){if(p.status==='proposed')return `<button class="primary" data-id="${p.id}" data-status="confirmed">确认这件事</button><button data-id="${p.id}" data-status="cancelled">先搁置</button>`;if(p.status==='confirmed')return `<button class="primary" data-id="${p.id}" data-status="done">这一步做完了</button><button data-id="${p.id}" data-status="proposed">撤回重议</button>`;return `<button data-id="${p.id}" data-status="${p.status==='done'?'confirmed':'proposed'}">${p.status==='done'?'撤销完成':'重新讨论'}</button>`;}
function render(){
 const snaps=[...state.snapshots].sort((a,b)=>a.date.localeCompare(b.date)), last=snaps.at(-1), prev=snaps.at(-2),goal=state.goal;
 $('date-label').textContent=state.today.replaceAll('-',' / ');
 $('followers').textContent=num(last?.followers);$('source').textContent=last?`${last.date} · ${last.source}`:'暂无记录';
 $('delta').textContent=prev?`${last.followers-prev.followers>=0?'+':''}${last.followers-prev.followers}`:'—';$('period').textContent=prev?`${prev.date} → ${last.date}`:'需两次账号记录';
 $('goal-label').textContent=goal.confirmed?`目标 ${num(goal.target)} 粉`:`历史愿望 ${num(goal.target)} 粉 · 待确认`;
 const gap=last?Math.max(0,goal.target-last.followers):null;
 $('remaining').textContent=gap===0?'已经达到':gap===null?'—':`还差 ${num(gap)}`;
 $('progress').style.width=last?Math.min(100,last.followers/goal.target*100)+'%':'0%';
 $('goal-note').textContent=goal.deadline?`目标日 ${goal.deadline} · 不自动加量`:'截止日期未定 · 按最近记录计算';
 const stale=last && (Date.parse(state.today)-Date.parse(last.date))/86400000>3;
 if(!$('notice').textContent && stale)notice(`最近数据来自 ${last.date}，仅供参考。今天的安排由你确认。`);
 const p=state.plans.find(p=>p.date===state.today&&['confirmed','done'].includes(p.status));
 $('today-tag').textContent=p?statusName[p.status]:'留白也可以';
 $('today-content').innerHTML=p?`<h3>${esc(p.title)}</h3><p>你留出的时间：${p.minutes} 分钟</p><p><b>先花 5 分钟：</b>${esc(p.step)}</p><div class="actions">${planButtons(p)}</div>`:`<h3>今天还没有确认的安排。</h3><p class="muted">先聊聊你想做什么、有多少精力。<br>不需要为了填满日历而发帖。</p><button class="primary" data-tab="plan">一起定下一小步 →</button>`;
 const upcoming=state.plans.filter(p=>p.date>=state.today&&p.status==='confirmed').sort((a,b)=>a.date.localeCompare(b.date));
 $('upcoming').innerHTML=upcoming.length?upcoming.slice(0,3).map(p=>`<div class="card"><small>${p.date} · ${p.minutes} 分钟</small><h2>${esc(p.title)}</h2><span class="badge">已确认</span></div>`).join(''):'<div class="empty">还没有确定的日程。讨论中的想法留在草案里。</div>';
 const latest24=latestMetrics('24h').filter(m=>m.followers!==null);
 const best=latest24.sort((a,b)=>b.followers-a.followers)[0];
 $('insight').innerHTML=best?`<p>${esc(best.title)}</p><h3>+${num(best.followers)} 关注</h3><small>发布后24小时 · ${best.date} 手动记录</small><p class="muted">先回看这篇的内容和评论，再讨论是否延续。</p>`:'<p class="muted">还缺少同口径的新增关注数据。</p><p>下一次记一篇笔记的<br><b>24 小时观看与新增关注</b>，<br>再判断什么值得延续。</p>';
 $('messages').innerHTML=state.messages.length?state.messages.map(m=>`<div class="message ${m.role==='user'?'user':''}"><small>${m.role==='user'?'你':m.unavailable?'工作台 · 离线提示':'创作搭档'}</small>${esc(m.text)}</div>`).join(''):'<div class="message">我们先留白。等你有想法，再从最想推进的一件事开始。</div>';
 $('plans').innerHTML=state.plans.length?[...state.plans].reverse().map(p=>`<div class="plan-row"><div><small>${p.date} · ${p.minutes} 分钟 · ${statusName[p.status]}${p.date<state.today&&p.status!=='done'?' · 日期已过，可重新讨论':''}</small><p><b>${esc(p.title)}</b></p><small>依据：${esc(p.context)}</small><small>先做：${esc(p.step)}</small></div><div class="actions">${planButtons(p)}</div></div>`).join(''):'<div class="empty">暂无草案，不会从题库自动给你排满一周。</div>';
 $('history').innerHTML=[...snaps].reverse().map(s=>`<div class="history-row">${s.date} · <b>${num(s.followers)} 粉</b> · 赞藏 ${num(s.likes_collects)}<small>${esc(s.source)}</small></div>`).join('');
 $('legacy-date').textContent=`文件标注采集日期：${state.legacy.date}。未核验时效，未知关注数不当作0；不混入新记录排行。`;
 $('legacy-notes').innerHTML=state.legacy.notes.slice().sort((a,b)=>(b.likes??0)-(a.likes??0)).map(n=>`<div class="history-row">${esc(n.title)}<small>赞 ${num(n.likes)} · 藏 ${num(n.collects)} · 新增关注 未提供</small></div>`).join('');
 $('old-drafts').innerHTML=[...(state.legacy.drafts||[]).map(d=>({...d,kind:'旧草稿'})),...(state.legacy.archive||[]).map(d=>({...d,kind:'历史存档',key:d.date}))].map(d=>`<details><summary>${esc(d.kind)} · ${esc(d.key)} · ${esc(d.title)}</summary><p style="white-space:pre-wrap">${esc(d.body)}</p></details>`).join('')||'<p class="muted">暂无旧稿</p>';
 $('old-metrics').innerHTML=(state.legacy.analytics||[]).map(m=>`<div class="history-row">${esc(m.t)}<small>${esc(m.node)} · 观看 ${num(m.views)} · 关注 ${num(m.followers)}（旧值，待核验）</small></div>`).join('');
 $('note-titles').innerHTML=[...new Set([...state.metrics.map(n=>n.title),...state.legacy.notes.map(n=>n.title)])].map(t=>`<option value="${esc(t)}"></option>`).join('');
 for(const id of ['snap-date','metric-date','plan-date'])if(!$(id).value)$(id).value=state.today;
 $('snap-date').max=$('metric-date').max=state.today;$('plan-date').min=$('goal-deadline').min=state.today;
 renderMetrics();if(typeof renderCycle==='function')renderCycle();tab(active);
}
function latestMetrics(window){const by=new Map();state.metrics.filter(m=>m.window===window).sort((a,b)=>a.date.localeCompare(b.date)).forEach(m=>by.set(m.title,m));return [...by.values()];}
function renderMetrics(){const rows=latestMetrics($('window-filter').value).sort((a,b)=>(b.followers??-1)-(a.followers??-1));$('metric-rows').innerHTML=rows.length?rows.map(m=>`<tr><td>${esc(m.title)}<small>${m.date}</small></td><td>${num(m.views)}</td><td>${num(m.likes)} / ${num(m.collects)}</td><td>${num(m.followers)}</td><td>${m.views>0&&m.followers!==null?(m.followers/m.views*100).toFixed(2)+'%':'—'}</td><td>${m.views>0&&m.collects!==null?(m.collects/m.views*100).toFixed(2)+'%':'—'}</td></tr>`).join(''):'<tr><td colspan="6">这个口径还没有记录，先记一篇就好。</td></tr>';}
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.tab)tab(b.dataset.tab);if(b.dataset.status)await mutation('/status',{id:b.dataset.id,status:b.dataset.status},'安排已保存');});
$('record-shortcut').onclick=()=>{tab('data');$('snap-followers').focus();};
$('goal-open').onclick=()=>{$('goal-target').value=state.goal.target;$('goal-deadline').value=state.goal.deadline;$('goal-dialog').showModal();};$('goal-close').onclick=()=>$('goal-dialog').close();
$('goal-form').onsubmit=async e=>{e.preventDefault();if(await mutation('/goal',{target:$('goal-target').value,deadline:$('goal-deadline').value},'目标已确认'))$('goal-dialog').close();};
$('snapshot-form').onsubmit=async e=>{e.preventDefault();await mutation('/snapshot',{date:$('snap-date').value,followers:$('snap-followers').value,likes_collects:$('snap-likes').value},'账号快照已保存');};
$('metric-form').onsubmit=async e=>{e.preventDefault();const data={title:$('metric-title').value,date:$('metric-date').value,window:$('metric-window').value};Object.keys(labels).forEach(k=>data[k]=$('metric-'+k).value);await mutation('/metric',data,'笔记表现已保存');};
$('plan-form').onsubmit=async e=>{e.preventDefault();await mutation('/plan',{title:$('plan-title').value,date:$('plan-date').value,minutes:$('plan-minutes').value,context:$('plan-context').value,step:$('plan-step').value},'草案已保存，确认后才会进入日程');};
$('chat-form').onsubmit=async e=>{e.preventDefault();const message=$('message').value;$('chat-send').textContent='正在一起想…';notice('想法正在保存，等待创作搭档回复…');if(await mutation('/discuss',{message},'讨论已保存，排期仍由你确认')){$('message').value='';if(!$('plan-context').value)$('plan-context').value=message;$('messages').scrollTop=$('messages').scrollHeight;}$('chat-send').textContent='一起想一想';};
$('window-filter').onchange=renderMetrics;
$('metric-inputs').innerHTML=Object.entries(labels).map(([k,v])=>`<div><label for="metric-${k}">${v}</label><input id="metric-${k}" type="number" min="0" placeholder="未知留空"></div>`).join('');
$('export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`jocelyn-${state.today}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
document.addEventListener('DOMContentLoaded',()=>load().catch(e=>{notice('工作台未能读取数据：'+e.message+'。请刷新重试。');}));
