import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from accounts import Accounts,AuthError,password_ok
from gmail_sender import GmailSender,GmailError,SCOPE
from user_engines import UserEngines
from util import write_json,read_json

class Mailbox:
    def __init__(self):self.messages=[];self.connected=True
    def ready(self):return self.connected
    def send_code(self,email,code,purpose):self.messages.append((email,code,purpose))

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.clock=[1000.]
        self.mail=Mailbox();self.a=Accounts(self.tmp.name,self.mail,lambda:self.clock[0])
    def register(self,email='owner@example.com',name='Owner'):
        r=self.a.request_code('signup',{'email':email,'password':'a good password 123','name':name},'127.0.0.1',self.a.setup)
        result=self.a.verify_code(r['challenge'],self.mail.messages[-1][1]);return result
    def test_signup_requires_email_code_and_owner_setup_authorization(self):
        with self.assertRaises(AuthError):self.a.request_code('signup',{'email':'a@example.com','password':'a good password 123','name':'A'},'ip')
        self.clock[0]+=61;r=self.a.request_code('signup',{'email':'a@example.com','password':'a good password 123','name':'A'},'ip',self.a.setup)
        self.assertFalse(self.a.has_users());code=self.mail.messages[-1][1]
        self.a.verify_code(r['challenge'],code);self.assertTrue(self.a.has_users());self.assertFalse(self.a.setup_ok(self.a.setup))
        with self.assertRaises(AuthError):self.a.verify_code(r['challenge'],code)
        with self.a.db() as c:
            stored=c.execute('SELECT password FROM users').fetchone()[0]
        self.assertNotIn('a good password',stored);self.assertTrue(password_ok('a good password 123',stored))
    def test_code_expiry_attempt_limit_and_resend(self):
        r=self.a.request_code('signup',{'email':'a@example.com','password':'a good password 123','name':'A'},'ip',self.a.setup)
        code=self.mail.messages[-1][1]
        for _ in range(5):
            with self.assertRaises(AuthError):self.a.verify_code(r['challenge'],'not-a-code')
        with self.assertRaises(AuthError):self.a.verify_code(r['challenge'],code)
        self.clock[0]+=61
        r2=self.a.request_code('signup',{'email':'a@example.com','password':'a good password 123','name':'A'},'ip',self.a.setup)
        with self.assertRaises(AuthError):self.a.verify_code(r['challenge'],code)
        self.clock[0]+=301
        with self.assertRaises(AuthError):self.a.verify_code(r2['challenge'],self.mail.messages[-1][1])
    def test_same_login_both_modes_logout_and_reset_revokes_sessions(self):
        self.register();tokens=[]
        for mode in ('demo','paper'):
            token=self.a.login({'email':'OWNER@example.com','password':'a good password 123','mode':mode},'ip');tokens.append(token)
            self.assertEqual(self.a.session(token)['mode'],mode)
        self.a.logout(tokens[0]);self.assertIsNone(self.a.session(tokens[0]))
        self.clock[0]+=61
        r=self.a.request_code('reset',{'email':'owner@example.com'},'ip')
        self.a.verify_code(r['challenge'],self.mail.messages[-1][1],'a new password 456')
        self.assertIsNone(self.a.session(tokens[1]))
        with self.assertRaises(AuthError):self.a.login({'email':'owner@example.com','password':'a good password 123','mode':'demo'},'ip')
        self.assertIsNotNone(self.a.session(self.a.login({'email':'owner@example.com','password':'a new password 456','mode':'paper'},'ip')))
    def test_unknown_recovery_does_not_send_email_or_allow_reset(self):
        self.register();count=len(self.mail.messages)
        r=self.a.request_code('reset',{'email':'unknown@example.com'},'ip')
        self.assertEqual(count,len(self.mail.messages))
        with self.assertRaises(AuthError):self.a.verify_code(r['challenge'],'123456','another password 123')
    def test_delivery_failure_never_creates_user(self):
        self.mail.send_code=lambda *args: (_ for _ in ()).throw(ValueError('unavailable'))
        with self.assertRaises(AuthError):self.a.request_code('signup',{'email':'a@example.com','password':'a good password 123','name':'A'},'ip',self.a.setup)
        self.assertFalse(self.a.has_users())
        with self.a.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM challenges').fetchone()[0],0)
    def test_account_and_mode_isolation_preserves_legacy_owner_data(self):
        write_json(os.path.join(self.tmp.name,'settings.json'),{'budget':5000,'source':'demo','owner':'Legacy'})
        write_json(os.path.join(self.tmp.name,'demo-account.json'),{'capital':5000,'cash':4567,'positions':[],'orders':[],'trades':[],'events':[],'seq':0})
        write_json(os.path.join(self.tmp.name,'account.json'),{'capital':7000,'cash':6789,'positions':[],'orders':[],'trades':[],'events':[],'seq':0})
        self.register();self.clock[0]+=61;self.register('second@example.com','Second')
        users=self.a.users();owner=next(u for u in users if u['role']=='owner');other=next(u for u in users if u['role']=='user')
        m=UserEngines(self.tmp.name,self.a)
        demo=m.get(dict(owner,mode='demo'));paper=m.get(dict(owner,mode='paper'));second=m.get(dict(other,mode='demo'))
        self.assertEqual(demo.account()['cash'],4567);self.assertEqual(paper.account()['cash'],6789)
        self.assertEqual(second.account()['cash'],2000)
        second.reset(3333);self.assertEqual(demo.account()['cash'],4567)
        self.assertNotEqual(paper.settings_file,demo.settings_file)
        self.assertEqual(read_json(os.path.join(self.tmp.name,'demo-account.json'))['cash'],4567)
    def test_send_cooldown(self):
        data={'email':'a@example.com','password':'a good password 123','name':'A'}
        self.a.request_code('signup',data,'ip',self.a.setup)
        with self.assertRaises(AuthError):self.a.request_code('signup',data,'ip',self.a.setup)

class GmailTests(unittest.TestCase):
    def test_google_state_binding_and_minimal_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            m=GmailSender(folder);url,state=m.begin({'sender':'sender@example.com','client_id':'test.apps.googleusercontent.com','client_secret':'not-a-real-secret'},'http://localhost:8765/gmail/callback')
            self.assertIn('code_challenge_method=S256',url);self.assertIn('gmail.send',url);self.assertNotIn('gmail.readonly',url)
            with self.assertRaises(GmailError):m.finish('code',state,'wrong-browser-state')
            with patch.object(m,'_post',return_value={'access_token':'fake-access','refresh_token':'fake-refresh','expires_in':3600,'scope':SCOPE}):m.finish('code',state,state)
            self.assertTrue(m.ready())
            with self.assertRaises(GmailError):m.finish('code',state,state)
            sent=[]
            with patch.object(m,'_post',side_effect=lambda *args:sent.append(args) or {'id':'fake'}):m.send_code('user@example.com','123456','signup')
            self.assertEqual(sent[0][0],'https://gmail.googleapis.com/gmail/v1/users/me/messages/send')
            self.assertNotIn('refresh_token',str(m.status()))

if __name__=='__main__':unittest.main()
