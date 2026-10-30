#!/usr/bin/env python3
"""Paper Trader web server. Standard library only: nothing to pip install.

    python3 backend/server.py                 # http://localhost:8765 (only this computer can open it)
    DATA_DIR=... PORT=... python3 backend/launch.py    # single local launcher

Serves the screens in frontend/, a JSON API under /api/, the Upstox login round-trip under
/upstox/, and runs the paper broker's watcher (stop-loss, target, 3:20 PM square-off) in the
background.
"""

import hmac
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from engine import Engine, OrderError  # noqa: E402
from providers.base import ProviderError  # noqa: E402
from util import ist_now
from accounts import Accounts, AuthError, mode_name
from gmail_sender import GmailSender, GmailError
from user_engines import UserEngines
from http.cookies import SimpleCookie  # noqa: E402

ACCOUNTS = None
MAILER = None
ENGINES = None
LEGACY_ENGINE = None
PUBLIC_FILES = {"/", "/start.html", "/login.html", "/setup.html", "/css/styles.css", "/css/access.css", "/js/entry.js", "/js/login.js", "/js/setup.js", "/favicon.svg", "/gmail/callback", "/healthz", "/api/auth/status"}
PUBLIC_POSTS = {"/api/auth/login", "/api/auth/register", "/api/auth/recover", "/api/auth/verify", "/api/gmail/connect", "/api/tick"}


class Handler(BaseHTTPRequestHandler):
    server_version = "PaperTrader/1.0"

    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------------------ plumbing
    def _send(self, code, body, ctype="application/json", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json",
                                                                                        "application/javascript")) else ""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _redirect(self, where, headers=None):
        self.send_response(302)
        self.send_header("Location", where)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def _cookies(self):
        c=SimpleCookie()
        try:c.load(self.headers.get("Cookie") or "")
        except Exception:pass
        return c

    def _token(self):
        c=self._cookies();return c["it_session"].value if "it_session" in c else ""

    def _authed(self,path):
        self.user=ACCOUNTS.session(self._token())
        requested_mode=self.headers.get('X-Trade-Mode')
        if self.user and requested_mode in ('demo','paper'):self.user=dict(self.user,mode=requested_mode)
        return bool(self.user) or path in PUBLIC_FILES or path in PUBLIC_POSTS

    @property
    def engine(self):
        return ENGINES.get(self.user)

    def _origin(self):
        return os.environ.get("PUBLIC_ORIGIN") or "http://localhost:%d" % config.PORT

    def _cookie(self,name,value,max_age=604800):
        secure="; Secure" if self._origin().startswith("https:") else ""
        return "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (name,value,max_age,secure)

    def _admin(self):
        return bool(getattr(self,"user",None) and self.user['role']=='owner') or ACCOUNTS.setup_ok(self.headers.get('X-Setup-Token'))

    def _post_allowed(self):
        origin=self.headers.get('Origin')
        allowed={self._origin(),"http://localhost:%d"%config.PORT,"http://127.0.0.1:%d"%config.PORT}
        return (not origin or origin in allowed) and self.headers.get('Content-Type','').split(';')[0]=='application/json'

    def _static(self, path):
        rel = "start.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.normpath(os.path.join(config.FRONTEND, rel))
        if os.path.commonpath([full, config.FRONTEND]) != config.FRONTEND or not os.path.isfile(full):
            return self._send(404, b"Not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "application/javascript"
        with open(full, "rb") as fh:
            return self._send(200, fh.read(), ctype)

    # ------------------------------------------------------------ GET
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        path = u.path
        if path == "/healthz":
            return self._send(200, {"ok": True, "app": "IndianTrader", "version": 3})
        if not self._authed(path):
            if path.startswith("/api/"):
                return self._send(401, {"error": "please log in"})
            return self._redirect("/start.html")
        try:
            if path == "/api/auth/status":
                status={"setup_required":not ACCOUNTS.has_users(),"gmail_connected":MAILER.ready(),"user":self.user}
                if self._admin():status['gmail']=MAILER.status()
                return self._send(200,status)
            if path == "/gmail/callback":
                c=self._cookies()
                MAILER.finish(q.get('code'),q.get('state'),c['gmail_state'].value if 'gmail_state' in c else '')
                return self._redirect('/setup.html?connected=1',{'Set-Cookie':self._cookie('gmail_state','',0)})
            if path == "/api/state":
                state=self.engine.state();state["identity"]={"name":self.user["name"],"email":self.user["email"],"mode":self.user["mode"],"role":self.user["role"]};return self._send(200,state)
            if path == "/api/watchlist":
                return self._send(200, self.engine.watchlist())
            if path == "/api/quote":
                return self._send(200, self.engine.quote(q.get("s", "")))
            if path == "/api/plan":
                return self._send(200, self.engine.plan_for(q.get("s", "").upper()))
            if path == "/api/preview":
                return self._send(200, self.engine.preview(q.get("s", ""), q.get("qty") or 0, q.get("stop") or 0,
                                                      q.get("target") or 0, q.get("limit") or None))
            if path == "/api/search":
                term = q.get("q", "").strip().upper()
                pool = self.engine.provider.universe()
                hits = [x for x in pool if x["symbol"].startswith(term)]
                words = lambda n: (n or "").upper().replace("&", " ").split()
                hits += [x for x in pool if term and any(w.startswith(term) for w in words(x.get("name")))
                         and x not in hits]
                return self._send(200, {"items": hits[:20], "total": len(pool)})
            if path == "/upstox/login":
                return self._redirect(self.engine.upstox.login_url())
            if path in ("/upstox/callback", "/upstox/callback/"):
                try:
                    self.engine.upstox.finish_login(q.get("code"), q.get("state"), ist_now())
                    self.engine.save_settings({"source": "upstox"}) if self.user["mode"] == "paper" else None
                    return self._redirect("/index.html#/settings?upstox=ok")
                except ProviderError as e:
                    return self._redirect("/index.html#/settings?upstox=" + urllib.parse.quote(str(e)))
            if path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            return self._static(path)
        except (ProviderError, OrderError, AuthError, GmailError, ValueError, KeyError) as e:
            return self._send(400, {"error": str(e)})

    # ------------------------------------------------------------ POST
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._post_allowed():return self._send(403,{"error":"Request must come from this app as JSON."})
        try:b=self._body()
        except (ValueError,OverflowError):return self._send(400,{"error":"Invalid request."})
        if not isinstance(b,dict):return self._send(400,{"error":"Invalid request."})
        if not self._authed(path):
            return self._send(401, {"error": "please log in"})
        try:
            ip=self.client_address[0]
            if path == '/api/tick':
                tok=self.headers.get('X-Tick-Token') or ''
                if not config.TICK_TOKEN or not hmac.compare_digest(tok,config.TICK_TOKEN):return self._send(403,{'error':'forbidden'})
                ENGINES.tick_all();return self._send(200,{'ok':True})
            if path == "/api/gmail/connect":
                if not self._admin():return self._send(403,{"error":"Only the owner can configure Gmail. Start the app using its command file."})
                url,state=MAILER.begin(b,self._origin()+'/gmail/callback')
                return self._send(200,{"url":url},headers={'Set-Cookie':self._cookie('gmail_state',state,600)})
            if path in ('/api/auth/register','/api/auth/recover'):
                purpose='signup' if path.endswith('register') else 'reset'
                return self._send(200,ACCOUNTS.request_code(purpose,b,ip,self.headers.get('X-Setup-Token')))
            if path == '/api/auth/verify':
                ACCOUNTS.rate('verify-ip:'+ip,30,900)
                result=ACCOUNTS.verify_code(b.get('challenge'),b.get('code'),b.get('password'))
                if result.get('owner'):
                    owner=next(u for u in ACCOUNTS.users() if u['id']==result['user_id'])
                    for mode in ('demo','paper'):ENGINES.get(dict(owner,mode=mode))
                return self._send(200,{'ok':True})
            if path == '/api/auth/login':
                token=ACCOUNTS.login(b,ip)
                return self._send(200,{'ok':True},headers={'Set-Cookie':self._cookie('it_session',token)})
            if path == '/api/auth/logout':
                ACCOUNTS.logout(self._token())
                return self._send(200,{'ok':True},headers={'Set-Cookie':self._cookie('it_session','',0)})
            if path == '/api/auth/mode':
                mode=mode_name(b.get('mode'))
                with ACCOUNTS.db() as c:c.execute('UPDATE sessions SET mode=? WHERE token=?',(mode,ACCOUNTS.digest(self._token())))
                return self._send(200,{'ok':True})
            if path == "/api/order":
                return self._send(200, self.engine.place(b))
            if path == "/api/exit":
                return self._send(200, self.engine.exit(b.get("id")))
            if path == "/api/modify":
                return self._send(200, self.engine.modify(b.get("id"), b.get("stop"), b.get("target")))
            if path == "/api/cancel":
                return self._send(200, self.engine.cancel(b.get("id")))
            if path == "/api/scan":
                if not self.engine.scan["running"]:
                    threading.Thread(target=self.engine.run_scan, daemon=True).start()
                return self._send(200, {"started": True})
            if path == "/api/settings":
                if 'source' in b and ((self.user['mode']=='demo' and b['source']!='demo') or (self.user['mode']=='paper' and b['source']=='demo')):
                    raise AuthError('Use Switch mode to move between Demo and Paper Trading.')
                return self._send(200, self.engine.save_settings(b))
            if path == "/api/watchlist":
                return self._send(200, self.engine.save_settings({"watchlist": b.get("symbols") or []}))
            if path == "/api/reset":
                self.engine.reset(float(b.get("capital") or self.engine.settings()["budget"]))
                return self._send(200, {"ok": True})
            if path == "/api/upstox/app":
                self.engine.upstox.save_app(b.get("api_key"), b.get("api_secret"), b.get("redirect_uri"))
                return self._send(200, {"ok": True, "login_url": self.engine.upstox.login_url()})
            if path == "/api/upstox/token":
                self.engine.upstox.set_token(b.get("token"), ist_now())
                self.engine.save_settings({"source": "upstox"}) if self.user["mode"] == "paper" else None
                return self._send(200, {"ok": True})
            if path == "/api/upstox/forget":
                self.engine.upstox.forget()
                if self.engine.settings()["source"] == "upstox":
                    self.engine.cache.clear()
                return self._send(200, {"ok": True})
            if path == "/api/angel":
                self.engine.angel.save(b.get("api_key", ""), b.get("client_code", ""), b.get("pin", ""), b.get("totp_secret", ""))
                self.engine.save_settings({"source": "angel"}) if self.user["mode"] == "paper" else None
                return self._send(200, {"ok": True})
            if path == "/api/angel/forget":
                self.engine.angel.forget()
                if self.engine.settings()["source"] == "angel":
                    self.engine.cache.clear()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except (ProviderError, OrderError, AuthError, GmailError, ValueError, KeyError) as e:
            return self._send(400, {"error": str(e)})


def watcher():
    while True:
        try:
            ENGINES.tick_all()
            if not ACCOUNTS.has_users():LEGACY_ENGINE.tick()
        except Exception as e:  # never let the watcher die
            print("watcher: %s" % e, file=sys.stderr)
        time.sleep(2)


def main():
    global ACCOUNTS, MAILER, ENGINES, LEGACY_ENGINE
    os.makedirs(config.DATA_DIR, exist_ok=True)
    MAILER=GmailSender(config.DATA_DIR)
    ACCOUNTS=Accounts(config.DATA_DIR,MAILER)
    ENGINES=UserEngines(config.DATA_DIR,ACCOUNTS)
    LEGACY_ENGINE=Engine()
    threading.Thread(target=watcher, daemon=True).start()
    srv = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    where = "localhost" if config.HOST in ("127.0.0.1", "localhost") else config.HOST
    print("Paper Trader is running: open http://%s:%d" % (where, config.PORT), flush=True)
    print("Data folder: %s (email/password accounts)" % config.DATA_DIR, flush=True)
    if config.APP_PASSWORD:
        print("Named accounts replace the old shared APP_PASSWORD login.",flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
