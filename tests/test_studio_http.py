"""Actual local HTTP integration tests; needs permission to bind a loopback port."""
import json
import os
import stat
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from studio.server import Server, Store

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory()
        cls.store=Store(cls.directory.name)
        cls.server=Server(('127.0.0.1',0),cls.store)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)
        cls.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.store.close()
        cls.thread.join(); cls.directory.cleanup()

    def request(self,path,data=None,headers=None):
        request=urllib.request.Request(self.url+path,None if data is None else json.dumps(data).encode(),headers or {})
        return self.opener.open(request,timeout=5)

    def post(self,path,data):
        with self.request(path,data,{'X-Studio-Token':self.server.token,'Content-Type':'application/json','Origin':self.url}) as r:
            return json.loads(r.read())

    def test_bootstrap_and_static_assets(self):
        with self.request('/api/bootstrap') as r:
            data=json.loads(r.read())
            self.assertTrue(data['native']); self.assertEqual(len(data['templates']),5)
            self.assertTrue(any(t['id']=='chat-model-playground' for t in data['templates']))
            self.assertEqual([p['id'] for p in data['providers']],['openrouter'])
        for file in ['/', '/app.js', '/style.css']:
            with self.request(file) as r:
                self.assertGreater(len(r.read()),100)
                self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])

    def test_cross_origin_and_missing_token_rejected(self):
        for headers in [{}, {'X-Studio-Token':self.server.token,'Origin':'https://evil.invalid'}]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/runs',{},headers)
            self.assertEqual(caught.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/bootstrap',headers={'Host':'evil.invalid'})
        self.assertEqual(caught.exception.code,403)

    def test_save_run_and_fetch(self):
        workflow=json.loads((ROOT/'studio/templates/03-tools.json').read_text())
        self.assertTrue(self.post('/api/workflows',{'workflow':workflow})['saved'])
        ident=self.post('/api/runs',{'workflow':workflow,'inputs':workflow['inputs']})['id']
        result=None
        for _ in range(100):
            with self.request('/api/runs/'+ident) as response: result=json.loads(response.read())
            if result['status']=='completed': break
            time.sleep(.02)
        self.assertEqual(result['status'],'completed')
        self.assertIn('Text statistics:',result['state']['output'])
        with self.request('/api/workflows') as response: self.assertEqual(len(json.loads(response.read())),1)

    def test_invalid_graph_returns_actionable_error(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post('/api/runs',{'workflow':{},'inputs':{}})
        self.assertEqual(caught.exception.code,400)
        self.assertIn('error',json.loads(caught.exception.read()))

    def test_model_environment_settings_are_write_only_and_loaded(self):
        name='GRAPHCORE_TEST_SECRET'
        previous=os.environ.pop(name,None)
        secret='local test secret # with a "quote"'
        try:
            saved=self.post('/api/settings/environment',{'values':{name:secret},'remove':[]})
            item=next(v for v in saved['variables'] if v['name']==name)
            self.assertTrue(item['stored']); self.assertTrue(item['configured'])
            with self.request('/api/settings/environment') as response:
                body=response.read().decode()
            self.assertNotIn(secret,body)
            self.assertEqual(os.environ[name],secret)
            if os.name=='posix':
                self.assertEqual(stat.S_IMODE((Path(self.directory.name)/'.env').stat().st_mode),0o600)
            from studio.server import load_dotenv, read_dotenv
            self.assertEqual(read_dotenv(Path(self.directory.name)/'.env')[name],secret)
            os.environ.pop(name)
            self.assertEqual(load_dotenv(Path(self.directory.name)/'.env',override=True)[name],secret)
            self.post('/api/settings/environment',{'values':{},'remove':[name]})
            self.assertNotIn(name,os.environ)
        finally:
            os.environ.pop(name,None)
            if previous is not None: os.environ[name]=previous

if __name__=='__main__': unittest.main()
