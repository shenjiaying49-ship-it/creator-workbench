import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import feishu_board as b
class BoardTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.orig=b.BASE;b.BASE=Path(self.tmp.name);b.write('config.json',{'wuku':{'base_token':'test'}})
 def tearDown(self):b.BASE=self.orig;self.tmp.cleanup()
 def test_cache_empty(self):self.assertEqual(b.view()['topics'],[])
 def test_failed_sync_keeps_cache(self):
  b.write('data/feishu_board.json',dict(b.cache(),synced_at='old'))
  with patch.object(b,'rows',side_effect=RuntimeError('offline')):
   with self.assertRaises(RuntimeError):b.sync()
  self.assertEqual(b.cache()['synced_at'],'old')
 def test_conflict_never_writes(self):
  with patch.object(b,'one',return_value={'record_id':'r','正文':'new'}),patch.object(b,'put') as put:
   with self.assertRaises(ValueError):b.mutate('save',{'id':'r','version':'stale','title':'t','body':'old'})
   put.assert_not_called()
 def test_save_confirmed_content(self):
  r={'record_id':'r','正文':'old'}
  with patch.object(b,'one',return_value=r),patch.object(b,'put') as put:
   b.mutate('save',{'id':'r','version':b.stamp(r),'title':'t','body':'<script> literal','status':'草稿'})
   self.assertEqual(put.call_args.args[1]['正文'],'<script> literal')
 def test_draft_idempotency(self):
  with patch.object(b,'one',return_value={'record_id':'t','选题标题':'topic'}),patch.object(b,'rows',return_value=[{'record_id':'w','工作台ID':'draft:t:短视频'}]),patch.object(b,'put') as put:
   self.assertEqual(b.mutate('draft',{'topic_id':'t','format':'短视频'})['id'],'w');put.assert_not_called()
 def test_review_zero_missing(self):
  with patch.object(b,'one',return_value={'record_id':'w','作品标题':'t'}),patch.object(b,'rows',return_value=[]),patch.object(b,'put') as put:
   b.mutate('review',{'work_id':'w','date':'2026-11-06','window':'24h','观看':'0','收藏':'','新增关注':'0'})
   summary=put.call_args.args[1]['数据表现总结'];self.assertIn('收藏：未知',summary);self.assertNotIn('转粉率',summary)
 def test_review_idempotent_key(self):
  key='review:w:2026-11-06:24h'
  with patch.object(b,'one',return_value={'record_id':'w','作品标题':'t'}),patch.object(b,'rows',return_value=[{'record_id':'r','工作台ID':key}]),patch.object(b,'put') as put:
   b.mutate('review',{'work_id':'w','date':'2026-11-06','window':'24h','观看':'1000','新增关注':'20'});self.assertEqual(put.call_args.args[2],'r');self.assertIn('2.00%',put.call_args.args[1]['数据表现总结'])
 def test_draft_not_published(self):
  d=b.cache();d['works']=[{'record_id':'r','工作台ID':'post:x','作品标题':'x','制作状态':['草稿'],'关联选题':[{'id':'t'}]}]
  self.assertEqual(b.view(d)['works'][0]['status'],'草稿');self.assertEqual(b.view(d)['works'][0]['topics'],['t'])
if __name__=='__main__':unittest.main()
