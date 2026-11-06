import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import material_pipeline as m
class Pipeline(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=patch.object(m,'BASE',Path(self.tmp.name));self.base.start()
 def tearDown(self):self.base.stop();self.tmp.cleanup()
 def row(self,source,url='https://example.com/item'):return m.item(source,'Real item',url,'2026-11-06T00:00:00Z','abstract','5 points')
 def test_source_failure_keeps_last_success(self):
  with patch.object(m,'fetch_hn',return_value=[self.row('Hacker News')]),patch.object(m,'fetch_github',return_value=[self.row('GitHub','https://github.com/a/b')]):first=m.collect()
  with patch.object(m,'fetch_hn',side_effect=TimeoutError),patch.object(m,'fetch_github',return_value=[]):last=m.collect()
  self.assertEqual(first['items'],last['items']);self.assertFalse(last['sources']['Hacker News']['ok']);self.assertEqual(first['sources']['GitHub']['last_success'],last['sources']['GitHub']['last_success'])
 def test_idempotent_collection(self):
  with patch.object(m,'fetch_hn',return_value=[self.row('Hacker News')]*2),patch.object(m,'fetch_github',return_value=[]):m.collect();self.assertEqual(len(m.collect()['items']),1)
 def test_independent_sources(self):
  with patch.object(m,'fetch_hn',side_effect=TimeoutError),patch.object(m,'fetch_github',return_value=[self.row('GitHub')]):d=m.collect()
  self.assertEqual(len(d['items']),1);self.assertTrue(d['sources']['GitHub']['ok'])
 def test_safe_links(self):self.assertEqual(m.safe_url('javascript:alert(1)'),'')
 def test_stale_not_reported_as_fresh(self):
  (m.BASE/'data').mkdir();m.write({'items':[],'sources':{'GitHub':{'ok':True,'last_success':'2020-01-01T00:00:00+00:00'}}});self.assertTrue(m.view()['sources']['GitHub']['stale'])

class Adoption(unittest.TestCase):
 def test_repeat_adoption_does_not_write(self):
  import types,sys
  with tempfile.TemporaryDirectory() as folder:
   base=Path(folder);(base/'data').mkdir()
   candidate=m.item('GitHub','a/b','https://github.com/a/b','2026-11-06','description','100 stars')
   fake=types.SimpleNamespace(BASE=base,rows=lambda _: [{'工作台ID':'material:'+candidate['id'],'record_id':'existing'}],put=lambda *a: self.fail('duplicate write'))
   with patch.dict(sys.modules,{'feishu_board':fake}),patch.object(m,'read',return_value={'items':[candidate]}):
    self.assertEqual(m.adopt({'id':candidate['id']})['id'],'existing')
 def test_adoption_preserves_source(self):
  import types,sys
  from unittest.mock import Mock
  with tempfile.TemporaryDirectory() as folder:
   base=Path(folder);(base/'data').mkdir();put=Mock(return_value={'record_id':'new'})
   candidate=m.item('GitHub','a/b','https://github.com/a/b','2026-11-06','description','100 stars')
   fake=types.SimpleNamespace(BASE=base,rows=lambda _:[],put=put)
   with patch.dict(sys.modules,{'feishu_board':fake}),patch.object(m,'read',return_value={'items':[candidate]}):m.adopt({'id':candidate['id']})
   fields=put.call_args.args[1];self.assertIn(candidate['url'],fields['生产说明']);self.assertEqual(fields['状态'],'待使用');self.assertNotIn('计划日期',fields)

if __name__=='__main__':unittest.main()
