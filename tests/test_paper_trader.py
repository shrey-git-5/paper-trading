"""Offline tests for Paper Trader: rules, charges, orders, exits, and the Upstox client
against a fake Upstox server. Run:  python3 -m unittest discover -s tests -v"""
import datetime
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

TMP = tempfile.mkdtemp()
os.environ["DATA_DIR"] = TMP
import config  # noqa: E402
import engine as engine_mod  # noqa: E402
from charges import intraday_charges  # noqa: E402
from providers import upstox as up  # noqa: E402
from providers.base import ProviderError  # noqa: E402

NOW = datetime.datetime(2026, 10, 30, 10, 0)


class FakeResp(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


INSTR = [{"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES LTD",
          "instrument_key": "NSE_EQ|INE002A01018"},
         {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "M&M", "name": "MAHINDRA & MAHINDRA LTD",
          "instrument_key": "NSE_EQ|INE101A01026"},
         {"segment": "NSE_EQ", "instrument_type": "BE", "trading_symbol": "JUNK", "name": "JUNK", "instrument_key": "NSE_EQ|X"},
         {"segment": "NSE_FO", "instrument_type": "FUT", "trading_symbol": "RELIANCE FUT", "name": "R", "instrument_key": "NSE_FO|1"}]


class FakeUpstox:
    def __init__(self):
        self.calls = []
        self.expired = False

    def open(self, req, timeout=None):
        url = req.full_url
        self.calls.append((url, req.data, dict(req.header_items())))
        if url == up.INSTRUMENTS:
            return FakeResp(gzip.compress(json.dumps(INSTR).encode()))
        if url == up.TOKEN:
            body = dict(urllib.parse.parse_qsl(req.data.decode()))
            assert body["grant_type"] == "authorization_code" and body["client_secret"] == "SECRET"
            return FakeResp(json.dumps({"access_token": "TOKEN1", "user_name": "SHREY", "user_id": "AB1234"}).encode())
        if self.expired:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b'{"status":"error"}'))
        if "/v2/market-quote/quotes" in url:
            keys = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["instrument_key"][0].split(",")
            data = {}
            for k in keys:
                sym = "RELIANCE" if "INE002" in k else "M&M"
                data["NSE_EQ:" + sym] = {"instrument_token": k, "last_price": 1452.4, "net_change": 7.4, "volume": 2500000,
                                         "ohlc": {"open": 1440.0, "high": 1455.0, "low": 1438.0, "close": 1452.4},
                                         "timestamp": "2026-10-30T13:58:01.000+05:30"}
            return FakeResp(json.dumps({"status": "success", "data": data}).encode())
        if "/v3/historical-candle/intraday/" in url:
            assert "NSE_EQ%7CINE002A01018" in url and url.endswith("/minutes/5")
            c = [["2026-10-30T09:25:00+05:30", 1444, 1449, 1443, 1448, 90, 0],
                 ["2026-10-30T09:20:00+05:30", 1442, 1446, 1441, 1444, 80, 0],
                 ["2026-10-30T09:15:00+05:30", 1440, 1446, 1438, 1442, 100, 0]]
            return FakeResp(json.dumps({"status": "success", "data": {"candles": c}}).encode())
        raise AssertionError("unexpected " + url)


class TestUpstox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fake = FakeUpstox()
        up.PAUSE = 0
        self.u = up.Upstox(os.path.join(self.dir, "secrets.json"), self.dir, opener=self.fake, now=lambda: NOW)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def login(self):
        self.u.save_app("KEY", "SECRET", "http://localhost:8765/upstox/callback")
        url = self.u.login_url()
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
        self.u.finish_login("CODE", state, NOW)

    def test_login_flow_and_expiry(self):
        self.assertFalse(self.u.ready()[0])
        self.u.save_app("KEY", "SECRET", "http://localhost:8765/upstox/callback")
        url = self.u.login_url()
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(q["client_id"], ["KEY"])
        self.assertEqual(q["response_type"], ["code"])
        with self.assertRaises(ProviderError):
            self.u.finish_login("CODE", "wrong-state", NOW)
        self.u.finish_login("CODE", q["state"][0], NOW)
        st = self.u.status(NOW)
        self.assertTrue(st["logged_in"])
        self.assertEqual(st["expires"], "2026-10-31T03:30:00")
        self.assertFalse(self.u.status(datetime.datetime(2026, 10, 31, 3, 31))["logged_in"])
        self.assertEqual(oct(os.stat(os.path.join(self.dir, "secrets.json")).st_mode & 0o777), "0o600")

    def test_expiry_rule(self):
        self.assertEqual(up.next_expiry(datetime.datetime(2026, 10, 30, 2, 0)), datetime.datetime(2026, 10, 30, 3, 30))
        self.assertEqual(up.next_expiry(datetime.datetime(2026, 10, 30, 20, 0)), datetime.datetime(2026, 10, 31, 3, 30))

    def test_prices_and_candles(self):
        self.login()
        uni = self.u.universe()
        self.assertEqual([x["symbol"] for x in uni], ["M&M", "RELIANCE"])     # EQ only, no BE, no futures
        snap = self.u.snapshot(["RELIANCE", "M&M", "NOTREAL"])
        self.assertEqual(snap["RELIANCE"]["ltp"], 1452.4)
        self.assertEqual(snap["RELIANCE"]["prev_close"], 1445.0)
        self.assertAlmostEqual(snap["RELIANCE"]["pct"], 0.51, places=2)
        self.assertEqual(snap["RELIANCE"]["as_of"], "13:58:01")
        bars = self.u.candles("RELIANCE", NOW)
        self.assertEqual([b["t"] for b in bars], ["09:15", "09:20", "09:25"])   # oldest first
        hdr = [c for c in self.fake.calls if "/v2/market-quote/quotes" in c[0]][0][2]
        self.assertEqual(hdr["Authorization"], "Bearer TOKEN1")

    def test_expired_token_message(self):
        self.login()
        self.u.universe()
        self.fake.expired = True
        with self.assertRaises(ProviderError) as cm:
            self.u.snapshot(["RELIANCE"])
        self.assertIn("Login with Upstox", str(cm.exception))
        self.assertFalse(self.u.status(NOW)["logged_in"])


class TestEngine(unittest.TestCase):
    def setUp(self):
        for f in os.listdir(TMP):
            p = os.path.join(TMP, f)
            os.remove(p) if os.path.isfile(p) else shutil.rmtree(p)
        self.e = engine_mod.Engine(data_dir=TMP)
        self.e.save_settings({"demo_speed": 12})

    def test_charges(self):
        ch = intraday_charges(55, 1358.48, 1374.96, config.DEFAULT_SETTINGS["charges"])
        self.assertAlmostEqual(ch["total"], 73.83, places=2)

    def test_demo_trade_lifecycle(self):
        e = self.e
        sym = "SUZLON"
        p = e.plan_for(sym)
        self.assertLessEqual(p["loss_at_stop"] or 0, 40.005)
        if not p["qty"]:
            self.skipTest("plan has no quantity today")
        pv = e.preview(sym, p["qty"], p["stop"], p["target"])
        if not pv["ok"]:
            self.skipTest("rules fail for today's demo path: %s" % [c["text"] for c in pv["checks"] if not c["ok"]])
        r = e.place({"symbol": sym, "qty": p["qty"], "stop": p["stop"], "target": p["target"]})
        pos = r["position"]
        with self.assertRaises(engine_mod.OrderError):
            e.modify(pos["id"], stop=pos["stop"] - 1)                  # loosening a stop is refused
        t = e.exit(pos["id"])
        acc = e.account()
        self.assertAlmostEqual(acc["cash"], 2000 + t["net"], places=2)
        self.assertEqual(len(e.state()["trades"]), 1)

    def test_rules_block_oversized(self):
        q = self.e.quote("SUZLON")
        pv = self.e.preview("SUZLON", 1000, round(q["ltp"] * 0.98, 2), round(q["ltp"] * 1.1, 2))
        self.assertFalse(pv["ok"])
        failed = " ".join(c["text"] for c in pv["checks"] if not c["ok"])
        self.assertIn("max", failed)

    def test_settings_switch_accounts(self):
        self.e.save_settings({"source": "upstox"})
        self.assertTrue(self.e.account_path.endswith("account.json") and "demo" not in self.e.account_path)
        self.assertFalse(self.e.provider.ready()[0])
        self.e.save_settings({"source": "demo"})
        self.assertTrue(self.e.account_path.endswith("demo-account.json"))


if __name__ == "__main__":
    unittest.main()
