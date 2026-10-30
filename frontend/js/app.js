// The app shell: routing between screens, the watchlist, search, the top bar and notifications.

import { api } from "./api.js";
import { openOrder } from "./order.js";
import * as views from "./views.js";
import { inr, signed, price, pct, tone, esc } from "./format.js";

const $ = (id) => document.getElementById(id);

const app = {
  state: null,
  timers: [],
  async refresh(quiet) {
    try { app.state = await api.state(); renderChrome(); }
    catch (e) { if (!quiet) toast("Can't reach the app server: " + e.message, "bad"); }
    return app.state;
  },
  done(message, kind) { toast(message, kind); app.refresh(true).then(() => { app.render(); loadWatchlist(); }); },
  render,
};
views.setApp(app);

// ---------------------------------------------------------------- routing
function route() {
  const h = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [path, query] = h.split("?");
  const parts = path.split("/");
  return { name: parts[0], arg: decodeURIComponent(parts[1] || ""), params: new URLSearchParams(query || "") };
}

async function render() {
  app.timers.forEach(clearInterval); app.timers = [];
  if (!app.state) await app.refresh();
  if (!app.state) return;
  const r = route();
  document.body.classList.toggle("show-watchlist", r.name === "watchlist");
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.toggle("on", a.dataset.nav === r.name));
  const S = app.state;
  const v = r.name === "stock" && r.arg ? views.stock(S, r.arg.toUpperCase(), app)
    : r.name === "scanner" ? views.scanner(S, app)
    : r.name === "positions" ? views.positions(S, app)
    : r.name === "orders" ? views.orders(S, app)
    : r.name === "journal" ? views.journal(S)
    : r.name === "settings" ? views.settings(S, app, r.params)
    : views.dashboard(S, app);
  if (r.name === "watchlist") return;
  $("view").innerHTML = v.html;
  const t = await v.mount();
  if (t) app.timers.push(t);
  markSelected(r.name === "stock" ? r.arg.toUpperCase() : null);
}

window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });

// ---------------------------------------------------------------- top bar and notices
function renderChrome() {
  const S = app.state, m = S.market;
  const cls = m.demo ? "demo" : m.open ? "open" : "closed";
  $("market-pill").innerHTML = `<span class="status ${cls}">${m.demo ? "Demo market" : m.open ? "NSE open" : "NSE closed"}</span><span class="muted">${esc(m.now)}</span>`;
  $("account-chip").innerHTML = `<span class="muted">Available</span><b>${inr(S.funds.available)}</b>`;
  const n = $("notice");
  if (!S.source.ready) {
    n.hidden = false;
    n.innerHTML = `${esc(S.source.message)}. <a href="#/settings">Open Settings</a> or <a href="/start.html">switch to Demo</a>.`;
  } else n.hidden = true;
}

let toastId = 0;
function toast(text, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind; el.textContent = text; el.id = "t" + (++toastId);
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "bad" ? 7000 : 4000);
}

// ---------------------------------------------------------------- watchlist (left column)
let wlTimer = null;
async function loadWatchlist() {
  let w;
  try { w = await api.watchlist(); } catch (e) { return; }
  const list = $("wl-list");
  $("wl-count").textContent = `Watchlist (${w.items.length})`;
  $("wl-src").textContent = app.state ? app.state.source.label : "";
  if (!w.items.length) { list.innerHTML = `<li class="wl-empty">Search above and add stocks to watch.</li>`; return; }
  list.innerHTML = w.items.map(i => {
    const t = tone(i.pct);
    return `<li class="wl-row ${t === "down" ? "dn" : t === "up" ? "upr" : ""}" data-sym="${esc(i.symbol)}" tabindex="0">
      <span class="wl-sym">${esc(i.symbol)}</span>
      <span class="wl-pct ${t}">${i.pct != null ? pct(i.pct) : ""}</span>
      <span class="wl-ltp ${t}">${i.ltp ? price(i.ltp) : "–"}</span>
      <span class="wl-actions"><button class="b" data-buy="${esc(i.symbol)}" type="button" aria-label="Buy ${esc(i.symbol)}">B</button>
        <button class="x" data-del="${esc(i.symbol)}" type="button" aria-label="Remove ${esc(i.symbol)}">✕</button></span></li>`;
  }).join("") + (w.error ? `<li class="wl-empty down">${esc(w.error)}</li>` : "");
  list.querySelectorAll(".wl-row").forEach(row => {
    const go = () => { location.hash = "#/stock/" + encodeURIComponent(row.dataset.sym); };
    row.onclick = (e) => { if (!e.target.closest("button")) go(); };
    row.onkeydown = (e) => { if (e.key === "Enter") go(); };
  });
  list.querySelectorAll("[data-buy]").forEach(b => b.onclick = () => openOrder(b.dataset.buy, {}, app.done));
  list.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    await api.saveWatchlist(app.state.settings.watchlist.filter(s => s !== b.dataset.del));
    await app.refresh(true); loadWatchlist();
  });
  const r = route(); markSelected(r.name === "stock" ? r.arg.toUpperCase() : null);
}

function markSelected(sym) {
  document.querySelectorAll(".wl-row").forEach(r => r.classList.toggle("sel", r.dataset.sym === sym));
}

// ---------------------------------------------------------------- search
let searchTimer = null;
$("search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(search, 180); });
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { const v = $("search").value.trim().toUpperCase(); if (v) openStock(v); }
  if (e.key === "Escape") closeSearch();
});
document.addEventListener("click", (e) => { if (!e.target.closest(".wl-search")) closeSearch(); });

async function search() {
  const term = $("search").value.trim();
  const box = $("search-results");
  if (!term) return closeSearch();
  let r;
  try { r = await api.search(term); } catch (e) { box.innerHTML = `<div class="wl-empty down">${esc(e.message)}</div>`; box.hidden = false; return; }
  box.innerHTML = r.items.length ? r.items.map(i => `<button type="button" data-sym="${esc(i.symbol)}"><b>${esc(i.symbol)}</b><small>${esc(i.name || "NSE")}</small></button>`).join("")
    : `<div class="wl-empty">No NSE stock starts with “${esc(term)}”.</div>`;
  box.querySelectorAll("button").forEach(b => b.onclick = () => openStock(b.dataset.sym, true));
  box.hidden = false;
}
function closeSearch() { $("search-results").hidden = true; }
async function openStock(sym, add) {
  closeSearch(); $("search").value = "";
  if (add && app.state && !app.state.settings.watchlist.includes(sym)) {
    await api.saveWatchlist([...app.state.settings.watchlist, sym]); await app.refresh(true); loadWatchlist();
  }
  location.hash = "#/stock/" + encodeURIComponent(sym);
}

// ---------------------------------------------------------------- start
(async function start() {
  await app.refresh();
  await render();
  loadWatchlist();
  const fast = () => app.state && app.state.market.demo;
  setInterval(() => app.refresh(true), 5000);
  wlTimer = setInterval(loadWatchlist, fast() ? 4000 : 10000);
})();
