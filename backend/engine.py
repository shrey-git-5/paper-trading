"""The paper broker: your rules, pretend orders, positions, automatic exits and the journal.

No real money moves here. Fills happen at the live price the data source reports
(or your limit price), and every exit books the real Indian intraday charges."""

import datetime
import os
import threading
import time

import config
from charges import intraday_charges
from market import Clock, SQUARE_OFF
from providers.base import ProviderError
from providers.demo import Demo
from providers.upstox import Upstox
from providers.angel import Angel
from util import inr, ist_now, read_json, round_tick, write_json

SQUARE_OFF_FEE = 59.0          # Rs 50 + 18% GST: what Zerodha charges when it squares off for you
LOCK = threading.RLock()


class OrderError(Exception):
    pass


class Engine:
    def __init__(self, data_dir=None, credentials_dir=None):
        self.data_dir = data_dir or config.DATA_DIR
        self.settings_file = os.path.join(self.data_dir, "settings.json")
        credential_dir = credentials_dir or self.data_dir
        self.upstox = Upstox(os.path.join(credential_dir, "secrets.json"), credential_dir)
        self.angel = Angel(credential_dir)
        self.cache = {}
        self.scan = {"running": False, "items": [], "error": None, "kind": None, "finished": None, "progress": ""}
        self.reload()

    # ------------------------------------------------------------ settings and source
    def settings(self):
        s = dict(config.DEFAULT_SETTINGS)
        s.update(read_json(self.settings_file, {}) or {})
        return s

    def save_settings(self, changes):
        cur = read_json(self.settings_file, {}) or {}
        nums = ("budget", "max_loss_per_trade_inr", "max_daily_loss_inr", "max_trades_per_day", "max_position_pct",
                "min_reward_risk", "min_price", "demo_speed")
        for k, v in (changes or {}).items():
            if k in nums and v not in (None, ""):
                cur[k] = float(v)
            elif k in ("no_entries_before", "no_entries_after", "flat_by", "owner") and v:
                cur[k] = str(v)
            elif k == "source" and v in ("demo", "upstox", "angel"):
                cur[k] = v
            elif k == "watchlist" and isinstance(v, list):
                cur[k] = [str(x).strip().upper() for x in v if str(x).strip()][:100]
            elif k == "charges" and isinstance(v, dict):
                c = dict(config.DEFAULT_SETTINGS["charges"])
                c.update({kk: float(vv) for kk, vv in v.items() if kk in c})
                cur[k] = c
        write_json(self.settings_file, cur)
        self.reload()
        return self.settings()

    def reload(self):
        s = self.settings()
        demo = s["source"] == "demo"
        old = getattr(self, "clock", None)
        if not (old and old.demo == demo and old.speed == float(s["demo_speed"])):
            self.clock = Clock(demo, s["demo_speed"], self.data_dir)
        self.provider = {"demo": Demo(self.clock), "upstox": self.upstox, "angel": self.angel}[s["source"]]
        self.account_path = os.path.join(self.data_dir, "demo-account.json" if demo else "account.json")
        self.cache = {}

    # ------------------------------------------------------------ account
    def account(self):
        acc = read_json(self.account_path)
        if acc is None:
            acc = self.new_account(self.settings()["budget"])
            write_json(self.account_path, acc)
        return acc

    def new_account(self, capital):
        return {"capital": float(capital), "cash": float(capital), "created": ist_now().isoformat(),
                "positions": [], "orders": [], "trades": [], "events": [], "seq": 0}

    def reset(self, capital):
        with LOCK:
            self.save_settings({"budget": capital})
            write_json(self.account_path, self.new_account(capital))

    def _id(self, acc, p):
        acc["seq"] = acc.get("seq", 0) + 1
        return "%s%d" % (p, acc["seq"])

    def _event(self, acc, text, kind="info"):
        acc["events"].insert(0, {"at": self.clock.now().strftime("%Y-%m-%d %H:%M:%S"), "text": text, "kind": kind})
        del acc["events"][300:]

    def _save(self, acc):
        write_json(self.account_path, acc)

    # ------------------------------------------------------------ prices
    def quote(self, sym, fresh=False):
        sym = sym.strip().upper().replace(".NS", "")
        hit = self.cache.get(sym)
        ttl = 3 if self.clock.demo else 15
        if hit and not fresh and time.time() - hit[0] < ttl:
            return hit[1]
        q = self.provider.quote(sym, self.clock.now())
        self.cache[sym] = (time.time(), q)
        return q

    def ltps(self, symbols):
        symbols = sorted(set(symbols))
        if not symbols:
            return {}
        try:
            snap = self.provider.snapshot(symbols)
        except ProviderError:
            return {}
        return {s: v["ltp"] for s, v in snap.items() if v.get("ltp")}

    def watchlist(self):
        syms = self.settings()["watchlist"]
        try:
            snap = self.provider.snapshot(syms)
        except ProviderError as e:
            return {"items": [{"symbol": s} for s in syms], "error": str(e)}
        return {"items": [dict(snap.get(s, {}), symbol=s) for s in syms], "error": None}

    # ------------------------------------------------------------ rules
    def _today(self):
        return self.clock.now().date().isoformat()

    def today_trades(self, acc):
        return [t for t in acc["trades"] if t["closed"][:10] == self._today()]

    def today_entries(self, acc):
        d = self._today()
        return ([p for p in acc["positions"] if p["opened"][:10] == d] +
                [t for t in acc["trades"] if t["opened"][:10] == d] +
                [o for o in acc["orders"] if o["placed"][:10] == d and o["status"] in ("open", "filled")
                 and not o.get("position")])

    def preview(self, sym, qty, stop, target, limit=None):
        acc, s = self.account(), self.settings()
        q = self.quote(sym)
        price = float(limit) if limit else q["ltp"]
        qty, stop, target = int(float(qty or 0)), float(stop or 0), float(target or 0)
        rates = s["charges"]
        checks = []

        def rule(ok, text):
            checks.append({"ok": bool(ok), "text": text})
        risk = price - stop if stop else None
        ch_stop = intraday_charges(qty, price, stop, rates)["total"] if stop and qty else 0
        ch_tgt = intraday_charges(qty, price, target, rates)["total"] if target and qty else 0
        loss = round(qty * risk + ch_stop, 2) if risk is not None else None
        gain = round(qty * (target - price) - ch_tgt, 2) if target else None
        cost = round(qty * price, 2)
        st = self.clock.status()
        now = self.clock.now()
        rule(st["open"], "Market open" if st["open"] else "Market is closed (%s)" % st.get("reason", ""))
        if not self.clock.demo:
            a, b = s["no_entries_before"], s["no_entries_after"]
            hm = now.strftime("%H:%M")
            rule(a <= hm <= b, "New trades only between %s and %s (now %s)" % (a, b, hm))
        rule(qty > 0, "Quantity is at least 1 share")
        rule(price >= float(s["min_price"]), "Price %s is at least your minimum %s" % (inr(price), inr(s["min_price"])))
        rule(stop and stop < price, "Stop-loss is below the buy price")
        rule(target and target > price, "Target is above the buy price")
        if risk and risk > 0:
            rule(risk >= price * 0.002 - 1e-9, "Stop-loss is at least 0.2%% below the price (%s); tighter stops get "
                 "hit by normal wiggles" % inr(round_tick(price * 0.002, down=False)))
        if risk and risk > 0 and target and qty and loss:
            rr = gain / loss if loss > 0 else 0
            rule(rr >= float(s["min_reward_risk"]) - 1e-9,
                 "After charges, possible gain is at least %gx the possible loss (now %.2fx)" % (s["min_reward_risk"], rr))
        if loss is not None:
            rule(loss <= float(s["max_loss_per_trade_inr"]) + 0.005,
                 "Loss if stop-loss hits %s (with charges) fits your max %s per trade" % (inr(loss), inr(s["max_loss_per_trade_inr"])))
        cap = float(acc["capital"]) * float(s["max_position_pct"]) / 100.0
        rule(cost <= acc["cash"] + 0.005, "Cost %s fits your available funds %s" % (inr(cost), inr(acc["cash"])))
        rule(cost <= cap + 0.005, "Cost fits your max %d%% in one trade (%s)" % (float(s["max_position_pct"]), inr(cap)))
        net_today = sum(t["net"] for t in self.today_trades(acc))
        rule(-net_today + (loss or 0) <= float(s["max_daily_loss_inr"]) + 0.005,
             "Today's loss so far %s plus this trade's worst case fits your daily max %s"
             % (inr(max(-net_today, 0)), inr(s["max_daily_loss_inr"])))
        n = len(self.today_entries(acc))
        rule(n < int(float(s["max_trades_per_day"])), "Trades today: %d of %d" % (n, int(float(s["max_trades_per_day"]))))
        best = 0
        if risk and risk > 0:
            limit_cash = min(acc["cash"], cap)
            for k in range(1, 200000):
                if k * risk + intraday_charges(k, price, stop, rates)["total"] > float(s["max_loss_per_trade_inr"]) + 0.005 \
                        or k * price > limit_cash + 0.005:
                    break
                best = k
        return {"symbol": q["symbol"], "ltp": q["ltp"], "price": round(price, 2), "qty": qty, "cost": cost,
                "stop": stop, "target": target, "loss_at_stop": loss, "gain_at_target": gain,
                "charges_at_stop": ch_stop, "charges_at_target": ch_tgt, "max_qty": best, "checks": checks,
                "ok": all(c["ok"] for c in checks), "available": acc["cash"]}

    def plan_for(self, sym, or_high=None, or_low=None, why=""):
        """A suggested stop (middle of the morning range), target (2x the risk) and the safe quantity."""
        q = self.quote(sym)
        bars = q.get("bars") or []
        if or_high is None and len(bars) >= 3:
            or_high, or_low = max(b["h"] for b in bars[:3]), min(b["l"] for b in bars[:3])
        entry = q["ltp"]
        stop = round_tick((or_high + or_low) / 2.0) if or_high else round_tick(entry * 0.99)
        if stop >= entry or entry - stop < entry * 0.002:
            stop = round_tick(min(stop, entry * 0.995))
        target = round_tick(entry + 2 * (entry - stop), down=False)
        p = self.preview(sym, 1, stop, target)
        qty = p["max_qty"]
        if qty:
            p = self.preview(sym, qty, stop, target)
        return {"symbol": sym, "ltp": entry, "stop": stop, "target": target, "qty": qty, "why": why,
                "or_high": or_high, "or_low": or_low, "loss_at_stop": p["loss_at_stop"],
                "gain_at_target": p["gain_at_target"], "ok": bool(qty) and p["ok"],
                "note": "" if qty else "even 1 share risks more than your max loss per trade",
                "failed": [c["text"] for c in p["checks"] if not c["ok"]]}

    # ------------------------------------------------------------ orders
    def place(self, body):
        with LOCK:
            sym = str(body.get("symbol") or "").strip().upper()
            typ = body.get("type") or "market"
            limit = float(body["limit"]) if typ == "limit" and body.get("limit") else None
            p = self.preview(sym, body.get("qty"), body.get("stop"), body.get("target"), limit)
            if not p["ok"]:
                raise OrderError("Rejected by your rules: " + "; ".join(c["text"] for c in p["checks"] if not c["ok"]))
            acc = self.account()
            now = self.clock.now().isoformat(timespec="seconds")
            if typ == "limit" and limit < p["ltp"]:
                o = {"id": self._id(acc, "O"), "symbol": sym, "qty": p["qty"], "limit": limit, "stop": p["stop"],
                     "target": p["target"], "placed": now, "status": "open"}
                acc["orders"].append(o)
                acc["cash"] = round(acc["cash"] - p["cost"], 2)
                self._event(acc, "Limit order placed: BUY %d %s at %s (waits for the price to come down)"
                            % (o["qty"], sym, inr(limit)), "order")
                self._save(acc)
                return {"order": o}
            fill = limit if limit else p["ltp"]
            pos = self._open(acc, sym, p["qty"], fill, p["stop"], p["target"], now)
            acc["orders"].append({"id": self._id(acc, "O"), "symbol": sym, "qty": p["qty"], "limit": None,
                                  "price": fill, "stop": p["stop"], "target": p["target"], "placed": now,
                                  "status": "filled", "position": pos["id"], "type": typ})
            self._save(acc)
            return {"position": pos}

    def _open(self, acc, sym, qty, price, stop, target, when):
        pos = {"id": self._id(acc, "P"), "symbol": sym, "qty": int(qty), "avg": round(float(price), 2),
               "stop": float(stop), "target": float(target), "opened": when}
        acc["positions"].append(pos)
        acc["cash"] = round(acc["cash"] - pos["qty"] * pos["avg"], 2)
        self._event(acc, "BOUGHT %d %s at %s. Stop-loss %s, target %s." % (pos["qty"], sym, inr(price), inr(stop),
                                                                          inr(target)), "buy")
        return pos

    def _close(self, acc, pos, price, reason, fee=0.0):
        ch = intraday_charges(pos["qty"], pos["avg"], price, self.settings()["charges"])["total"] + fee
        gross = round(pos["qty"] * (price - pos["avg"]), 2)
        net = round(gross - ch, 2)
        acc["cash"] = round(acc["cash"] + pos["qty"] * price - ch, 2)
        acc["positions"] = [p for p in acc["positions"] if p["id"] != pos["id"]]
        t = {"id": pos["id"], "symbol": pos["symbol"], "qty": pos["qty"], "buy": pos["avg"], "sell": round(price, 2),
             "stop": pos["stop"], "target": pos["target"], "opened": pos["opened"],
             "closed": self.clock.now().isoformat(timespec="seconds"), "reason": reason, "gross": gross,
             "charges": round(ch, 2), "net": net}
        acc["trades"].append(t)
        self._event(acc, "SOLD %d %s at %s (%s). Net %s after %s charges." % (pos["qty"], pos["symbol"], inr(price),
                                                                              reason, inr(net), inr(ch)), "sell")
        return t

    def exit(self, pid):
        with LOCK:
            acc = self.account()
            pos = next((p for p in acc["positions"] if p["id"] == pid), None)
            if not pos:
                raise OrderError("no open position %s" % pid)
            t = self._close(acc, pos, self.quote(pos["symbol"], fresh=True)["ltp"], "you exited")
            self._save(acc)
            return t

    def modify(self, pid, stop=None, target=None):
        with LOCK:
            acc = self.account()
            pos = next((p for p in acc["positions"] if p["id"] == pid), None)
            if not pos:
                raise OrderError("no open position %s" % pid)
            if stop not in (None, ""):
                if float(stop) < pos["stop"]:
                    raise OrderError("Moving a stop-loss further away only makes the loss bigger. Not allowed.")
                pos["stop"] = float(stop)
            if target not in (None, ""):
                pos["target"] = float(target)
            self._event(acc, "Modified %s: stop-loss %s, target %s" % (pos["symbol"], inr(pos["stop"]), inr(pos["target"])))
            self._save(acc)
            return pos

    def cancel(self, oid):
        with LOCK:
            acc = self.account()
            o = next((o for o in acc["orders"] if o["id"] == oid and o["status"] == "open"), None)
            if not o:
                raise OrderError("no open order %s" % oid)
            o["status"] = "cancelled"
            acc["cash"] = round(acc["cash"] + o["qty"] * o["limit"], 2)
            self._event(acc, "Cancelled the limit order for %s" % o["symbol"], "order")
            self._save(acc)
            return o

    # ------------------------------------------------------------ the broker's job: run every few seconds
    def tick(self):
        with LOCK:
            acc = self.account()
            open_orders = [o for o in acc["orders"] if o["status"] == "open"]
            if not acc["positions"] and not open_orders:
                return 0
            now = self.clock.now()
            prices = self.ltps([o["symbol"] for o in open_orders] + [p["symbol"] for p in acc["positions"]])
            changed = 0
            for o in open_orders:
                ltp = prices.get(o["symbol"])
                if now.time() >= SQUARE_OFF or o["placed"][:10] != now.date().isoformat():
                    o["status"] = "expired"
                    acc["cash"] = round(acc["cash"] + o["qty"] * o["limit"], 2)
                    self._event(acc, "Limit order for %s expired unfilled" % o["symbol"], "order")
                    changed += 1
                elif ltp is not None and ltp <= o["limit"]:
                    o["status"] = "filled"
                    acc["cash"] = round(acc["cash"] + o["qty"] * o["limit"], 2)
                    pos = self._open(acc, o["symbol"], o["qty"], o["limit"], o["stop"], o["target"],
                                     now.isoformat(timespec="seconds"))
                    o["position"] = pos["id"]
                    changed += 1
            for pos in list(acc["positions"]):
                ltp = prices.get(pos["symbol"])
                stale = pos["opened"][:10] != now.date().isoformat()
                if ltp is None and not stale:
                    continue
                ltp = ltp if ltp is not None else pos["avg"]
                if ltp <= pos["stop"]:
                    self._close(acc, pos, ltp, "stop-loss hit")          # fills at the market: can be below the stop
                elif ltp >= pos["target"]:
                    self._close(acc, pos, pos["target"], "target hit")
                elif now.time() >= SQUARE_OFF or stale:
                    self._close(acc, pos, ltp, "auto square-off at 3:20 PM (broker fee %s)" % inr(SQUARE_OFF_FEE),
                                fee=SQUARE_OFF_FEE)
                else:
                    continue
                changed += 1
            if changed:
                self._save(acc)
            return changed

    # ------------------------------------------------------------ the scanner
    def run_scan(self):
        s = self.settings()
        self.scan.update(running=True, error=None, progress="starting", started=self.clock.now().strftime("%H:%M:%S"))
        try:
            ok, why = self.provider.ready()
            if not ok:
                raise ProviderError(why)
            syms = [u["symbol"] for u in self.provider.universe()]
            self.scan["progress"] = "prices for %d stocks" % len(syms)
            snap = self.provider.snapshot(syms)
            minp = float(s["min_price"])
            live = [(k, v) for k, v in snap.items() if v.get("ltp") and v["ltp"] >= minp and v.get("open")]
            now = self.clock.now()
            if not self.clock.status()["open"] or now.time() < datetime.time(9, 35):
                movers = sorted(live, key=lambda kv: -(kv[1].get("pct") or 0))[:25]
                items = [{"symbol": k, "ltp": v["ltp"], "watch_only": True,
                          "why": "%+.2f%% today" % (v.get("pct") or 0)} for k, v in movers]
                kind = "Biggest movers (breakouts are checked from 9:35 AM on a trading day)"
            else:
                cands = [(k, v) for k, v in live if v["ltp"] > v["open"]
                         and (self.clock.demo or v["ltp"] * (v.get("volume") or 0) >= 1e7)]
                cands.sort(key=lambda kv: -(kv[1]["ltp"] * (kv[1].get("volume") or 0)))
                cands = cands[:40]
                items = []
                for i, (k, v) in enumerate(cands):
                    self.scan["progress"] = "checking candles %d of %d" % (i + 1, len(cands))
                    try:
                        bars = self.provider.candles(k, now)
                    except ProviderError:
                        continue
                    if len(bars) < 4:
                        continue
                    oh, ol = max(b["h"] for b in bars[:3]), min(b["l"] for b in bars[:3])
                    hit = next((b for b in bars[3:] if b["c"] > oh), None)
                    if not hit:
                        continue
                    self.cache[k] = (time.time(), dict(v, symbol=k, bars=bars, source=self.provider.label))
                    try:
                        items.append(self.plan_for(k, oh, ol, "Broke above its 9:15–9:30 high %s at %s, %+.2f%% today"
                                                   % (inr(oh), hit["t"], v.get("pct") or 0)))
                    except ProviderError:
                        continue
                items.sort(key=lambda x: (not x["ok"], -(x.get("gain_at_target") or 0)))
                kind = "Today's breakouts (checked the %d most-traded stocks that are up today)" % len(cands)
            self.scan.update(items=items, kind=kind)
        except Exception as e:  # shown to you in the app
            self.scan.update(error=str(e), items=[])
        finally:
            self.scan.update(running=False, finished=self.clock.now().strftime("%H:%M:%S"), progress="")

    # ------------------------------------------------------------ everything the screens need
    def state(self):
        s = self.settings()
        acc = self.account()
        prices = self.ltps([p["symbol"] for p in acc["positions"]])
        positions, unreal = [], 0.0
        for p in acc["positions"]:
            ltp = prices.get(p["symbol"], p["avg"])
            pnl = round(p["qty"] * (ltp - p["avg"]), 2)
            unreal += pnl
            positions.append(dict(p, ltp=ltp, pnl=pnl))
        trades = acc["trades"]
        wins = [t for t in trades if t["net"] > 0]
        losses = [t for t in trades if t["net"] <= 0]
        blocked = sum(o["qty"] * o["limit"] for o in acc["orders"] if o["status"] == "open")
        invested = sum(p["qty"] * p["avg"] for p in acc["positions"])
        today = self.today_trades(acc)
        ok, why = self.provider.ready()
        return {
            "market": self.clock.status(), "settings": s,
            "source": {"name": self.provider.name, "label": self.provider.label, "ready": ok, "message": why},
            "upstox": self.upstox.status(ist_now()), "angel": {"saved": self.angel.c.configured()},
            "funds": {"capital": acc["capital"], "available": acc["cash"], "invested": round(invested, 2),
                      "blocked": round(blocked, 2), "unrealised": round(unreal, 2),
                      "value": round(acc["cash"] + invested + blocked + unreal, 2)},
            "pnl": {"today": round(sum(t["net"] for t in today), 2), "all": round(sum(t["net"] for t in trades), 2),
                    "charges": round(sum(t["charges"] for t in trades), 2), "trades": len(trades), "wins": len(wins),
                    "avg_win": round(sum(t["net"] for t in wins) / len(wins), 2) if wins else 0,
                    "avg_loss": round(sum(t["net"] for t in losses) / len(losses), 2) if losses else 0,
                    "trades_today": len(self.today_entries(acc))},
            "positions": positions,
            "orders": list(reversed([o for o in acc["orders"] if o["placed"][:10] == self._today()])),
            "trades": list(reversed(trades))[:300], "events": acc["events"][:60],
            "scan": dict(self.scan),
        }
