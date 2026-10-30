"""Gmail HTTPS API sender. Requests only gmail.send; never uses SMTP or reads inboxes."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from util import read_json, write_json

SCOPE='https://www.googleapis.com/auth/gmail.send'
class GmailError(ValueError): pass

class GmailSender:
    def __init__(self, folder):
        self.path=os.path.join(folder,'gmail-sender.json'); self.lock=threading.RLock()
    def credentials(self): return read_json(self.path,{}) or {}
    def ready(self): return bool(self.credentials().get('refresh_token'))
    def status(self):
        c=self.credentials()
        return {'configured':bool(c.get('client_id')),'connected':bool(c.get('refresh_token')),'sender':c.get('sender','')}
    def _save(self,c): write_json(self.path,c,private=True)
    def begin(self,data,redirect):
        from accounts import email_address
        client=str(data.get('client_id') or '').strip(); secret=str(data.get('client_secret') or '').strip()
        sender=email_address(data.get('sender'))
        if not client.endswith('.apps.googleusercontent.com') or not secret: raise GmailError('Enter the Google OAuth web client ID and secret.')
        state=secrets.token_urlsafe(32); verifier=secrets.token_urlsafe(48)
        c={'client_id':client,'client_secret':secret,'sender':sender,'redirect':redirect,'state':state,'verifier':verifier,'state_expires':time.time()+600}
        self._save(c)
        params={'client_id':client,'redirect_uri':redirect,'response_type':'code','scope':SCOPE,'access_type':'offline','prompt':'consent','state':state,'login_hint':sender,'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode(),'code_challenge_method':'S256'}
        return 'https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode(params),state
    def _post(self,url,body,headers=None):
        req=urllib.request.Request(url,data=body,headers=headers or {},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
        except (urllib.error.URLError,ValueError): raise GmailError('Google could not complete this request. Check Gmail API access and reconnect.') from None
    def finish(self,code,state,browser_state):
        with self.lock:
            c=self.credentials()
            if not code or not state or not hmac.compare_digest(str(state),str(c.get('state',''))) or not hmac.compare_digest(str(state),str(browser_state or '')) or c.get('state_expires',0)<time.time(): raise GmailError('This Google authorization is invalid or expired. Start again.')
            # Consume state before network exchange to prevent replay.
            c.pop('state',None); self._save(c)
            b=urllib.parse.urlencode({'client_id':c['client_id'],'client_secret':c['client_secret'],'code':code,'code_verifier':c['verifier'],'redirect_uri':c['redirect'],'grant_type':'authorization_code'}).encode()
            doc=self._post('https://oauth2.googleapis.com/token',b,{'Content-Type':'application/x-www-form-urlencoded'})
            if SCOPE not in doc.get('scope','').split() or not doc.get('refresh_token'): raise GmailError('Google did not grant offline Gmail sending access. Try Connect Gmail again.')
            for k in ('verifier','state_expires'):c.pop(k,None)
            c.update(refresh_token=doc['refresh_token'],access_token=doc.get('access_token',''),expires=time.time()+doc.get('expires_in',3600)-60);self._save(c)
    def send_code(self,to,code,purpose):
        with self.lock:
            c=self.credentials()
            if not c.get('refresh_token'):raise GmailError('Connect Gmail first.')
            if c.get('expires',0)<time.time():
                b=urllib.parse.urlencode({'client_id':c['client_id'],'client_secret':c['client_secret'],'refresh_token':c['refresh_token'],'grant_type':'refresh_token'}).encode()
                doc=self._post('https://oauth2.googleapis.com/token',b,{'Content-Type':'application/x-www-form-urlencoded'})
                if not doc.get('access_token'):raise GmailError('Reconnect Gmail.')
                c.update(access_token=doc['access_token'],expires=time.time()+doc.get('expires_in',3600)-60);self._save(c)
            msg=EmailMessage();msg['From']=c['sender'];msg['To']=to
            action='verify your email' if purpose=='signup' else 'reset your password'
            msg['Subject']='IndianTrader: '+action
            msg.set_content('Your IndianTrader code is '+code+'.\n\nUse it to '+action+'. It expires in 5 minutes and works once.\nIf you did not request it, ignore this email.\n\nIndianTrader — paper trading only')
            body=json.dumps({'raw':base64.urlsafe_b64encode(msg.as_bytes()).decode()}).encode()
            self._post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',body,{'Authorization':'Bearer '+c['access_token'],'Content-Type':'application/json'})
