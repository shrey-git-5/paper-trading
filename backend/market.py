"""The NSE clock: trading days, session hours, and a fast pretend clock for demo mode."""

import datetime
import os
import time

from util import ist_now, read_json

OPEN, CLOSE = datetime.time(9, 15), datetime.time(15, 30)
SQUARE_OFF = datetime.time(15, 20)        # brokers square off intraday positions around 3:15-3:25 PM

NSE_HOLIDAYS = {  # NSE equity trading holidays, NSE circular for 2026
    "2026-01-15": "Municipal Corporation Election in Maharashtra", "2026-01-26": "Republic Day",
    "2026-03-03": "Holi", "2026-03-26": "Shri Ram Navami", "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday", "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti", "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id", "2026-06-26": "Muharram", "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti", "2026-10-20": "Dussehra", "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev", "2026-12-25": "Christmas",
}


def holidays(data_dir):
    """The built-in 2026 list plus anything in DATA_DIR/holidays.json (add 2027 when NSE publishes it)."""
    h = dict(NSE_HOLIDAYS)
    extra = read_json(os.path.join(data_dir, "holidays.json"), {}) or {}
    h.update({str(k): str(v) for k, v in extra.items() if not str(k).startswith("_")})
    return h


class Clock:
    """Live: the real time in India. Demo: a pretend session that starts at 9:30 and runs `speed` times faster."""

    def __init__(self, demo=False, speed=12.0, data_dir="."):
        self.demo, self.speed, self.t0, self.data_dir = demo, float(speed), time.time(), data_dir

    def now(self):
        if not self.demo:
            return ist_now()
        mins = ((time.time() - self.t0) * self.speed / 60.0) % 375 + 15
        return datetime.datetime.combine(ist_now().date(), OPEN) + datetime.timedelta(minutes=mins)

    def trading_day(self, d):
        if d.weekday() >= 5:
            return False, "weekend"
        name = holidays(self.data_dir).get(d.isoformat())
        return (False, "NSE holiday: " + name) if name else (True, "")

    def status(self):
        n = self.now()
        if self.demo:
            return {"open": True, "demo": True, "reason": "demo market: pretend prices, %gx speed" % self.speed,
                    "now": n.strftime("%H:%M:%S"), "date": n.date().isoformat()}
        ok, why = self.trading_day(n.date())
        st = {"open": False, "demo": False, "reason": why, "now": n.strftime("%a %d %b, %H:%M:%S"),
              "date": n.date().isoformat(), "opens": "09:15", "closes": "15:30"}
        if ok:
            if OPEN <= n.time() < CLOSE:
                st.update(open=True, reason="regular session")
            else:
                st["reason"] = "before the open" if n.time() < OPEN else "after the close"
        d = n.date() if (ok and n.time() < OPEN) else n.date() + datetime.timedelta(days=1)
        for _ in range(15):
            if self.trading_day(d)[0]:
                st["next_open"] = "%s 09:15" % d.strftime("%a %d %b")
                break
            d += datetime.timedelta(days=1)
        return st
