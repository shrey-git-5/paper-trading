"""Where things live and the default rules. Everything can be changed with environment
variables, which is how the same code runs on your Mac and on Google Cloud Run.

  DATA_DIR        folder for your account, settings and keys (default: ./data)
  PORT            web port (default 8765; Cloud Run sets this itself)
  HOST            127.0.0.1 locally (only this computer can open it); 0.0.0.0 in the cloud
  APP_PASSWORD    if set, the app asks for this password before showing anything (required in the cloud)
  TICK_TOKEN      if set, POST /api/tick with header X-Tick-Token runs the stop-loss / target check
                  (Cloud Scheduler calls this every minute so exits happen even when nobody has the app open)
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR") or os.path.join(ROOT, "data"))
PORT = int(os.environ.get("PORT") or 8765)
HOST = os.environ.get("HOST") or "127.0.0.1"
APP_PASSWORD = os.environ.get("APP_PASSWORD") or ""
TICK_TOKEN = os.environ.get("TICK_TOKEN") or ""

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
SECRETS_FILE = os.path.join(DATA_DIR, "secrets.json")


def account_file(source):
    """Demo money and the live drill never mix."""
    return os.path.join(DATA_DIR, "demo-account.json" if source == "demo" else "account.json")


DEFAULT_SETTINGS = {
    "owner": "Shrey",
    "source": "demo",                 # demo | upstox | angel
    "budget": 2000,
    "max_loss_per_trade_inr": 40,     # 2% of 2,000
    "max_daily_loss_inr": 120,
    "max_trades_per_day": 3,
    "max_position_pct": 90,
    "min_reward_risk": 1.5,
    "min_price": 20,
    "no_entries_before": "09:30",
    "no_entries_after": "14:30",
    "flat_by": "15:10",
    "demo_speed": 12,
    "watchlist": ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "TATASTEEL",
                  "TATAPOWER", "IRFC", "NHPC", "SUZLON", "PNB", "ONGC", "WIPRO"],
    "charges": {"brokerage_pct": 0.03, "brokerage_cap_inr": 20, "stt_sell_pct": 0.025, "exchange_pct": 0.00307,
                "sebi_inr_per_crore": 10, "stamp_buy_pct": 0.003, "ipft_inr_per_crore": 0.01, "gst_pct": 18},
}
