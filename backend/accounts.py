"""Local SQLite identities. No SMTP, cloud database, or plaintext passwords/OTP storage."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from util import read_json, write_json

class AuthError(ValueError): pass

def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise AuthError('Use a password between 12 and 128 characters.')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return salt + ':' + digest

def password_ok(password, stored):
    try:
        salt, digest = stored.split(':')
        actual = hashlib.pbkdf2_hmac('sha256', str(password).encode(), bytes.fromhex(salt), 600000).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError): return False

def email_address(value):
    value = str(value or '').strip()
    if len(value) > 254 or not re.fullmatch(r'[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+', value):
        raise AuthError('Enter a valid email address.')
    return value.casefold()

def mode_name(value):
    if value not in ('demo', 'paper'): raise AuthError('Choose Demo or Paper Trading.')
    return value

class Accounts:
    def __init__(self, folder, mailer, now=time.time):
        self.folder, self.mailer, self.now = folder, mailer, now
        self.lock = threading.RLock()
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, 'users.sqlite3')
        key_file = os.path.join(folder, 'auth-key.json')
        key = read_json(key_file)
        if not key:
            key = {'key': secrets.token_hex(32), 'setup': secrets.token_urlsafe(32)}
            write_json(key_file, key, private=True)
        self.key, self.setup = bytes.fromhex(key['key']), key['setup']
        self.dummy = password_hash(secrets.token_urlsafe(24))
        fd=os.open(self.path,os.O_CREAT|os.O_WRONLY,0o600);os.close(fd)
        with self.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,mode TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY,email TEXT NOT NULL,purpose TEXT NOT NULL,digest TEXT NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS limits(bucket TEXT NOT NULL,at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS limits_bucket ON limits(bucket,at);
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def digest(self, value): return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()
    def has_users(self):
        with self.db() as c: return bool(c.execute('SELECT 1 FROM users LIMIT 1').fetchone())
    def setup_ok(self, value): return not self.has_users() and hmac.compare_digest(str(value or ''), self.setup)
    def users(self):
        with self.db() as c: return [dict(r) for r in c.execute('SELECT id,name,email,role FROM users')]

    def rate(self, bucket, maximum, seconds):
        with self.lock, self.db() as c:
            now = self.now(); bucket = self.digest(bucket)
            c.execute('DELETE FROM limits WHERE at < ?', (now-86400,))
            if c.execute('SELECT count(*) FROM limits WHERE bucket=? AND at>?', (bucket, now-seconds)).fetchone()[0] >= maximum:
                raise AuthError('Too many attempts. Please wait and try again.')
            c.execute('INSERT INTO limits VALUES(?,?)', (bucket, now))

    def request_code(self, purpose, data, ip, setup_token=''):
        if purpose not in ('signup','reset'): raise AuthError('Invalid request.')
        email = email_address(data.get('email'))
        self.rate('send-ip:'+ip, 20, 3600)
        self.rate('send:'+email, 1, 60)
        self.rate('send-hour:'+email, 5, 3600)
        payload = {}
        with self.db() as c: existing = c.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        if purpose == 'signup':
            name = str(data.get('name') or '').strip()
            if not 1 <= len(name) <= 80: raise AuthError('Enter your name (up to 80 characters).')
            owner = not self.has_users()
            if owner and not self.setup_ok(setup_token): raise AuthError('Use Start IndianTrader.command to set up the first account on this Mac.')
            payload = {'name': name, 'password': password_hash(data.get('password')), 'owner': owner}
        if not self.mailer.ready(): raise AuthError('The owner must connect Gmail before verification emails can be sent. Open Gmail setup.')
        ident = secrets.token_urlsafe(24); code = '%06d' % secrets.randbelow(1000000)
        should_send = (purpose == 'signup' and not existing) or (purpose == 'reset' and bool(existing))
        if existing and purpose == 'reset': payload = {'user_id': existing['id']}
        # Dummy challenges have the same shape but can never verify.
        if not should_send: payload = {'dummy': True}
        with self.lock, self.db() as c:
            c.execute('DELETE FROM challenges WHERE expires<?', (self.now(),))
            c.execute('DELETE FROM challenges WHERE email=? AND purpose=?', (email,purpose))
            c.execute('INSERT INTO challenges VALUES(?,?,?,?,?,?,?)', (ident,email,purpose,self.digest(ident+code),self.now()+300,0,json.dumps(payload)))
        if should_send:
            try: self.mailer.send_code(email, code, purpose)
            except Exception:
                with self.db() as c: c.execute('DELETE FROM challenges WHERE id=?', (ident,))
                raise AuthError('Gmail could not send the code. Ask the owner to reconnect Gmail, then try again.') from None
        return {'challenge': ident, 'message': 'If this email is eligible, a code has been sent. It expires in 5 minutes.'}

    def verify_code(self, ident, code, new_password=None):
        # Validate new password before consuming the recovery code.
        replacement = password_hash(new_password) if new_password is not None else None
        with self.lock, self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            r = c.execute('SELECT * FROM challenges WHERE id=?', (str(ident),)).fetchone()
            if not r or r['expires'] < self.now() or r['attempts'] >= 5:
                raise AuthError('This code is invalid or expired. Request a new one.')
            p = json.loads(r['payload'])
            if p.get('dummy') or not hmac.compare_digest(r['digest'],self.digest(str(ident)+str(code))):
                c.execute('UPDATE challenges SET attempts=attempts+1 WHERE id=?', (ident,)); c.commit()
                raise AuthError('This code is invalid or expired. Request a new one.')
            if r['purpose'] == 'signup':
                if p.get('owner') and c.execute('SELECT 1 FROM users LIMIT 1').fetchone(): raise AuthError('Setup is already complete. Register again.')
                if c.execute('SELECT 1 FROM users WHERE email=?',(r['email'],)).fetchone(): raise AuthError('Use the login screen for this account.')
                uid = uuid.uuid4().hex
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(uid,r['email'],p['name'],p['password'],'owner' if p.get('owner') else 'user',self.now()))
            else:
                if not replacement: raise AuthError('Enter a new password.')
                uid = p['user_id']
                c.execute('UPDATE users SET password=? WHERE id=?',(replacement,uid))
                c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            c.execute('DELETE FROM challenges WHERE email=?',(r['email'],))
            return {'ok':True,'owner':bool(p.get('owner')),'user_id':uid}

    def login(self, data, ip):
        mode = mode_name(data.get('mode'))
        email = email_address(data.get('email'))
        self.rate('login-ip:'+ip,30,900); self.rate('login:'+email,10,900)
        password = data.get('password')
        if not isinstance(password,str) or len(password)>128: raise AuthError('Email or password is incorrect.')
        with self.db() as c: r=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        good = password_ok(password,r['password'] if r else self.dummy)
        if not r or not good: raise AuthError('Email or password is incorrect.')
        token=secrets.token_urlsafe(32)
        with self.db() as c:
            c.execute('DELETE FROM sessions WHERE expires<?',(self.now(),))
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(self.digest(token),r['id'],mode,self.now()+7*86400))
        return token

    def session(self, token):
        if not token: return None
        with self.db() as c:
            r=c.execute('SELECT users.id,users.email,users.name,users.role,sessions.mode FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>?',(self.digest(token),self.now())).fetchone()
            return dict(r) if r else None
    def logout(self, token):
        with self.db() as c: c.execute('DELETE FROM sessions WHERE token=?',(self.digest(token or ''),))
