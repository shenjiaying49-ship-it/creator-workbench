"""Single-app weekly planning, editing adapters and consolidated review data."""
import json,datetime as dt,fcntl,uuid
from pathlib import Path
import creation_desk as desk
import feishu_board as board
import growth
BASE=Path(__file__).resolve().parent
def read(n,d):
 p=BASE/n
 return json.loads(p.read_text()) if p.exists() else d
def write(n,d):
 p=BASE/n;p.parent.mkdir(exist_ok=True,parents=True);t=p.with_suffix('.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2));t.replace(p)
def local():return read('data/workspace_app.json',{'version':0,'tasks':[],'done':{},'reviews':[],'edits':{}})
def monday(s):
 d=dt.date.fromisoformat(s);return (d-dt.timedelta(days=d.weekday())).isoformat()
def view(start):
 start=monday(start);days=[(dt.date.fromisoformat(start)+dt.timedelta(days=i)).isoformat() for i in range(7)];data=local();cloud=board.view();all_=read('data/daily_creations.json',{});tasks=[]
 for day in days:
  drafts=[r for r in all_.values() if r['day']==day];mother=next((r for r in drafts if r['platform']=='小红书'),next(iter(drafts),None))
  if not mother and (day<desk.today() or any(t['date']==day and t['account']=='Jocelyn' for t in cloud['topics'])):continue
  tasks.append({'id':'daily:'+day,'day':day,'title':mother['title'] if mother else '查看 Codex 今日建议稿','kind':'稿件' if mother else '每日建议','action':'edit','minutes':None,'topic':'','state':mother['status'] if mother else '待备稿'})
 for t in cloud['topics']:
  if t['date'] in days and t['account']=='Jocelyn':tasks.append({'id':'topic:'+t['id'],'day':t['date'],'title':t['title'],'kind':'已排创作','action':'edit','topic':t['id'],'minutes':t['minutes'],'state':'已安排'})
 for t in cloud['topics']:
  if t['date'] in days and any(r.get('source_id')==t['id'] and r['day']==t['date'] for r in all_.values()):
   tasks=[x for x in tasks if x['id']!='daily:'+t['date']]
 tasks.extend({**t,'action':'task','kind':'自定任务','state':'待完成'} for t in data['tasks'] if t['day'] in days)
 if days[-1]>=desk.today() or data['done'].get('review:'+days[-1]):tasks.append({'id':'review:'+days[-1],'day':days[-1],'title':'本周数据复盘','kind':'每周建议','action':'review','minutes':None,'state':'建议'})
 for t in tasks:t['done']=bool(data['done'].get(t['id']))
 g=growth.read(str(BASE));metrics=list(g.get('metrics',[]));new=data['reviews'];keys={(r['title'],r['date'],r['window'],r.get('platform','小红书')) for r in new};metrics=[r for r in metrics if (r['title'],r['date'],r['window'],r.get('platform','小红书')) not in keys]+new
 posts={r['id']:r for r in read('data/posts.json',[])};titles={k:r.get('title','') for k,r in posts.items()}
 legacy=[{**r,'title':titles.get(r.get('post_id')) or r.get('post_id','')} for r in read('data/analytics.json',[]) if (r.get('account') or posts.get(r.get('post_id'),{}).get('account'))=='Jocelyn']
 return {'start':start,'days':days,'tasks':tasks,'version':data['version'],'snapshot_version':g['version'],'snapshots':g.get('snapshots',[]),'metrics':metrics,'cloud_reviews':cloud['reviews'],'legacy_metrics':legacy,'works':cloud['works'],'synced_at':cloud['synced_at']}
def editor(day,topic):
 d=desk.state(day)
 if not topic:return d
 cloud=board.view();t=next((x for x in cloud['topics'] if x['id']==topic),None)
 if not t:raise ValueError('选题不存在，请刷新五库')
 records=[r for r in d['records'] if r['source_id']==topic];edits=local()['edits']
 for w in cloud['works']:
  if topic not in w['topics']:continue
  source=edits.get(w['id'],{'title':w['title'],'body':w['body'],'id':w['id']})
  records.append({'id':w['id'],'day':day,'platform':'小红书','form':'口播' if w['format']=='短视频' else '图文','title':source['title'],'body':source['body'],'tags':[],'status':'已修改 · 待你确认' if w['id'] in edits else w['status'],'edited':w['id'] in edits,'version':desk.digest(source),'origin':'feishu-work','source_id':topic,'form_reason':'来自该选题的已有'+w['format']+'稿件。','fit_reason':t['notes'],'provenance':None})
 d['records']=records;d['topic_title']=t['title'];return d

def mutate(action,b):
 with (BASE/'data/workspace_app.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);d=local()
  if action=='save-work':
   w=next((w for w in board.view()['works'] if w['id']==b['id']),None)
   if not w:raise ValueError('原稿不存在')
   old=d['edits'].get(w['id'],{'title':w['title'],'body':w['body'],'id':w['id']})
   if desk.digest(old)!=b.get('version'):raise ValueError('稿件已经变化，请保留文字并刷新后合并')
   if not str(b.get('title','')).strip():raise ValueError('标题不能为空')
   desk.write('data/creation-history/work-'+w['id']+'-'+uuid.uuid4().hex[:6]+'.json',old)
   d['edits'][w['id']]={'id':w['id'],'title':str(b['title'])[:200],'body':str(b.get('body',''))[:30000],'updated_at':board.now()}
  else:
   if d['version']!=b.get('version'):raise ValueError('页面数据已经变化，请刷新后重试')
   if action=='done':d['done'][str(b['id'])[:150]]=bool(b.get('done'))
   elif action=='task':
    day=dt.date.fromisoformat(b['day']).isoformat();title=str(b.get('title','')).strip();minutes=int(b.get('minutes',15))
    if not title or not 1<=minutes<=480:raise ValueError('请输入任务和1—480分钟预算')
    d['tasks'].append({'id':'task:'+uuid.uuid4().hex[:10],'day':day,'title':title[:200],'minutes':minutes})
   elif action=='review':
    title=str(b.get('title','')).strip();date=dt.date.fromisoformat(b['date']).isoformat();window=b['window']
    if not title or date>desk.today() or window not in ('24h','7d','累计'):raise ValueError('请核对标题、日期和观察口径')
    row={'title':title[:200],'date':date,'window':window,'platform':b.get('platform','小红书'),'next':str(b.get('next',''))[:3000],'observation':str(b.get('observation',''))[:3000],'source':'工作台录入'}
    for k in ['views','collects','followers','likes','comments','profile_visits']:row[k]=growth.number(b.get(k),True)
    if all(row[k] is None for k in ['views','collects','followers','likes','comments','profile_visits']) and not row['observation']:raise ValueError('至少填一项数据或复盘观察')
    d['reviews']=[x for x in d['reviews'] if (x['title'],x['date'],x['window'],x['platform'])!=(title,date,window,row['platform'])]+[row]
   else:raise ValueError('未知操作')
  d['version']+=1;write('data/workspace_app.json',d);return {'ok':True}
def handle(h,method,path,qs):
 if not path.startswith('/api/workspace'):return False
 try:
  if method=='GET':r=editor(qs.get('day',[desk.today()])[0],qs.get('topic',[''])[0]) if path.endswith('/editor') else view(qs.get('start',[desk.today()])[0])
  else:r=mutate(path.rsplit('/',1)[-1],h._read_json())
  h._send_json(r)
 except (ValueError,KeyError,TypeError) as e:h._send_json({'error':str(e)},409)
 except Exception:h._send_json({'error':'读取或保存失败，原有数据仍保留。'},503)
 return True
