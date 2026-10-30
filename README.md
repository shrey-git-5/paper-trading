# Paper Trader

Practice intraday trading on NSE with pretend money and real prices. A Python backend with a
browser front end, laid out like a broker's app: watchlist on the left, charts, a buy window,
positions, orders and a journal. Nothing here can place a real order.

## Run it on your Mac

Double-click **Start Paper Trader.command** in Documents/IndianTrader, or:

```bash
cd ~/Documents/IndianTrader/paper-trader
DATA_DIR=~/Documents/IndianTrader/trader/app-data python3 backend/server.py
```

then open http://localhost:8765. Python 3.8+ only; nothing to install. Keep the Terminal window open
while you use the app (closing it stops the app).

## Live prices

Settings > Live prices: **Demo market** (pretend, any time), **Upstox** or **Angel One** (real NSE
prices, free with an account at that broker).

Upstox, once: on https://account.upstox.com/developer/apps create an app with the redirect URL shown
in Settings (locally `http://localhost:8765/upstox/callback`), paste its API key and secret into
Settings, click **Save and log in**. Then each trading morning click **Log in with Upstox**: Upstox
access tokens end at 3:30 AM. If Upstox won't accept a localhost redirect URL, use the app's
**Generate** button on that developer page and paste the token under "Or paste today's access token".

Keys are stored only in the data folder (`secrets.json`, readable by your user only).

## What's where

```
backend/                Python, standard library only
  server.py             web server: pages, /api/*, Upstox login round-trip, password, background watcher
  engine.py             the paper broker: rules, orders, positions, exits, journal, scanner
  charges.py            NSE intraday charges (brokerage, STT, exchange, SEBI, stamp duty, GST)
  market.py             NSE hours, 2026 holidays (+ data/holidays.json), the fast demo clock
  config.py             paths, environment variables, default rules
  util.py               rupee formatting, IST time, safe JSON files
  providers/            where prices come from: demo.py, upstox.py, angel.py (+ angel_client.py)
frontend/
  index.html            the shell (top bar, watchlist, main view, order window)
  login.html            password screen (cloud only)
  css/styles.css        all styling, light and dark
  js/app.js             routing, watchlist, search, notifications
  js/views.js           dashboard, stock, scanner, positions, orders, journal, settings
  js/order.js           the buy window and its risk bar
  js/chart.js           5-minute candle chart
  js/api.js, format.js  talking to the backend; rupee and number formatting
tests/                  python3 -m unittest discover -s tests -v
Dockerfile, deploy/     Google Cloud Run (see deploy/CLOUD.md)
```

## The rules it enforces

Every buy needs a stop-loss and a target; the loss at the stop-loss **including charges** must fit
your max loss per trade; the possible gain after charges must be at least your minimum multiple of
the loss; daily loss limit; trades per day; no new trades before 9:30 or after 14:30; stop-losses can
be raised but never lowered. The app sells automatically at the stop-loss (at the market price, which
can be worse), at the target, and at 3:20 PM with the ₹59 fee a broker charges for squaring off.

Education and practice, not financial advice.
