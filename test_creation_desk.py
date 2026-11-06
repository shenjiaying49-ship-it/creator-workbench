import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import creation_desk as c
class Desk(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(c,'BASE',Path(self.tmp.name));self.p.start();(c.BASE/'data').mkdir()
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def test_rules_do_not_mix_forms(self):
  lib={'rules':[{'record_id':'v','规则名称':'口播风格skill','规则内容':'FULL VIDEO'},{'record_id':'g','规则名称':'小红书风格skill','规则内容':'FULL GRAPHIC'}]}
  self.assertEqual(c.route_rules(lib,'小红书','口播')[0]['record_id'],'v');self.assertEqual(c.route_rules(lib,'小红书','图文')[0]['record_id'],'g')
 def test_missing_rules_block(self):
  with self.assertRaises(ValueError):c.route_rules({'rules':[]},'抖音','口播')
 def test_no_generic_platform_fallback(self):
  with self.assertRaises(ValueError):c.route_rules({'rules':[]},'公众号','图文')
 def test_copy_detection(self):
  text='这是一句不该直接复制的其他作者独特经历。'*10
  self.assertTrue(any('相同' in e for e in c.issues({'title':'标题','body':text},[{'逐字稿/口播稿':text}],'小红书','图文')))
 def test_save_requires_version(self):
  record={'id':'r','day':'2026-11-06','platform':'小红书','body':'original'};c.write('data/daily_creations.json',{'2026-11-06|小红书':record})
  with self.assertRaises(ValueError):c.save({'day':'2026-11-06','platform':'小红书','version':'wrong','title':'x'})
  self.assertEqual(c.read('data/daily_creations.json',{})['2026-11-06|小红书']['body'],'original')
 def test_save_preserves_original_and_invalidates_review(self):
  r={'id':'r','day':'2026-11-06','platform':'小红书','body':'old'};c.write('data/daily_creations.json',{'2026-11-06|小红书':r});c.save({'day':r['day'],'platform':r['platform'],'version':c.digest(r),'title':'新标题','body':'new'})
  self.assertTrue(list((c.BASE/'data/creation-history').glob('*.json')));self.assertTrue(c.read('data/daily_creations.json',{})['2026-11-06|小红书']['edited'])
 def test_scheduled_priority_and_explicit_future(self):
  def topic(id,date):return {'id':id,'date':date,'title':'title','notes':'full notes','status':'待使用','account':'Jocelyn'}
  lib={'topics':[topic('today','2026-11-06'),topic('future','2026-11-09')],'examples':[]}
  self.assertEqual([s['id'] for s in c.candidates(lib,'2026-11-06')],['today']);self.assertIn('future',[s['id'] for s in c.candidates(lib,'2026-11-06','future')])
 def test_invalid_model_response(self):
  with self.assertRaises(ValueError):c.model_json(lambda _:('pretend success',None),'prompt')

class CodexImport(unittest.TestCase):
 def test_unknown_source_and_changed_snapshot_block(self):
  from unittest.mock import patch
  with patch.object(c,'libraries',return_value={}),patch.object(c.board,'cache',return_value={}):
   with self.assertRaisesRegex(ValueError,'已更新'):c.accept_codex({'day':'2026-11-06','form':'图文','snapshot_hash':'bad'})
 def test_quota_error_is_explicit(self):
  from unittest.mock import patch
  with patch.object(c,'write'):
   with self.assertRaisesRegex(RuntimeError,'余额不足'):c.model_json(lambda p:(None,'insufficient_organization_quota'),'p')

 def test_legacy_generation_cannot_bypass_rules(self):
  from types import SimpleNamespace
  from unittest.mock import Mock
  h=SimpleNamespace(_send_json=Mock());call=Mock()
  self.assertTrue(c.handle(h,'POST','/api/studio/generate',{},call))
  self.assertEqual(h._send_json.call_args.args[1],409);call.assert_not_called()

if __name__=='__main__':unittest.main()
