"""Feishu-backed creator board. Local JSON is a recoverable read cache only."""
import json,os,subprocess,tempfile,hashlib,datetime as dt,fcntl
from pathlib import Path
from zoneinfo import ZoneInfo
BASE=Path(__file__).resolve().parent
TABLES={'topics':'tblwVlgtdprHLcxu','works':'tblyQYdwdkiiKUtY','reviews':'tblD2erv6vZWe984','examples':'tblw1g4EZYOVVDD3','rules':'tble0ODUvREvWzTC'}
def now():return dt.datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
def read(name,default):
 p=BASE/name
 return json.loads(p.read_text()) if p.exists() else default

def write(name,data):
 p=BASE/name;p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(p)

def token():
 v=os.environ.get('WUKU_BASE_TOKEN') or read('config.json',{}).get('wuku',{}).get('base_token')
 if not v:raise ValueError('尚未配置飞书五库')
 return v

def cli(command,table,*args):
 with tempfile.TemporaryDirectory(prefix='creator-base-') as folder:
  p=subprocess.run(['lark-cli','base',command,'--base-token',token(),'--table-id',TABLES[table],*args],capture_output=True,text=True,cwd=folder,timeout=90)
  try:d=json.loads(p.stdout)
  except ValueError:raise RuntimeError('飞书暂时连接失败，请检查网络与本机登录')
  if p.returncode or d.get('ok') is False:raise RuntimeError('飞书操作失败，未确认保存；请检查登录或表权限')
  if d.get('record_file'):
   rows=[json.loads(l) for l in Path(d['record_file']).read_text().splitlines() if l.strip()]
   return {'rows':rows,'has_more':d.get('has_more',False)}
  return d.get('data',d)

def rows(table):
 allrows=[]
 while True:
  d=cli('+record-list',table,'--offset',str(len(allrows)),'--limit','200');page=d['rows'];allrows+=page
  if not d['has_more']:return allrows
  if not page:raise RuntimeError('飞书分页异常，保留上次数据')

def one(table,rid):
 d=cli('+record-get',table,'--record-id',rid)
 if d.get('rows'):return d['rows'][0]
 r=d.get('record')
 if r:return r
 raise ValueError('记录不存在，请刷新')

def first(v):return v[0] if isinstance(v,list) and v else ('' if v is None or v==[] else v)
def stamp(r):return hashlib.sha256(json.dumps(r,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def cache():return read('data/feishu_board.json',{'topics':[],'works':[],'reviews':[],'rules':[],'examples':[],'synced_at':''})
def sync():
 d={k:rows(k) for k in TABLES};d['synced_at']=now();write('data/feishu_board.json',d);write('data/feishu_board_health.json',{'ok':True,'checked_at':now()});return view(d)
def view(d=None):
 d=d or cache();out={'synced_at':d.get('synced_at',''),'health':read('data/feishu_board_health.json',{}),'base_url':'https://feishu.doubao.com/base/'+token(),'topics':[],'works':[],'reviews':[]}
 for r in d['topics']:
  if not r.get('工作台ID') and str(r.get('收录日期') or '')[:10]<'2026-10-15':continue
  out['topics'].append({'id':r['record_id'],'title':r.get('选题标题',''),'date':str(r.get('计划日期') or '')[:10],'minutes':r.get('预计分钟'),'notes':r.get('生产说明') or r.get('为什么值得做') or '', 'status':first(r.get('状态')),'version':stamp(r),'account':r.get('账号') or 'Jocelyn'})
 for r in d['works']:
  if not r.get('工作台ID') and str(r.get('发布时间') or '')[:10]<'2026-10-15':continue
  out['works'].append({'id':r['record_id'],'title':r.get('作品标题',''),'body':r.get('正文') or '', 'status':first(r.get('制作状态')) or ('已发布' if r.get('发布时间') else '草稿'),'format':first(r.get('作品类型')),'topics':[x['id'] for x in r.get('关联选题') or []],'date':str(r.get('发布时间') or '')[:10], 'version':stamp(r),'account':r.get('账号') or 'Jocelyn'})
 for r in d['reviews']:
  if not r.get('工作台ID') and str(r.get('复盘日期') or '')[:10]<'2026-10-15':continue
  out['reviews'].append({'id':r['record_id'],'title':r.get('复盘主题',''),'date':str(r.get('复盘日期') or '')[:10],'summary':r.get('数据表现总结') or '', 'next':r.get('优化方向') or '', 'window':r.get('观察口径') or ''})
 out['rules']=[{'name':r.get('规则名称',''),'text':r.get('规则内容',''),'confidence':first(r.get('置信度'))} for r in d['rules'] if str(r.get('首次沉淀日期') or '')[:10]>='2026-10-15']
 return out

def put(table,fields,rid=None):
 args=['--json',json.dumps(fields,ensure_ascii=False)]
 if rid:args+=['--record-id',rid]
 cli('+record-upsert',table,*args)
 # Read back; caller uses stable ID for deduplication if response is lost.
 fresh=rows(table);d=cache();d[table]=fresh;write('data/feishu_board.json',d)
 return next((r for r in fresh if (r['record_id']==rid if rid else r.get('工作台ID')==fields.get('工作台ID'))),None)

def check_version(table,body):
 r=one(table,body['id'])
 if stamp(r)!=body.get('version'):raise ValueError('这条记录已在飞书或另一页面修改。请保留当前文字，刷新后再合并。')
 return r

def date(v):return dt.date.fromisoformat(str(v)).isoformat()
def text(b,k,limit=30000):return str(b.get(k) or '').strip()[:limit]
def mutate(action,b):
 if action=='save':
  r=check_version('works',b);title=text(b,'title',200);body=text(b,'body')
  if not title:raise ValueError('标题不能为空')
  status=b.get('status','草稿')
  if status not in ['草稿','待发布','已发布']:raise ValueError('状态不正确')
  fields={'作品标题':title,'正文':body,'制作状态':status}
  if status=='已发布':
   day=date(b.get('date'))
   if day>now()[:10]:raise ValueError('实际发布日期不能在未来')
   fields['发布时间']=day+' 00:00:00'
  elif r.get('发布时间'):raise ValueError('已发布作品请在飞书核对状态，不在编辑器撤销发布')
  put('works',fields,b['id']);return {'ok':True}
 if action=='plan':
  check_version('topics',b);day=date(b.get('date'));minutes=int(b.get('minutes',45))
  if not 1<=minutes<=480:raise ValueError('时间预算须为1—480分钟')
  if day<now()[:10]:raise ValueError('请安排今天或以后的日期')
  put('topics',{'计划日期':day+' 00:00:00','预计分钟':minutes},b['id']);return {'ok':True}
 if action=='draft':
  topic=one('topics',text(b,'topic_id',100));fmt=b.get('format')
  if fmt not in ['短视频','图文笔记']:raise ValueError('请选择口播或图文')
  key='draft:'+topic['record_id']+':'+fmt
  exists=next((r for r in rows('works') if r.get('工作台ID')==key or (first(r.get('作品类型'))==fmt and any(x.get('id')==topic['record_id'] for x in r.get('关联选题') or []))),None)
  if exists:return {'ok':True,'id':exists['record_id']}
  r=put('works',{'工作台ID':key,'作品标题':topic.get('选题标题') or '新稿件','正文':'','平台':'小红书','作品类型':fmt,'制作状态':'草稿','账号':'Jocelyn','关联选题':[{'id':topic['record_id']}]})
  return {'ok':True,'id':r['record_id']}
 if action=='review':
  work=one('works',text(b,'work_id',100));day=date(b.get('date'));window=b.get('window')
  if day>now()[:10] or window not in ['24h','7d','累计']:raise ValueError('请核对日期和观察口径')
  metrics={}
  for k in ['观看','收藏','新增关注']:
   v=b.get(k)
   if v in ('',None):metrics[k]=None
   elif isinstance(v,bool) or not str(v).isdigit():raise ValueError('指标填非负整数，未知留空')
   else:metrics[k]=int(v)
  if all(v is None for v in metrics.values()):raise ValueError('至少填一项数据')
  summary='；'.join(k+'：'+('未知' if v is None else str(v)) for k,v in metrics.items())
  if metrics['观看'] and metrics['新增关注'] is not None:summary+='；观看转粉率：'+format(metrics['新增关注']/metrics['观看']*100,'.2f')+'%'
  key='review:'+work['record_id']+':'+day+':'+window
  old=next((r for r in rows('reviews') if r.get('工作台ID')==key),None)
  fields={'工作台ID':key,'复盘主题':work.get('作品标题') or '作品复盘','复盘日期':day+' 00:00:00','复盘类型':'单条复盘','观察口径':window,'数据表现总结':summary,'优化方向':text(b,'next',2000),'关联作品':[{'id':work['record_id']}]}
  put('reviews',fields,old['record_id'] if old else None);return {'ok':True}
 raise ValueError('未知操作')

def handle(h,method,path):
 if not path.startswith('/api/board'):return False
 try:
  if method=='GET' and path=='/api/board':h._send_json(view());return True
  if method!='POST':raise ValueError('不支持此操作')
  b=h._read_json()
  (BASE/'data').mkdir(exist_ok=True)
  with (BASE/'data/feishu_board.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   result=sync() if path=='/api/board/sync' else mutate(path.rsplit('/',1)[-1],b)
  h._send_json(result)
 except ValueError as e:h._send_json({'error':str(e)},409 if '修改' in str(e) else 400)
 except Exception:
  if path.endswith('/sync'):write('data/feishu_board_health.json',{'ok':False,'checked_at':now(),'error':'同步失败，请检查网络和飞书登录；保留上次快照'})
  h._send_json({'error':'飞书暂时未响应。输入仍保留；恢复连接后再试。'},503)
 return True

if __name__=='__main__':
 (BASE/'data').mkdir(exist_ok=True)
 with (BASE/'data/feishu_board.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  try:
   d=sync();print('Five-library sync OK:',d['synced_at'])
  except Exception:
   write('data/feishu_board_health.json',{'ok':False,'checked_at':now(),'error':'同步失败，保留上次快照'});raise
