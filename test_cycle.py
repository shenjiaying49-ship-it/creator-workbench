import unittest,tempfile,json,os,shutil
import growth,growth_cycle
class Handler:
 def __init__(self,body=None): self.body=body or {};self.code=200
 def _read_json(self):return self.body
 def _send_json(self,data,code=200):self.result=data;self.code=code
class CycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=self.tmp.name
  os.makedirs(self.base+'/data');os.makedirs(self.base+'/static')
  with open(self.base+'/static/wuku-data.json','w') as f:json.dump({'topics_list':[{'id':'t1','title':'test'}]},f)
 def tearDown(self):self.tmp.cleanup()
 def call(self,path,body=None,method='POST',llm=lambda p,c:('result',None)):
  h=Handler(body);growth.handle(h,method,'/api/growth'+path,self.base,llm,lambda:{});return h
 def post(self,path,body):
  return self.call(path,dict(body,version=growth.read(self.base)['version']))
 def test_read_old_compatibility(self):
  h=self.call('',method='GET');self.assertEqual(h.code,200);self.assertEqual(h.result['cycle']['capacity']['minutes'],180)
 def test_scores_and_conflict(self):
  self.assertEqual(self.post('/rating',{'topic_id':'t1','fit':5,'value':3,'ready':4}).code,200)
  self.assertEqual(self.call('/rating',{'version':0,'topic_id':'t1','fit':5,'value':3,'ready':4}).code,409)
  self.assertEqual(self.post('/rating',{'topic_id':'t1','fit':8,'value':3,'ready':4}).code,400)
 def test_publication_validation_and_duplicate(self):
  b={'title':'A','date':growth.today()};self.assertEqual(self.post('/publication',b).code,200);self.assertEqual(self.post('/publication',b).code,400)
  self.assertEqual(self.post('/publication',{'title':'B','date':'2099-01-01'}).code,400)
 def test_metrics_null_zero_replace(self):
  b={'title':'A','date':growth.today(),'window':'24h','views':0};self.assertEqual(self.post('/metric',b).code,200)
  self.post('/metric',dict(b,views=100,followers=2));rows=growth.read(self.base)['metrics'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['collects'],None)
 def test_plan_confirmation_collision(self):
  b={'title':'A','date':growth.today(),'minutes':60,'context':'budget'}
  self.post('/plan',b);self.post('/plan',dict(b,title='B'));plans=growth.read(self.base)['plans'];self.assertEqual(plans[0]['status'],'proposed')
  self.assertEqual(self.post('/status',{'id':plans[0]['id'],'status':'confirmed'}).code,200)
  self.assertEqual(self.post('/status',{'id':plans[1]['id'],'status':'confirmed'}).code,400)
 def test_experiment_and_ai_failure(self):
  self.post('/experiment',dict(title='A',hypothesis='H',variable='V',next='N'))
  self.assertEqual(growth.read(self.base)['experiments'][0]['status'],'待验证')
  h=self.call('/assist',{'stage':'初稿','topic':'A'},llm=lambda p,c:(None,'offline'));self.assertEqual(h.code,503)
 def test_missing_library(self):
  os.unlink(self.base+'/static/wuku-data.json');self.assertIn('error',growth_cycle.view(self.base,{}))
if __name__=='__main__':unittest.main()
