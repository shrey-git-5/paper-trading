"""HTTP contract tests using only disposable users and a fake mail sender."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import server
from accounts import Accounts
from engine import Engine
from user_engines import UserEngines

class FakeMail:
    def __init__(self):self.codes=[]
    def ready(self):return True
    def status(self):return {'connected':True,'configured':True,'sender':'sender@example.com'}
    def send_code(self,email,code,purpose):self.codes.append(code)

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.mail=FakeMail();self.a=Accounts(self.tmp.name,self.mail)
        self.srv=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.port=self.srv.server_address[1]
        self.patch=patch.multiple(server,ACCOUNTS=self.a,MAILER=self.mail,ENGINES=UserEngines(self.tmp.name,self.a),LEGACY_ENGINE=Engine(data_dir=self.tmp.name));self.patch.start();self.addCleanup(self.patch.stop)
        self.pc=patch.object(server.config,'PORT',self.port);self.pc.start();self.addCleanup(self.pc.stop)
        self.thread=threading.Thread(target=self.srv.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
    def stop(self):self.srv.shutdown();self.srv.server_close();self.thread.join()
    def req(self,path,body=None,cookie='',headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        h={'Content-Type':'application/json'};h.update(headers or {})
        if cookie:h['Cookie']=cookie
        conn.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),h)
        r=conn.getresponse();raw=r.read();ctype=r.getheader('Content-Type','');result=json.loads(raw) if 'json' in ctype else raw.decode();out=(r.status,result,r.getheader('Set-Cookie'));conn.close();return out
    def create_owner(self):
        code,r,_=self.req('/api/auth/register',{'email':'owner@example.com','name':'Owner','password':'a good password 123'},headers={'X-Setup-Token':self.a.setup});self.assertEqual(code,200)
        self.assertFalse(self.a.has_users())
        code,_,_=self.req('/api/auth/verify',{'challenge':r['challenge'],'code':self.mail.codes[-1]});self.assertEqual(code,200)
    def test_signup_login_both_modes_and_logout(self):
        self.assertEqual(self.req('/api/state')[0],401)
        self.assertEqual(self.req('/api/gmail/connect',{})[0],403)
        self.assertEqual(self.req('/')[0],200)
        self.create_owner()
        for mode in ('demo','paper'):
            code,_,cookie=self.req('/api/auth/login',{'email':'owner@example.com','password':'a good password 123','mode':mode});self.assertEqual(code,200)
            self.assertIn('HttpOnly',cookie)
            code,state,_=self.req('/api/state',cookie=cookie);self.assertEqual(code,200)
            self.assertEqual(state['identity']['mode'],mode);self.assertEqual(state['market']['demo'],mode=='demo')
            if mode=='paper':self.assertFalse(state['source']['ready'])
            self.assertEqual(self.req('/api/auth/logout',{},cookie=cookie)[0],200)
            self.assertEqual(self.req('/api/state',cookie=cookie)[0],401)
    def test_cross_origin_and_mode_switch_validation(self):
        self.assertEqual(self.req('/api/auth/login',{},headers={'Origin':'https://other.example'})[0],403)
        self.create_owner()
        _,_,cookie=self.req('/api/auth/login',{'email':'owner@example.com','password':'a good password 123','mode':'demo'})
        self.assertEqual(self.req('/api/settings',{'source':'upstox'},cookie=cookie)[0],400)
        self.assertEqual(self.req('/api/auth/mode',{'mode':'unknown'},cookie=cookie)[0],400)
        self.assertEqual(self.req('/api/auth/mode',{'mode':'paper'},cookie=cookie)[0],200)
        self.assertEqual(self.req('/api/state',cookie=cookie)[1]['identity']['mode'],'paper')
        # A Demo tab remains in Demo while the same browser also has a Paper tab.
        self.assertEqual(self.req('/api/state',cookie=cookie,headers={'X-Trade-Mode':'demo'})[1]['identity']['mode'],'demo')
        self.assertEqual(self.req('/api/state',cookie=cookie,headers={'X-Trade-Mode':'paper'})[1]['identity']['mode'],'paper')

if __name__=='__main__':unittest.main()
