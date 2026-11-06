"""Read-only public source collection; adopting a candidate is a separate action."""
import datetime as dt, hashlib, json, subprocess, urllib.request, urllib.parse, fcntl
from pathlib import Path
from zoneinfo import ZoneInfo
BASE=Path(__file__).resolve().parent
SOURCES=('Hacker News','GitHub')
def now():return dt.datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
def read():
 p=BASE/'data/material_feed.json'
 return json.loads(p.read_text()) if p.exists() else {'items':[],'sources':{},'checked_at':''}
def write(d):
 p=BASE/'data/material_feed.json';p.parent.mkdir(exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2));tmp.replace(p)
def safe_url(url):return str(url or '') if urllib.parse.urlsplit(str(url or '')).scheme in ('http','https') else ''
def item(source,title,url,published,summary,metric):
 url=safe_url(url)
 if not title or not url:raise ValueError('Invalid source item')
 return {'id':hashlib.sha256(url.encode()).hexdigest()[:20],'source':source,'title':title[:200],'url':url,'source_date':published,'summary':(summary or '')[:800],'metric':metric,'fetched_at':now()}
def fetch_hn():
 cutoff=int((dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)).timestamp())
 query=urllib.parse.urlencode({'query':'AI','tags':'story','numericFilters':f'points>5,created_at_i>{cutoff}','hitsPerPage':12})
 req=urllib.request.Request('https://hn.algolia.com/api/v1/search_by_date?'+query,headers={'User-Agent':'CreatorWorkbench/1.0'})
 with urllib.request.urlopen(req,timeout=25) as r:d=json.load(r)
 return [item('Hacker News',h['title'],safe_url(h.get('url')) or 'https://news.ycombinator.com/item?id='+h['objectID'],h.get('created_at',''),'社区讨论线索；观点与事实需查看原文。',str(h.get('points',0))+' 分 · '+str(h.get('num_comments',0))+' 评论') for h in d['hits'] if h.get('title')]
def fetch_github():
 cutoff=(dt.date.today()-dt.timedelta(days=7)).isoformat()
 endpoint='search/repositories?'+urllib.parse.urlencode({'q':f'topic:artificial-intelligence pushed:>{cutoff} stars:>100 archived:false','sort':'updated','per_page':12})
 p=subprocess.run(['gh','api',endpoint],capture_output=True,text=True,timeout=40)
 if p.returncode:raise RuntimeError('GitHub request failed')
 d=json.loads(p.stdout)
 return [item('GitHub',h['full_name'],h['html_url'],h['pushed_at'],h.get('description'),str(h.get('stargazers_count',0))+' 总星标 · 近期更新（非涨速榜）') for h in d['items']]
def collect():
 (BASE/'data').mkdir(exist_ok=True)
 with (BASE/'data/material_feed.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  d=read();items=d['items'];statuses=d.get('sources',{})
  for name,fetch in [('Hacker News',fetch_hn),('GitHub',fetch_github)]:
   previous=statuses.get(name,{})
   try:
    fresh=fetch()
    if not fresh:raise ValueError('Empty response')
    items=[x for x in items if x['source']!=name]+fresh
    statuses[name]={'ok':True,'last_success':now(),'count':len(fresh)}
   except Exception:
    statuses[name]={**previous,'ok':False,'error':'暂时无法采集，保留上次素材','checked_at':now()}
  unique={x['id']:x for x in items};d={'items':sorted(unique.values(),key=lambda x:x['source_date'],reverse=True),'sources':statuses,'checked_at':now()};write(d);return d

def view():
 d=read();current=dt.datetime.now(dt.timezone.utc)
 for status in d['sources'].values():
  stamp=status.get('last_success')
  status['stale']=not stamp or (current-dt.datetime.fromisoformat(stamp)).total_seconds()>86400
 return d

def adopt(body):
 import feishu_board as board
 candidate=next((i for i in read()['items'] if i['id']==body.get('id')),None)
 if not candidate:raise ValueError('素材已更新，请刷新后重选')
 key='material:'+candidate['id']
 with (board.BASE/'data/feishu_board.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  old=next((r for r in board.rows('topics') if r.get('工作台ID')==key),None)
  if old:return {'ok':True,'id':old['record_id']}
  notes=f"来源：{candidate['source']}\n原文：{candidate['url']}\n来源时间：{candidate['source_date']}\n{candidate['metric']}\n{candidate['summary']}\n待核实素材，尚未形成账号观点。先阅读原文，再补充个人判断与真实经历。"
  saved=board.put('topics',{'工作台ID':key,'选题标题':candidate['title'],'收录日期':now()[:10]+' 00:00:00','为什么值得做':notes,'生产说明':notes,'状态':'待使用','账号':'Jocelyn'})
  if not saved:raise RuntimeError('No confirmed record')
  return {'ok':True,'id':saved['record_id']}
def handle(h,method,path):
 if path not in ('/api/material-feed','/api/material-feed/refresh','/api/material-feed/adopt','/api/hot/today'):return False
 try:
  if method=='GET' and path=='/api/material-feed':h._send_json(view())
  elif method=='GET' and path=='/api/hot/today':
   d=view();h._send_json({'date':d['checked_at'][:10],'hots':[{'name':i['title'],'stat':i['metric'],'url':i['url'],'source_date':i['source_date']} for i in d['items'][:12]],'sources':d['sources'],'error':None if d['items'] else '素材尚未采集，请在新版工作台刷新'})
  elif method=='POST' and path.endswith('/refresh'):h._read_json();h._send_json(collect())
  elif method=='POST' and path.endswith('/adopt'):h._send_json(adopt(h._read_json()))
  else:h._send_json({'error':'不支持此操作'},405)
 except ValueError as e:h._send_json({'error':str(e)},400)
 except Exception:h._send_json({'error':'操作未完成；请稍后重试，已有素材仍保留'},503)
 return True
if __name__=='__main__':
 d=collect();print(json.dumps({'checked_at':d['checked_at'],'count':len(d['items']),'sources':d['sources']},ensure_ascii=False))
 raise SystemExit(0 if all(s.get('ok') for s in d['sources'].values()) else 1)
