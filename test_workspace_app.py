import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import workspace_app as w
class Workspace(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(w,'BASE',Path(self.tmp.name));self.p.start();(w.BASE/'data').mkdir()
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def test_monday_across_year(self):self.assertEqual(w.monday('2027-01-01'),'2026-12-28')
 def test_version_conflict_preserves_tasks(self):
  w.mutate('task',{'version':0,'day':'2026-11-09','title':'录口播','minutes':30})
  with self.assertRaises(ValueError):w.mutate('task',{'version':0,'day':'2026-11-09','title':'other','minutes':20})
  self.assertEqual(len(w.local()['tasks']),1)
 def test_done_not_publish(self):
  w.mutate('done',{'version':0,'id':'daily:2026-11-06','done':True});self.assertTrue(w.local()['done']['daily:2026-11-06']);self.assertNotIn('publications',w.local())
 def test_review_dedup_and_unknown(self):
  b={'version':0,'title':'one','date':'2026-11-01','window':'24h','views':'100','followers':'','next':'改开头'}
  w.mutate('review',b);b.update(version=1,views='200');w.mutate('review',b)
  self.assertEqual(len(w.local()['reviews']),1);self.assertIsNone(w.local()['reviews'][0]['followers']);self.assertEqual(w.local()['reviews'][0]['views'],200)
 def test_platforms_separate(self):
  b={'version':0,'title':'one','date':'2026-11-01','window':'24h','views':'100','platform':'小红书'};w.mutate('review',b);b.update(version=1,platform='抖音');w.mutate('review',b);self.assertEqual(len(w.local()['reviews']),2)
 def test_week_preserves_confirmed_budget(self):
  cloud={'topics':[{'id':'t','title':'Coffee','date':'2026-11-09','account':'Jocelyn','minutes':45}], 'reviews':[],'works':[],'synced_at':''}
  with patch.object(w.board,'view',return_value=cloud),patch.object(w.growth,'read',return_value={'version':0}):d=w.view('2026-11-12')
  self.assertEqual(len(d['days']),7);fixed=[t for t in d['tasks'] if t['kind']=='已排创作'];self.assertEqual(fixed[0]['minutes'],45);self.assertEqual(len(fixed),1)

class HistoricalMetrics(unittest.TestCase):
 def test_legacy_account_inherited_from_post(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(w,'BASE',Path(folder)):
   (w.BASE/'data').mkdir();w.write('data/posts.json',[{'id':'old','title':'真实旧稿','account':'Jocelyn'},{'id':'other','account':'Yuki.AI'}]);w.write('data/analytics.json',[{'post_id':'old','views':0},{'post_id':'other','views':500}])
   with patch.object(w.board,'view',return_value={'topics':[],'reviews':[],'works':[],'synced_at':''}),patch.object(w.growth,'read',return_value={'version':0}):d=w.view('2026-11-06')
   self.assertEqual(len(d['legacy_metrics']),1);self.assertEqual(d['legacy_metrics'][0]['title'],'真实旧稿')

 def test_existing_work_edits_stay_local(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(w,'BASE',Path(folder)):
   (w.BASE/'data').mkdir();work={'id':'work','title':'旧标题','body':'原飞书正文'}
   with patch.object(w.board,'view',return_value={'works':[work]}),patch.object(w.desk,'write'):
    v=w.desk.digest(work);w.mutate('save-work',{'id':'work','version':v,'title':'修改标题','body':'本地修改'})
    self.assertEqual(w.local()['edits']['work']['body'],'本地修改');self.assertEqual(work['body'],'原飞书正文')
    with self.assertRaises(ValueError):w.mutate('save-work',{'id':'work','version':v,'title':'不能覆盖','body':'stale'})

if __name__=='__main__':unittest.main()
