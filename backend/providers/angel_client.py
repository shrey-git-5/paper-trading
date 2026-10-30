"""Angel One SmartAPI client for the Paper Trader app: official live NSE prices.

Your own Angel One account and SmartAPI key, used only to READ prices. This
module never places orders. Standard library only.

What it needs (typed by you into the app's Settings, saved only on your Mac in
trader/app/angel.json, readable by your user account alone):
  api_key      from smartapi.angelone.in > My Apps (create a free app)
  client_code  your Angel One client ID
  pin          your 4-digit Angel One login PIN
  totp_secret  the text behind the QR code shown when you enable TOTP for SmartAPI

Endpoints (from Angel One's official smartapi-python SDK):
  POST /rest/auth/angelbroking/user/v1/loginByPassword   clientcode, password (PIN), totp
  POST /rest/secure/angelbroking/market/v1/quote/        {"mode": "FULL", "exchangeTokens": {"NSE": [...]}}
  POST /rest/secure/angelbroking/historical/v1/getCandleData
       {"exchange": "NSE", "symboltoken": "3045", "interval": "FIVE_MINUTE",
        "fromdate": "2026-10-30 09:15", "todate": "2026-10-30 14:00"}
  Instrument list: OpenAPIScripMaster.json (NSE "-EQ" rows give each stock's token)
"""

import base64
import datetime
import hashlib
import hmac
import json
import os
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid

ROOT = "https://apiconnect.angelone.in"
SCRIP_MASTER = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
UA = "indian-trader-skill/1.0 (personal paper-trading tool; Python urllib)"
QUOTE_BATCH = 50
PAUSES = {"quote": 1.05, "candle": 0.40, "login": 1.0}   # stay well inside Angel's per-second limits


class AngelError(Exception):
    pass


def totp_now(secret, at=None, step=30, digits=6):
    """RFC 6238 one-time code from the base32 secret behind Angel's TOTP QR code."""
    key = base64.b32decode(secret.strip().replace(" ", "").upper() + "=" * (-len(secret.strip().replace(" ", "")) % 8))
    counter = int((at if at is not None else time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def _mac():
    n = uuid.getnode()
    return ":".join("%02x" % ((n >> s) & 0xFF) for s in range(40, -1, -8))


class Angel:
    def __init__(self, folder, opener=None):
        self.folder = folder
        self.cred_path = os.path.join(folder, "angel.json")
        self.map_path = os.path.join(folder, "angel-nse-eq.json")
        self.opener = opener or urllib.request.build_opener()
        self.jwt = None
        self.jwt_day = None
        self.lock = threading.RLock()
        self.last = {}
        self.tokens = None

    # ------------------------------------------------------------ credentials
    def creds(self):
        try:
            with open(self.cred_path, encoding="utf-8") as fh:
                c = json.load(fh)
            return c if all(c.get(k) for k in ("api_key", "client_code", "pin", "totp_secret")) else None
        except (OSError, ValueError):
            return None

    def configured(self):
        return self.creds() is not None

    def save_creds(self, api_key, client_code, pin, totp_secret):
        c = {"api_key": api_key.strip(), "client_code": client_code.strip().upper(), "pin": str(pin).strip(),
             "totp_secret": totp_secret.strip().replace(" ", "")}
        if not all(c.values()):
            raise AngelError("all four fields are needed: API key, client code, PIN and TOTP secret")
        try:
            totp_now(c["totp_secret"])
        except (ValueError, TypeError, base64.binascii.Error):
            raise AngelError("the TOTP secret is not valid: copy the text under the QR code (letters A-Z and 2-7)")
        os.makedirs(self.folder, exist_ok=True)
        fd = os.open(self.cred_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(c, fh)
        self.jwt = None

    def forget(self):
        self.jwt = None
        if os.path.exists(self.cred_path):
            os.remove(self.cred_path)

    # ------------------------------------------------------------ http
    def _wait(self, kind):
        gap = PAUSES.get(kind, 0.5) - (time.time() - self.last.get(kind, 0))
        if gap > 0:
            time.sleep(gap)
        self.last[kind] = time.time()

    def _post(self, path, body, kind, auth=True, retry=True):
        c = self.creds()
        if not c:
            raise AngelError("Angel One is not connected: add your details in Settings")
        if auth:
            self.login()
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA,
                   "X-UserType": "USER", "X-SourceID": "WEB", "X-ClientLocalIP": "127.0.0.1",
                   "X-ClientPublicIP": "127.0.0.1", "X-MACAddress": _mac(), "X-PrivateKey": c["api_key"]}
        if auth:
            headers["Authorization"] = "Bearer " + self.jwt
        with self.lock:
            self._wait(kind)
            req = urllib.request.Request(ROOT + path, data=json.dumps(body).encode(), headers=headers, method="POST")
            try:
                with self.opener.open(req, timeout=20) as r:
                    doc = json.loads(r.read().decode("utf-8", "replace") or "{}")
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")[:300]
                if e.code in (401, 403) and auth and retry:
                    self.jwt = None
                    return self._post(path, body, kind, auth, retry=False)
                raise AngelError("Angel One answered HTTP %d: %s" % (e.code, text or e.reason))
            except (urllib.error.URLError, OSError) as e:
                raise AngelError("could not reach Angel One: %s" % getattr(e, "reason", e))
            except ValueError:
                raise AngelError("Angel One sent something that is not JSON")
        if not doc.get("status", doc.get("success", False)):
            code = doc.get("errorcode") or doc.get("errorCode") or ""
            if auth and retry and code in ("AG8001", "AG8002", "AG8003", "AB1010"):   # token invalid / expired
                self.jwt = None
                return self._post(path, body, kind, auth, retry=False)
            raise AngelError("Angel One said: %s %s" % (doc.get("message") or "error", code))
        return doc.get("data")

    def login(self):
        today = datetime.date.today().isoformat()
        if self.jwt and self.jwt_day == today:
            return
        c = self.creds()
        data = self._post("/rest/auth/angelbroking/user/v1/loginByPassword",
                          {"clientcode": c["client_code"], "password": c["pin"], "totp": totp_now(c["totp_secret"])},
                          "login", auth=False)
        if not data or not data.get("jwtToken"):
            raise AngelError("Angel One login gave no token (check client code, PIN and TOTP secret)")
        self.jwt, self.jwt_day = data["jwtToken"].replace("Bearer ", ""), today

    # ------------------------------------------------------------ instruments
    def stock_tokens(self, refresh=False):
        """{SYMBOL: token} for every NSE equity (the -EQ series), cached for the day."""
        if self.tokens and not refresh:
            return self.tokens
        today = datetime.date.today().isoformat()
        try:
            with open(self.map_path, encoding="utf-8") as fh:
                doc = json.load(fh)
            if doc.get("date") == today and doc.get("tokens") and not refresh:
                self.tokens = doc["tokens"]
                return self.tokens
        except (OSError, ValueError):
            pass
        req = urllib.request.Request(SCRIP_MASTER, headers={"User-Agent": UA})
        try:
            with self.opener.open(req, timeout=120) as r:
                rows = json.loads(r.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise AngelError("could not download Angel One's instrument list: %s" % getattr(e, "reason", e))
        tokens = parse_scrips(rows)
        if not tokens:
            raise AngelError("Angel One's instrument list had no NSE equities")
        os.makedirs(self.folder, exist_ok=True)
        with open(self.map_path, "w", encoding="utf-8") as fh:
            json.dump({"date": today, "tokens": tokens}, fh)
        self.tokens = tokens
        return tokens

    def token(self, sym):
        t = self.stock_tokens().get(sym.upper())
        if not t:
            raise AngelError("%s is not an NSE equity in Angel One's list" % sym.upper())
        return t

    # ------------------------------------------------------------ prices
    def quotes(self, symbols, mode="FULL"):
        """{SYMBOL: row} for many symbols, in batches."""
        tokens = self.stock_tokens()
        by_token = {tokens[s]: s for s in symbols if s in tokens}
        out = {}
        ids = list(by_token)
        for i in range(0, len(ids), QUOTE_BATCH):
            data = self._post("/rest/secure/angelbroking/market/v1/quote/",
                              {"mode": mode, "exchangeTokens": {"NSE": ids[i:i + QUOTE_BATCH]}}, "quote") or {}
            for row in data.get("fetched") or []:
                s = by_token.get(str(row.get("symbolToken")))
                if s:
                    out[s] = row
        return out

    def candles(self, sym, day=None, now=None):
        """Today's 5-minute candles as [{"t","o","h","l","c","v"}]."""
        now = now or datetime.datetime.now()
        day = day or now.date()
        frm = datetime.datetime.combine(day, datetime.time(9, 15))
        to = min(datetime.datetime.combine(day, datetime.time(15, 30)), now)
        if to <= frm:
            return []
        data = self._post("/rest/secure/angelbroking/historical/v1/getCandleData",
                          {"exchange": "NSE", "symboltoken": self.token(sym), "interval": "FIVE_MINUTE",
                           "fromdate": frm.strftime("%Y-%m-%d %H:%M"), "todate": to.strftime("%Y-%m-%d %H:%M")},
                          "candle") or []
        return parse_candles(data)


def parse_scrips(rows):
    out = {}
    for r in rows or []:
        if r.get("exch_seg") != "NSE":
            continue
        sym = str(r.get("symbol") or "")
        if not sym.endswith("-EQ"):
            continue
        name = sym[:-3].upper()
        tok = str(r.get("token") or "").strip()
        if name and tok:
            out[name] = tok
    return out


def parse_candles(data):
    bars = []
    for row in data or []:
        try:
            ts, o, h, l, c, v = row[:6]
            t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if t.tzinfo is not None:
                t = (t.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))).replace(tzinfo=None)
            if not (datetime.time(9, 15) <= t.time() < datetime.time(15, 30)):
                continue
            bars.append({"t": t.strftime("%H:%M"), "o": float(o), "h": float(h), "l": float(l), "c": float(c),
                         "v": int(v or 0)})
        except (ValueError, TypeError):
            continue
    return bars
