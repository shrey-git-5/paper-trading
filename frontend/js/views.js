// Every screen. Each view returns { html, mount(ctx) } and gets the latest state from the app.

import { api } from "./api.js";
import { drawChart } from "./chart.js";
import { openOrder } from "./order.js";
import { inr, signed, price, pct, tone, esc, timeOf, dateOf } from "./format.js";

const $ = (id) => document.getElementById(id);

function ruleLine(label, value) { return `<li><span>${label}</span><b>${value}</b></li>`; }

// ---------------------------------------------------------------- dashboard
export function dashboard(S, app) {
  const f = S.funds, p = S.pnl, s = S.settings, m = S.market;
  const hour = parseInt((m.now || "").match(/(\d\d):/)?.[1] || "12", 10);
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const winRate = p.trades ? Math.round(100 * p.wins / p.trades) : null;
  return {
    html: `
    <div class="page-head"><div><div class="hello">${greet}, ${esc(s.owner || "Shrey")}</div>
      <p>${m.demo ? "Demo market: pretend prices that run fast, open any time." : m.open ? "NSE is open. New trades allowed " + esc(s.no_entries_before) + " to " + esc(s.no_entries_after) + "." : "NSE is closed (" + esc(m.reason) + ")" + (m.next_open ? ". Opens " + esc(m.next_open) + "." : ".")}</p></div>
      <a class="btn buy" href="#/scanner">Find a trade</a></div>
    <div class="grid-3">
      <div class="panel figure"><div class="label">Account value</div><div class="value">${inr(f.value)}</div>
        <div class="sub">Started with ${inr(f.capital)}</div></div>
      <div class="panel figure"><div class="label">Available to trade</div><div class="value">${inr(f.available)}</div>
        <div class="sub">${f.invested ? inr(f.invested) + " in open positions" : "Nothing open right now"}</div></div>
      <div class="panel figure"><div class="label">Today's result</div><div class="value ${tone(p.today + f.unrealised)}">${signed(p.today + f.unrealised)}</div>
        <div class="sub">${signed(p.today)} closed, ${signed(f.unrealised)} open</div></div>
    </div>
    <div class="grid-2" style="margin-top:16px">
      <section class="panel"><div class="panel-head"><h2>How the practice is going</h2><a href="#/journal">Journal</a></div>
        <div class="panel-body">${p.trades ? `<ul class="rules">
          ${ruleLine("Trades closed", p.trades)}
          ${ruleLine("Won", `${p.wins} (${winRate}%)`)}
          ${ruleLine("Average win", `<span class="up">${signed(p.avg_win)}</span>`)}
          ${ruleLine("Average loss", `<span class="down">${signed(p.avg_loss)}</span>`)}
          ${ruleLine("Charges paid", inr(p.charges))}
          ${ruleLine("Net result", `<span class="${tone(p.all)}">${signed(p.all)}</span>`)}</ul>
          <p class="muted" style="margin:10px 0 0">The number that matters after 20–30 trades: is the net result above zero after charges?</p>`
          : `<div class="empty"><b>No trades yet.</b> Open the scanner, pick a breakout, and place your first practice trade.</div>`}</div></section>
      <section class="panel"><div class="panel-head"><h2>Your rules</h2><a href="#/settings">Change</a></div>
        <div class="panel-body"><ul class="rules">
          ${ruleLine("Max loss per trade", inr(s.max_loss_per_trade_inr) + ` <span class="muted">(${(100 * s.max_loss_per_trade_inr / f.capital).toFixed(1)}% of capital)</span>`)}
          ${ruleLine("Max loss per day", inr(s.max_daily_loss_inr))}
          ${ruleLine("Trades per day", `${p.trades_today} of ${s.max_trades_per_day} used`)}
          ${ruleLine("Gain must be at least", `${s.min_reward_risk}× the loss`)}
          ${ruleLine("New trades", `${esc(s.no_entries_before)} to ${esc(s.no_entries_after)}`)}
          ${ruleLine("Prices from", esc(S.source.label))}</ul></div></section>
    </div>
    ${S.positions.length ? positionsPanel(S) : ""}`,
    mount() { bindPositionButtons(); },
  };
}

// ---------------------------------------------------------------- one stock
export function stock(S, symbol, app) {
  return {
    html: `
    <div class="page-head"><div class="quote-head"><span class="sym">${esc(symbol)}</span><span class="ltp" id="q-ltp">…</span><span id="q-chg"></span></div>
      <div style="display:flex;gap:8px"><button class="btn" id="q-watch" type="button"></button><button class="btn buy" id="q-buy" type="button">Buy</button></div></div>
    <section class="panel"><div class="panel-head"><h2>Today, 5-minute candles</h2><span class="muted" id="q-src"></span></div>
      <div class="chart-wrap"><svg id="chart" role="img" aria-label="${esc(symbol)} candle chart for today"></svg></div>
      <div class="chart-key"><span><i style="border-color:var(--muted)"></i>Morning range, 9:15 to 9:30</span>
        <span><i style="border-color:var(--down)"></i>Your stop-loss</span><span><i style="border-color:var(--up)"></i>Your target</span></div></section>
    <section class="panel"><div class="panel-body explain"><details><summary>How to read this chart</summary><div style="margin-top:10px">
      <p>Each bar is a candle covering 5 minutes. Green means the price ended those 5 minutes higher than it started; red means lower. The thin line shows the highest and lowest price inside those 5 minutes.</p>
      <p>The shaded band is the morning range: the high and low of the first 15 minutes. When a candle closes above the top of that band, it's a breakout. Breakouts often keep going up, but not always, which is why every trade needs a stop-loss.</p>
      <p>Hover a candle to see its four prices: open, high, low, close.</p></div></details></div></section>`,
    async mount() {
      const pos = S.positions.find(p => p.symbol === symbol);
      const inList = S.settings.watchlist.includes(symbol);
      $("q-watch").textContent = inList ? "Remove from watchlist" : "Add to watchlist";
      $("q-watch").onclick = async () => {
        const list = inList ? S.settings.watchlist.filter(x => x !== symbol) : [...S.settings.watchlist, symbol];
        await api.saveWatchlist(list); app.refresh(true); app.render();
      };
      $("q-buy").onclick = () => openOrder(symbol, {}, app.done);
      const load = async () => {
        try {
          const q = await api.quote(symbol);
          if (!$("chart")) return;
          $("q-ltp").textContent = inr(q.ltp, { keepZeros: true });
          if (q.prev_close) { const d = q.ltp - q.prev_close; $("q-chg").innerHTML = `<span class="${tone(d)}">${signed(d)} (${pct(100 * d / q.prev_close)})</span> <span class="muted">today</span>`; }
          $("q-src").textContent = q.source + (q.as_of ? ", " + q.as_of : "");
          drawChart($("chart"), q, pos ? { stop: pos.stop, target: pos.target } : {});
        } catch (e) { $("q-ltp").textContent = ""; $("q-chg").innerHTML = `<span class="down">${esc(e.message)}</span>`; drawChart($("chart"), null); }
      };
      await load();
      return setInterval(load, S.market.demo ? 4000 : 15000);
    },
  };
}

// ---------------------------------------------------------------- scanner
export function scanner(S, app) {
  const sc = S.scan;
  const rows = sc.items || [];
  return {
    html: `
    <div class="page-head"><div><h1>Scanner</h1><p>Checks every NSE stock for a breakout: a 5-minute candle closing above the high of the first 15 minutes (9:15 to 9:30). Each suggestion comes with a stop-loss, a target and a quantity sized to your max loss.</p></div>
      <button class="btn buy" id="scan-btn" type="button" ${sc.running ? "disabled" : ""}>${sc.running ? "Scanning, " + esc(sc.progress || "please wait") : "Scan all stocks"}</button></div>
    <section class="panel"><div class="panel-head"><h2>${esc(sc.kind || "Results")}</h2><span class="muted">${sc.finished ? "Last scan " + esc(sc.finished) : ""}</span></div>
      ${sc.error ? `<div class="empty down">${esc(sc.error)}</div>` :
        !rows.length ? `<div class="empty">${sc.finished ? "<b>Nothing matched.</b> No setup is a perfectly good answer; forcing trades is how money gets lost." : "<b>No scan yet.</b> Best run after 9:35 AM, when the first breakouts can show up."}</div>` :
        `<div class="table-wrap"><table><thead><tr><th>Stock</th><th class="num">Price</th><th>Why</th>${rows[0].watch_only ? "" : `<th class="num">Qty</th><th class="num">Stop-loss</th><th class="num">Target</th><th class="num">Risk</th><th class="num">Reward</th><th>Your rules</th>`}<th></th></tr></thead><tbody>
        ${rows.map((r, i) => `<tr><td><a href="#/stock/${encodeURIComponent(r.symbol)}"><b>${esc(r.symbol)}</b></a></td><td class="num">${price(r.ltp)}</td><td class="muted">${esc(r.why)}</td>
          ${r.watch_only ? "" : `<td class="num">${r.qty}</td><td class="num">${price(r.stop)}</td><td class="num">${price(r.target)}</td>
          <td class="num down">${r.qty ? inr(r.loss_at_stop) : "–"}</td><td class="num up">${r.qty ? inr(r.gain_at_target) : "–"}</td>
          <td>${r.ok ? `<span class="tag ok">Fits</span>` : `<span class="tag no" title="${esc((r.failed || []).join("; ") || r.note)}">Doesn't fit</span>`}</td>`}
          <td>${r.watch_only ? `<a class="btn small" href="#/stock/${encodeURIComponent(r.symbol)}">Chart</a>` : `<button class="btn small buy" data-i="${i}" type="button">Trade</button>`}</td></tr>`).join("")}
        </tbody></table></div>`}
    </section>`,
    mount() {
      $("scan-btn").onclick = async () => { await api.scan(); app.refresh(true).then(app.render); };
      document.querySelectorAll("[data-i]").forEach(b => b.onclick = () => {
        const r = rows[+b.dataset.i];
        openOrder(r.symbol, { qty: r.qty, stop: r.stop, target: r.target }, app.done);
      });
      if (sc.running) return setInterval(() => app.refresh(true).then(() => { if (!app.state.scan.running) app.render(); else $("scan-btn").textContent = "Scanning, " + (app.state.scan.progress || "please wait"); }), 1500);
    },
  };
}

// ---------------------------------------------------------------- positions
function positionsPanel(S) {
  const rows = S.positions;
  const total = rows.reduce((a, p) => a + p.pnl, 0);
  return `<section class="panel" style="margin-top:16px"><div class="panel-head"><h2>Open positions (${rows.length})</h2><b class="${tone(total)}">${signed(total)}</b></div>
    ${rows.length ? `<div class="table-wrap"><table><thead><tr><th>Stock</th><th class="num">Qty</th><th class="num">Avg. price</th><th class="num">Last price</th><th class="num">P&amp;L</th><th class="num">Stop-loss</th><th class="num">Target</th><th></th></tr></thead><tbody>
      ${rows.map(p => `<tr><td><a href="#/stock/${encodeURIComponent(p.symbol)}"><b>${esc(p.symbol)}</b></a> <span class="tag">MIS</span></td>
        <td class="num">${p.qty}</td><td class="num">${price(p.avg)}</td><td class="num">${price(p.ltp)}</td>
        <td class="num ${tone(p.pnl)}"><b>${signed(p.pnl)}</b></td>
        <td class="num">${price(p.stop)} <button class="linklike" data-trail="${p.id}" data-stop="${p.stop}" data-ltp="${p.ltp}" type="button" title="Move the stop-loss up to protect profit">raise</button></td>
        <td class="num">${price(p.target)}</td>
        <td><button class="btn small sell" data-exit="${p.id}" data-sym="${esc(p.symbol)}" type="button">Exit</button></td></tr>`).join("")}
      </tbody></table></div>
      <p class="muted" style="margin:0;padding:10px 18px 14px">The app sells automatically at your stop-loss or target. Anything still open at 3:20 PM is squared off, with the ₹59 fee a broker charges for that.</p>`
      : `<div class="empty">Nothing open. Positions appear here after you buy.</div>`}</section>`;
}

let appRef = null;
export function setApp(app) { appRef = app; }
function bindPositionButtons() {
  document.querySelectorAll("[data-exit]").forEach(b => b.onclick = async () => {
    if (!confirm(`Exit ${b.dataset.sym} now at the current price?`)) return;
    try { const t = await api.exit(b.dataset.exit); appRef.done(`Sold ${t.symbol}: ${signed(t.net)} after ${inr(t.charges)} charges`, t.net >= 0 ? "good" : "bad"); }
    catch (e) { appRef.done(e.message, "bad"); }
  });
  document.querySelectorAll("[data-trail]").forEach(b => b.onclick = async () => {
    const v = prompt(`Raise the stop-loss to protect profit.\nNow ${b.dataset.stop}, last price ${b.dataset.ltp}.\nNew stop-loss (higher than now, lower than the last price):`);
    if (!v) return;
    try { await api.modify(b.dataset.trail, +v); appRef.done("Stop-loss raised to " + inr(+v), "good"); } catch (e) { appRef.done(e.message, "bad"); }
  });
}

export function positions(S, app) {
  appRef = app;
  return { html: `<div class="page-head"><div><h1>Positions</h1><p>Shares you hold right now, with live profit or loss.</p></div></div>${positionsPanel(S).replace('style="margin-top:16px"', "")}`,
    mount() { bindPositionButtons(); return setInterval(() => app.refresh(true).then(app.render), S.market.demo ? 2500 : 8000); } };
}

// ---------------------------------------------------------------- orders
export function orders(S, app) {
  const rows = S.orders;
  return {
    html: `<div class="page-head"><div><h1>Orders</h1><p>Today's orders. A limit order waits until the price comes down to it, and expires unfilled at 3:20 PM.</p></div></div>
    <section class="panel">${rows.length ? `<div class="table-wrap"><table><thead><tr><th>Time</th><th>Stock</th><th>Type</th><th class="num">Qty</th><th class="num">Price</th><th>Status</th><th></th></tr></thead><tbody>
      ${rows.map(o => `<tr><td class="muted">${timeOf(o.placed)}</td><td><b>${esc(o.symbol)}</b></td><td>BUY ${o.limit ? "limit" : "market"}</td><td class="num">${o.qty}</td>
        <td class="num">${price(o.limit || o.price)}</td><td><span class="tag ${o.status === "filled" ? "ok" : o.status === "open" ? "warn" : ""}">${esc(o.status)}</span></td>
        <td>${o.status === "open" ? `<button class="btn small" data-cancel="${o.id}" type="button">Cancel</button>` : ""}</td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty">No orders today.</div>`}</section>
    <section class="panel"><div class="panel-head"><h2>Activity</h2></div>
      ${S.events.length ? `<div class="table-wrap"><table><tbody>${S.events.map(e => `<tr><td class="muted" style="width:90px">${esc(e.at.slice(11, 16))}</td><td style="white-space:normal">${esc(e.text)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">Nothing yet.</div>`}</section>`,
    mount() {
      document.querySelectorAll("[data-cancel]").forEach(b => b.onclick = async () => { await api.cancel(b.dataset.cancel); app.done("Order cancelled"); });
    },
  };
}

// ---------------------------------------------------------------- journal
export function journal(S) {
  const t = S.trades, p = S.pnl;
  const byReason = {};
  t.forEach(x => { const k = x.reason.startsWith("auto square-off") ? "square-off" : x.reason; byReason[k] = (byReason[k] || 0) + 1; });
  return {
    html: `<div class="page-head"><div><h1>Journal</h1><p>Every closed practice trade, after charges. This is the honest scorecard.</p></div></div>
    <div class="grid-3">
      <div class="panel figure"><div class="label">Net result</div><div class="value ${tone(p.all)}">${signed(p.all)}</div><div class="sub">${p.trades} trades, ${p.wins} won</div></div>
      <div class="panel figure"><div class="label">Average win vs average loss</div><div class="value"><span class="up">${signed(p.avg_win)}</span> <span class="muted" style="font-size:16px">vs</span> <span class="down">${signed(p.avg_loss)}</span></div><div class="sub">Wins should be bigger than losses</div></div>
      <div class="panel figure"><div class="label">Charges paid</div><div class="value">${inr(p.charges)}</div><div class="sub">${Object.entries(byReason).map(([k, v]) => `${v} ${esc(k)}`).join(", ") || "No exits yet"}</div></div>
    </div>
    <section class="panel" style="margin-top:16px">${t.length ? `<div class="table-wrap"><table><thead><tr><th>Date</th><th>Stock</th><th class="num">Qty</th><th class="num">Bought</th><th class="num">Sold</th><th>How it closed</th><th class="num">Charges</th><th class="num">Net</th></tr></thead><tbody>
      ${t.map(x => `<tr><td class="muted">${dateOf(x.closed)} ${timeOf(x.closed)}</td><td><b>${esc(x.symbol)}</b></td><td class="num">${x.qty}</td><td class="num">${price(x.buy)}</td><td class="num">${price(x.sell)}</td>
        <td>${esc(x.reason)}</td><td class="num muted">${inr(x.charges)}</td><td class="num ${tone(x.net)}"><b>${signed(x.net)}</b></td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty"><b>No closed trades yet.</b> After each trade, come back here: the journal is where you learn whether the method works.</div>`}</section>`,
    mount() {},
  };
}

// ---------------------------------------------------------------- settings
export function settings(S, app, params) {
  const s = S.settings, u = S.upstox;
  const redirect = u.redirect_uri || (location.origin + "/upstox/callback");
  const flash = params.get("upstox");
  const src = s.source;
  const pick = (v, title, desc) => (S.identity && ((S.identity.mode === "demo" && v !== "demo") || (S.identity.mode === "paper" && v === "demo"))) ? "" : `<label class="${src === v ? "on" : ""}"><input type="radio" name="src" value="${v}" ${src === v ? "checked" : ""}><b>${title}</b><small>${desc}</small></label>`;
  return {
    html: `<div class="page-head"><div><h1>Settings</h1><p>Your rules, and where live prices come from.</p></div></div>
    ${flash ? `<div class="panel" style="margin-bottom:16px"><div class="panel-body ${flash === "ok" ? "up" : "down"}">${flash === "ok" ? "Connected to Upstox. Live prices are on." : "Upstox login failed: " + esc(flash)}</div></div>` : ""}
    <section class="panel"><div class="panel-head"><h2>Live prices</h2><span class="tag ${S.source.ready ? "ok" : "warn"}">${esc(S.source.label)}${S.source.ready ? "" : ": not ready"}</span></div>
      <div class="panel-body">
        <div class="source-pick">
          ${pick("demo", "Demo market", "Pretend prices, open any time, 12× speed. For learning the app. Separate pretend account.")}
          ${pick("upstox", "Upstox", "Real NSE prices, free with an Upstox account. Log in once each trading day.")}
          ${pick("angel", "Angel One", "Real NSE prices, free with an Angel One account.")}
        </div>
        ${!S.source.ready ? `<p class="down" style="margin:12px 0 0">${esc(S.source.message)}</p>` : ""}
      </div></section>

    <section class="panel" id="upstox"><div class="panel-head"><h2>Upstox</h2>
      <span class="tag ${u.logged_in ? "ok" : u.app_saved ? "warn" : ""}">${u.logged_in ? "Logged in" + (u.user ? " as " + esc(u.user) : "") : u.app_saved ? "Login needed today" : "Not set up"}</span></div>
      <div class="panel-body">
        <ol class="steps">
          <li>Open <a href="https://account.upstox.com/developer/apps" target="_blank" rel="noopener">account.upstox.com/developer/apps</a> and click <b>New App</b>.</li>
          <li>App name: <b>Paper Trader</b>. Redirect URL: <code id="u-redir-copy">${esc(redirect)}</code>. Leave the postback/notifier URL empty if allowed.</li>
          <li>Copy the <b>API Key</b> and <b>API Secret</b> it shows into the boxes below, then click <b>Save and log in</b>.</li>
          <li>You'll sign in on Upstox's own page and come back here. Repeat the login each trading morning; Upstox tokens end at 3:30 AM.</li>
        </ol>
        <div class="form-grid" style="margin-top:14px">
          <div class="field"><label for="u-key">API key</label><input id="u-key" autocomplete="off" value="${esc(u.api_key || "")}"></div>
          <div class="field"><label for="u-secret">API secret</label><input id="u-secret" type="password" autocomplete="off" placeholder="${u.app_saved ? "saved (leave empty to keep)" : ""}"></div>
          <div class="field"><label for="u-redir">Redirect URL</label><input id="u-redir" autocomplete="off" value="${esc(redirect)}"><div class="hint">Must match the app's redirect URL exactly.</div></div>
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px">
          <button class="btn buy" id="u-save" type="button">${u.app_saved ? "Save and log in again" : "Save and log in"}</button>
          ${u.app_saved ? `<a class="btn" href="/upstox/login">Log in with Upstox</a>` : ""}
          ${u.app_saved ? `<button class="btn ghost" id="u-forget" type="button">Disconnect</button>` : ""}
        </div>
        <details style="margin-top:14px"><summary>Or paste today's access token</summary>
          <p class="muted">On the Upstox developer page, your app has a <b>Generate</b> button that makes a token for today. Paste it here.</p>
          <div style="display:flex;gap:10px"><input id="u-token" class="grow" style="flex:1;padding:9px 11px;border:1px solid var(--line);border-radius:6px" autocomplete="off" type="password"><button class="btn" id="u-token-save" type="button">Use token</button></div></details>
        <p class="muted" style="margin:12px 0 0">Your key and secret are saved only on the computer running this app (in its data folder, readable by your user only). This app only reads prices; it never places real orders.</p>
      </div></section>

    <section class="panel"><div class="panel-head"><h2>Angel One</h2><span class="tag ${S.angel.saved ? "ok" : ""}">${S.angel.saved ? "Saved" : "Not set up"}</span></div>
      <div class="panel-body"><div class="form-grid">
        <div class="field"><label for="a-key">SmartAPI key</label><input id="a-key" autocomplete="off"></div>
        <div class="field"><label for="a-client">Client code</label><input id="a-client" autocomplete="off"></div>
        <div class="field"><label for="a-pin">Login PIN</label><input id="a-pin" type="password" autocomplete="off"></div>
        <div class="field"><label for="a-totp">TOTP secret</label><input id="a-totp" type="password" autocomplete="off"><div class="hint">The text under the QR code when you enable TOTP on smartapi.angelone.in.</div></div>
      </div><div style="display:flex;gap:10px;margin-top:12px"><button class="btn" id="a-save" type="button">Connect Angel One</button>${S.angel.saved ? `<button class="btn ghost" id="a-forget" type="button">Disconnect</button>` : ""}</div></div></section>

    <section class="panel"><div class="panel-head"><h2>Your rules</h2></div><div class="panel-body">
      <div class="form-grid">
        ${num("budget", "Starting money (₹)", s.budget, "Changes only when you start fresh.")}
        ${num("max_loss_per_trade_inr", "Max loss per trade (₹)", s.max_loss_per_trade_inr, "1–2% of your money: ₹20–40 on ₹2,000.")}
        ${num("max_daily_loss_inr", "Max loss per day (₹)", s.max_daily_loss_inr, "No new trades for the day after this.")}
        ${num("max_trades_per_day", "Trades per day", s.max_trades_per_day, "")}
        ${num("min_reward_risk", "Gain at least × the loss", s.min_reward_risk, "1.5 means a possible gain of ₹60 for a ₹40 risk.")}
        ${num("min_price", "Cheapest stock allowed (₹)", s.min_price, "Below ₹20 many stocks can't be traded intraday.")}
        ${text("no_entries_before", "No new trades before", s.no_entries_before)}
        ${text("no_entries_after", "No new trades after", s.no_entries_after)}
        ${num("demo_speed", "Demo market speed", s.demo_speed, "12 = one market minute every 5 seconds.")}
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:14px"><button class="btn buy" id="r-save" type="button">Save rules</button>
        <button class="btn ghost" id="r-reset" type="button">Start fresh with the starting money</button></div>
      <p class="muted" style="margin:10px 0 0">Start fresh deletes this account's practice trades (${S.market.demo ? "demo account" : "live-price account"}) and gives you the starting money again.</p>
    </div></section>`,
    mount() {
      document.querySelectorAll('input[name="src"]').forEach(r => r.onchange = async () => { await api.settings({ source: r.value }); app.done("Prices now from " + r.parentElement.querySelector("b").textContent); });
      $("u-save").onclick = async () => {
        try { const r = await api.upstoxApp({ api_key: $("u-key").value, api_secret: $("u-secret").value, redirect_uri: $("u-redir").value }); location.href = r.login_url; }
        catch (e) { app.done(e.message, "bad"); }
      };
      $("u-forget") && ($("u-forget").onclick = async () => { await api.upstoxForget(); app.done("Upstox disconnected and its keys deleted from this computer."); });
      $("u-token-save").onclick = async () => { try { await api.upstoxToken($("u-token").value); app.done("Token saved. Live prices from Upstox.", "good"); } catch (e) { app.done(e.message, "bad"); } };
      $("a-save").onclick = async () => {
        try { await api.angel({ api_key: $("a-key").value, client_code: $("a-client").value, pin: $("a-pin").value, totp_secret: $("a-totp").value }); app.done("Angel One connected.", "good"); }
        catch (e) { app.done(e.message, "bad"); }
      };
      $("a-forget") && ($("a-forget").onclick = async () => { await api.angelForget(); app.done("Angel One disconnected."); });
      $("r-save").onclick = async () => {
        const b = {}; document.querySelectorAll("[data-key]").forEach(i => b[i.dataset.key] = i.value);
        const cap = +b.budget, loss = +b.max_loss_per_trade_inr;
        if (loss > cap * 0.02 && !confirm(`${inr(loss)} is ${(100 * loss / cap).toFixed(1)}% of ${inr(cap)}, more than the 1–2% you said you can afford. Save anyway?`)) return;
        await api.settings(b); app.done("Rules saved.", "good");
      };
      $("r-reset").onclick = async () => {
        const cap = +document.querySelector('[data-key="budget"]').value;
        if (!confirm(`Delete all practice trades in this account and start again with ${inr(cap)}?`)) return;
        await api.reset(cap); app.done("Fresh start with " + inr(cap), "good");
      };
    },
  };
}

function num(key, label, v, hint) {
  return `<div class="field"><label for="f-${key}">${label}</label><input id="f-${key}" data-key="${key}" type="number" step="any" value="${esc(v)}">${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
}
function text(key, label, v) {
  return `<div class="field"><label for="f-${key}">${label}</label><input id="f-${key}" data-key="${key}" type="time" value="${esc(v)}"></div>`;
}
