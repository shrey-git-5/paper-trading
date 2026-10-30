"""Angel One SmartAPI as a price source (official, free for Angel One account holders).
The client itself is in angel_client.py; this adapts it to the Provider interface."""

from util import ist_now
from .angel_client import Angel as Client, AngelError
from .base import Provider, ProviderError


class Angel(Provider):
    name, label = "angel", "Angel One (live)"

    def __init__(self, data_dir):
        self.c = Client(data_dir)

    def ready(self):
        return (True, "") if self.c.configured() else (False, "Angel One is not set up: Settings > Live prices > Angel One")

    def save(self, api_key, client_code, pin, totp_secret):
        try:
            self.c.save_creds(api_key, client_code, pin, totp_secret)
            self.c.login()
        except AngelError as e:
            raise ProviderError(str(e))

    def forget(self):
        self.c.forget()

    def universe(self):
        try:
            return [{"symbol": s, "name": ""} for s in sorted(self.c.stock_tokens())]
        except AngelError as e:
            raise ProviderError(str(e))

    def snapshot(self, symbols):
        try:
            rows = self.c.quotes(symbols, mode="FULL")
        except AngelError as e:
            raise ProviderError(str(e))
        out = {}
        for s, r in rows.items():
            ltp, prev = float(r.get("ltp") or 0), r.get("close")
            out[s] = {"ltp": round(ltp, 2), "open": r.get("open"), "high": r.get("high"), "low": r.get("low"),
                      "prev_close": prev, "volume": int(r.get("tradeVolume") or 0), "pct": r.get("percentChange"),
                      "as_of": str(r.get("exchFeedTime") or "")[-8:]}
        return out

    def candles(self, symbol, now):
        try:
            return self.c.candles(symbol, now=ist_now())
        except AngelError as e:
            raise ProviderError(str(e))
