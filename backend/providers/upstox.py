"""Upstox: official, free live NSE prices for Upstox account holders.

Login (OAuth 2.0, as in Upstox's API docs):
  1. Your browser goes to https://api.upstox.com/v2/login/authorization/dialog
       ?response_type=code&client_id=<API key>&redirect_uri=<redirect URL>&state=<random>
  2. You sign in on upstox.com; Upstox sends you back to <redirect URL>?code=...&state=...
  3. This server swaps the code for an access token:
       POST https://api.upstox.com/v2/login/authorization/token
       (code, client_id, client_secret, redirect_uri, grant_type=authorization_code)
  The token expires at 3:30 AM the next day, so you log in once per trading day.

Prices:
  GET /v2/market-quote/quotes?instrument_key=NSE_EQ|INE002A01018,...      up to 500 at once
  GET /v3/historical-candle/intraday/{instrument_key}/minutes/5           today's 5-minute candles
  Instruments: https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz (segment NSE_EQ, type EQ)

Only reads prices. Never places, changes or cancels an order.
"""

import datetime
import gzip
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from util import read_json, write_json
from .base import Provider, ProviderError

API = "https://api.upstox.com"
DIALOG = API + "/v2/login/authorization/dialog"
TOKEN = API + "/v2/login/authorization/token"
INSTRUMENTS = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
UA = "paper-trader/1.0 (personal paper-trading app; Python urllib)"
BATCH = 200          # instrument keys per quote call (Upstox allows 500; 200 keeps the URL short)
PAUSE = 0.12         # seconds between calls, well inside Upstox's per-second limit


def next_expiry(now):
    """Upstox tokens expire at 3:30 AM the following day (a token made before 3:30 AM expires the same morning)."""
    cut = now.replace(hour=3, minute=30, second=0, microsecond=0)
    return cut if now < cut else cut + datetime.timedelta(days=1)


class Upstox(Provider):
    name, label = "upstox", "Upstox (live)"

    def __init__(self, secrets_file, data_dir, opener=None, now=None):
        self.secrets_file, self.data_dir = secrets_file, data_dir
        self.map_file = os.path.join(data_dir, "upstox-nse-eq.json")
        self.opener = opener or urllib.request.build_opener()
        self.now = now
        self.lock = threading.RLock()
        self.last = 0.0
        self.instruments = None

    # ------------------------------------------------------------ keys and login
    def _all(self):
        return read_json(self.secrets_file, {}) or {}

    def creds(self):
        return self._all().get("upstox") or {}

    def _save(self, c):
        doc = self._all()
        doc["upstox"] = c
        write_json(self.secrets_file, doc, private=True)

    def save_app(self, api_key, api_secret, redirect_uri):
        api_key, api_secret, redirect_uri = (api_key or "").strip(), (api_secret or "").strip(), (redirect_uri or "").strip()
        c = self.creds()
        if not api_key or not redirect_uri or not (api_secret or c.get("api_secret")):
            raise ProviderError("Upstox needs the API key, the API secret and the redirect URL from your app")
        c.update(api_key=api_key, redirect_uri=redirect_uri)
        if api_secret:
            c["api_secret"] = api_secret
        if c.get("api_key_was") and c["api_key_was"] != api_key:
            c.pop("access_token", None)
        c["api_key_was"] = api_key
        self._save(c)

    def login_url(self):
        c = self.creds()
        if not c.get("api_key") or not c.get("redirect_uri"):
            raise ProviderError("Save your Upstox API key, secret and redirect URL first")
        state = secrets.token_urlsafe(16)
        c["state"] = state
        self._save(c)
        return DIALOG + "?" + urllib.parse.urlencode({"response_type": "code", "client_id": c["api_key"],
                                                      "redirect_uri": c["redirect_uri"], "state": state})

    def finish_login(self, code, state, now):
        c = self.creds()
        if not code:
            raise ProviderError("Upstox did not send a login code back")
        if not state or state != c.get("state"):
            raise ProviderError("this login link is stale or not from this app; click Login with Upstox again")
        body = urllib.parse.urlencode({"code": code, "client_id": c["api_key"], "client_secret": c["api_secret"],
                                       "redirect_uri": c["redirect_uri"], "grant_type": "authorization_code"}).encode()
        req = urllib.request.Request(TOKEN, data=body, method="POST", headers={
            "accept": "application/json", "Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
        doc = self._open(req)
        token = (doc or {}).get("access_token")
        if not token:
            raise ProviderError("Upstox login gave no token: %s" % ((doc or {}).get("errors") or doc))
        c.update(access_token=token, token_expiry=next_expiry(now).isoformat(), user=doc.get("user_name") or "",
                 user_id=doc.get("user_id") or "")
        c.pop("state", None)
        self._save(c)
        return c

    def set_token(self, token, now):
        """For Upstox's 'Generate' button on the developer page: paste today's token directly."""
        token = (token or "").strip()
        if len(token) < 20:
            raise ProviderError("that does not look like an Upstox access token")
        c = self.creds()
        c.update(access_token=token, token_expiry=next_expiry(now).isoformat())
        self._save(c)

    def forget(self):
        doc = self._all()
        doc.pop("upstox", None)
        write_json(self.secrets_file, doc, private=True)

    def status(self, now):
        c = self.creds()
        exp = c.get("token_expiry")
        live = bool(c.get("access_token") and exp and now < datetime.datetime.fromisoformat(exp))
        return {"app_saved": bool(c.get("api_key")), "logged_in": live, "user": c.get("user", ""),
                "expires": exp, "redirect_uri": c.get("redirect_uri", ""), "api_key": c.get("api_key", "")}

    def ready(self):
        from util import ist_now
        st = self.status(self.now() if self.now else ist_now())
        if not st["app_saved"]:
            return False, "Upstox is not set up: Settings > Live prices > Upstox"
        if not st["logged_in"]:
            return False, "Upstox login needed today: Settings > Login with Upstox (tokens expire at 3:30 AM)"
        return True, ""

    # ------------------------------------------------------------ http
    def _open(self, req):
        with self.lock:
            gap = PAUSE - (time.time() - self.last)
            if gap > 0:
                time.sleep(gap)
            self.last = time.time()
        try:
            with self.opener.open(req, timeout=25) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:300]
            if e.code == 401:
                c = self.creds()
                c.pop("access_token", None)
                self._save(c)
                raise ProviderError("Upstox login expired: Settings > Login with Upstox")
            if e.code == 429:
                raise ProviderError("Upstox says too many requests; slow down and try again in a minute")
            raise ProviderError("Upstox answered HTTP %d: %s" % (e.code, text or e.reason))
        except (urllib.error.URLError, OSError) as e:
            raise ProviderError("could not reach Upstox: %s" % getattr(e, "reason", e))
        except ValueError:
            raise ProviderError("Upstox sent something that is not JSON")

    def _get(self, path, params=None):
        ok, why = self.ready()
        if not ok:
            raise ProviderError(why)
        url = API + path + ("?" + urllib.parse.urlencode(params, safe="|,") if params else "")
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA,
                                                   "Authorization": "Bearer " + self.creds()["access_token"]})
        doc = self._open(req)
        if doc.get("status") not in (None, "success"):
            raise ProviderError("Upstox said: %s" % (doc.get("errors") or doc.get("status")))
        return doc.get("data")

    # ------------------------------------------------------------ instruments
    def _instruments(self):
        if self.instruments:
            return self.instruments
        from util import ist_now
        today = ist_now().date().isoformat()
        cached = read_json(self.map_file, {}) or {}
        if cached.get("date") == today and cached.get("items"):
            self.instruments = cached["items"]
            return self.instruments
        req = urllib.request.Request(INSTRUMENTS, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        rows = self._open(req)
        items = parse_instruments(rows)
        if not items:
            raise ProviderError("Upstox's instrument list had no NSE equities")
        write_json(self.map_file, {"date": today, "items": items})
        self.instruments = items
        return items

    def universe(self):
        return [{"symbol": s, "name": v["name"]} for s, v in sorted(self._instruments().items())]

    def key(self, symbol):
        v = self._instruments().get(symbol.upper())
        if not v:
            raise ProviderError("%s is not an NSE equity in Upstox's list" % symbol.upper())
        return v["key"]

    # ------------------------------------------------------------ prices
    def snapshot(self, symbols):
        inst = self._instruments()
        by_key = {inst[s]["key"]: s for s in symbols if s in inst}
        keys = list(by_key)
        out = {}
        for i in range(0, len(keys), BATCH):
            data = self._get("/v2/market-quote/quotes", {"instrument_key": ",".join(keys[i:i + BATCH])}) or {}
            for row in data.values():
                s = by_key.get(row.get("instrument_token"))
                if s:
                    out[s] = parse_quote(row)
        return out

    def candles(self, symbol, now):
        path = "/v3/historical-candle/intraday/%s/minutes/5" % urllib.parse.quote(self.key(symbol), safe="")
        data = self._get(path) or {}
        return parse_candles(data.get("candles") or [])


def parse_instruments(rows):
    out = {}
    for r in rows or []:
        if r.get("segment") == "NSE_EQ" and r.get("instrument_type") == "EQ" and r.get("trading_symbol"):
            out[str(r["trading_symbol"]).upper()] = {"key": r["instrument_key"], "name": r.get("name") or ""}
    return out


def parse_quote(row):
    ltp = float(row.get("last_price") or 0)
    ohlc = row.get("ohlc") or {}
    chg = row.get("net_change")
    prev = round(ltp - float(chg), 2) if chg is not None else None
    ts = row.get("timestamp") or row.get("last_trade_time") or ""
    as_of = ""
    try:
        if str(ts).isdigit():
            as_of = (datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=int(ts), hours=5, minutes=30)
                     ).strftime("%H:%M:%S")
        elif ts:
            as_of = str(ts)[11:19]
    except (ValueError, OverflowError):
        pass
    return {"ltp": round(ltp, 2), "open": ohlc.get("open"), "high": ohlc.get("high"), "low": ohlc.get("low"),
            "prev_close": prev, "volume": int(row.get("volume") or 0),
            "pct": round(100 * float(chg) / prev, 2) if chg is not None and prev else None, "as_of": as_of}


def parse_candles(rows):
    bars = []
    for row in rows:
        try:
            t = datetime.datetime.fromisoformat(str(row[0]))
            if t.tzinfo is not None:
                t = t.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).replace(tzinfo=None)
            if not (datetime.time(9, 15) <= t.time() < datetime.time(15, 30)):
                continue
            bars.append({"t": t.strftime("%H:%M"), "o": float(row[1]), "h": float(row[2]), "l": float(row[3]),
                         "c": float(row[4]), "v": int(row[5] or 0)})
        except (ValueError, TypeError, IndexError):
            continue
    bars.sort(key=lambda b: b["t"])            # Upstox sends newest first
    return bars
