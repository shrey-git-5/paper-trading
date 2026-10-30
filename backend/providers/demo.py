"""A pretend market: made-up but realistic prices for 20 well-known NSE names, fixed for the day,
so you can practise any time, including weekends. Some stocks break out, some drift down, some chop."""

import datetime
import hashlib
import random

from market import OPEN
from util import ist_now
from .base import Provider, ProviderError

STOCKS = {"TATASTEEL": "Tata Steel", "IDEA": "Vodafone Idea", "YESBANK": "Yes Bank", "SUZLON": "Suzlon Energy",
          "IRFC": "Indian Railway Finance Corp", "NHPC": "NHPC", "PNB": "Punjab National Bank", "SAIL": "SAIL",
          "BHEL": "BHEL", "IOC": "Indian Oil", "NTPC": "NTPC", "ONGC": "ONGC", "ITC": "ITC", "WIPRO": "Wipro",
          "COALINDIA": "Coal India", "TATAPOWER": "Tata Power", "ZOMATO": "Zomato", "IRCTC": "IRCTC",
          "SBIN": "State Bank of India", "RELIANCE": "Reliance Industries", "TCS": "Tata Consultancy Services",
          "INFY": "Infosys", "HDFCBANK": "HDFC Bank", "ICICIBANK": "ICICI Bank"}


class Demo(Provider):
    name, label = "demo", "Demo (pretend prices)"

    def __init__(self, clock):
        self.clock = clock

    def ready(self):
        return True, ""

    def universe(self):
        return [{"symbol": s, "name": n} for s, n in sorted(STOCKS.items())]

    def _path(self, sym):
        day = ist_now().date().isoformat()
        seed = int(hashlib.sha1(("%s|%s" % (sym, day)).encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        base = 12 + seed % 30 if sym in ("IDEA", "YESBANK", "SUZLON") else 40 + seed % 1500
        kind = seed % 3                                  # 0 breakout up, 1 drift down, 2 chop
        p, path = float(base), []
        for m in range(375):
            drift = 0.0009 if (kind == 0 and 18 <= m < 120) else -0.0004 if kind == 1 else 0.0
            p *= 1 + drift + rng.gauss(0, 0.0016)
            path.append(round(p, 2))
        return float(base), path

    def _minute(self, now):
        m = int((now - datetime.datetime.combine(now.date(), OPEN)).total_seconds() // 60)
        return max(1, min(m, 375))

    def snapshot(self, symbols):
        now = self.clock.now()
        m = self._minute(now)
        out = {}
        for s in symbols:
            if s not in STOCKS:
                continue
            base, path = self._path(s)
            seg = path[:m]
            ltp = seg[-1]
            out[s] = {"ltp": ltp, "open": round(base, 2), "high": max(seg), "low": min(seg),
                      "prev_close": round(base, 2), "volume": 20000 * m + (hash(s) % 9000),
                      "pct": round(100 * (ltp / base - 1), 2), "as_of": now.strftime("%H:%M:%S")}
        return out

    def candles(self, symbol, now):
        if symbol not in STOCKS:
            raise ProviderError("%s is not in the demo market. Demo stocks: %s" % (symbol, ", ".join(sorted(STOCKS))))
        base, path = self._path(symbol)
        now = self.clock.now()
        m = self._minute(now)
        bars = []
        start = datetime.datetime.combine(now.date(), OPEN)
        for k in range(0, m - (m % 5), 5):
            seg = path[k:k + 5]
            bars.append({"t": (start + datetime.timedelta(minutes=k)).strftime("%H:%M"),
                         "o": path[k - 1] if k else round(base, 2), "h": max(seg), "l": min(seg), "c": seg[-1],
                         "v": 10000 + (hash(symbol + str(k)) % 50000)})
        return bars
