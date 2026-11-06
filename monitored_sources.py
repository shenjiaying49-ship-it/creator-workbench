"""Only collect the user's configured RSS sources; never send messages."""
import json,urllib.request,urllib.error,xml.etree.ElementTree as ET,hashlib,datetime as dt,email.utils,re,html
from pathlib import Path
import creation_desk as desk
BASE=Path(__file__).resolve().parent
def collect():
 config=json.loads((BASE/'config.json').read_text());path=config.get('creator',{}).get('monitor_sources_path')
 sources=json.loads(Path(path).read_text()) if path else []
 d=desk.read('data/monitored_feed.json',{'items':[],'sources':{}})
 for source in sources:
  if not source.get('enabled',True):continue
  name=source['name'];old=d['sources'].get(name,{})
  try:
   req=urllib.request.Request(source['url'],headers={'User-Agent':'CreatorWorkbench/1.0'})
   with urllib.request.urlopen(req,timeout=15) as resp:root=ET.fromstring(resp.read(3_000_000))
   ns={'a':'http://www.w3.org/2005/Atom'};entries=root.findall('.//item') or root.findall('a:entry',ns);items=[]
   for entry in entries[:15]:
    title=entry.findtext('title') or entry.findtext('a:title','',ns);url=entry.findtext('link') or (entry.find('a:link',ns).get('href','') if entry.find('a:link',ns) is not None else '')
    text=entry.findtext('description') or entry.findtext('a:content','',ns) or entry.findtext('a:summary','',ns)
    stamp=entry.findtext('pubDate') or entry.findtext('a:published','',ns) or entry.findtext('a:updated','',ns)
    try:date=dt.datetime.fromisoformat(stamp.replace('Z','+00:00')).isoformat()
    except ValueError:date=email.utils.parsedate_to_datetime(stamp).isoformat()
    if not title or not url.startswith(('http://','https://')):continue
    items.append({'id':'monitor:'+hashlib.sha256(url.encode()).hexdigest()[:20],'source':name,'title':title,'url':url,'date':date,'text':html.unescape(re.sub('<[^>]+>',' ',text)).strip(),'fetched_at':desk.board.now()})
   if not items:raise ValueError('RSS返回为空')
   d['items']=[i for i in d['items'] if i['source']!=name]+items;d['sources'][name]={'ok':True,'url':source['url'],'last_success':desk.board.now(),'count':len(items)}
  except Exception as e:
   reason='HTTP '+str(e.code) if isinstance(e,urllib.error.HTTPError) else type(e).__name__
   d['sources'][name]={**old,'ok':False,'url':source['url'],'error':reason+'；保留配置，未获取新素材','checked_at':desk.board.now()}
 d['checked_at']=desk.board.now();desk.write('data/monitored_feed.json',d);return d
if __name__=='__main__':print(json.dumps(collect()['sources'],ensure_ascii=False))
