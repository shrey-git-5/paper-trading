// The order window (opens from the watchlist, a stock page, or a scanner suggestion).
// Buy only: this app practises long intraday trades. Selling happens from Positions, or automatically
// at your stop-loss, target, or the 3:20 PM square-off.

import { api } from "./api.js";
import { inr, signed, price, esc, tick } from "./format.js";

const $ = (id) => document.getElementById(id);
let ctx = null, timer = null, onDone = null;

export function openOrder(symbol, prefill = {}, done) {
  onDone = done;
  ctx = { symbol, type: "market", ...prefill };
  const sheet = $("order-sheet");
  sheet.innerHTML = `
    <div class="sheet-head">
      <h2 id="order-title">Buy ${esc(symbol)}</h2>
      <p id="o-ltp">NSE, loading price…</p>
    </div>
    <div class="sheet-body">
      <div class="product"><span class="tag">Intraday</span><span>Sold the same day: by you, at your stop-loss or target, or at 3:20 PM.</span></div>
      <div class="fields">
        <div class="field"><label for="o-qty">Quantity</label><input id="o-qty" type="number" min="1" step="1" inputmode="numeric">
          <div class="hint"><button class="linklike" id="o-max" type="button">Use safe maximum</button></div></div>
        <div class="field"><label>Price</label>
          <div class="seg" role="group" aria-label="Order type"><button type="button" id="o-mkt" class="on">Market</button><button type="button" id="o-lim">Limit</button></div>
          <input id="o-limit" type="number" step="0.05" inputmode="decimal" hidden aria-label="Limit price"></div>
        <div class="field"><label for="o-stop">Stop-loss</label><input id="o-stop" type="number" step="0.05" inputmode="decimal">
          <div class="hint">Sell automatically if the price falls here.</div></div>
        <div class="field"><label for="o-target">Target</label><input id="o-target" type="number" step="0.05" inputmode="decimal">
          <div class="hint">Sell automatically if the price rises here.</div></div>
      </div>
      <div class="hint" style="margin-top:8px"><button class="linklike" id="o-auto" type="button">Fill stop-loss and target for me</button>
        <span class="muted"> (stop at the middle of the 9:15–9:30 range, target at twice the risk)</span></div>
      <div class="riskbar" aria-live="polite">
        <div class="track"><div class="loss" id="o-loss">–</div><div class="gain" id="o-gain">–</div></div>
        <div class="caption"><span>If the stop-loss hits</span><span>If the target hits</span></div>
      </div>
      <ul class="checks" id="o-checks"></ul>
      <div class="margin-line" id="o-margin"></div>
    </div>
    <div class="sheet-foot">
      <button class="btn buy" id="o-buy" type="button" disabled>Buy</button>
      <button class="btn" id="o-cancel" type="button">Cancel</button>
    </div>`;
  $("sheet-backdrop").hidden = false;
  sheet.hidden = false;
  if (ctx.qty) $("o-qty").value = ctx.qty;
  if (ctx.stop) $("o-stop").value = ctx.stop;
  if (ctx.target) $("o-target").value = ctx.target;
  $("o-cancel").onclick = closeOrder;
  $("sheet-backdrop").onclick = closeOrder;
  $("o-mkt").onclick = () => setType("market");
  $("o-lim").onclick = () => setType("limit");
  $("o-max").onclick = useMax;
  $("o-auto").onclick = autoFill;
  $("o-buy").onclick = submit;
  for (const id of ["o-qty", "o-stop", "o-target", "o-limit"]) $(id).addEventListener("input", schedule);
  document.addEventListener("keydown", onKey);
  if (!ctx.stop) autoFill(); else schedule(true);
  $("o-qty").focus();
}

export function closeOrder() {
  $("order-sheet").hidden = true;
  $("sheet-backdrop").hidden = true;
  document.removeEventListener("keydown", onKey);
  clearTimeout(timer);
}

function onKey(e) { if (e.key === "Escape") closeOrder(); }

function setType(t) {
  ctx.type = t;
  $("o-mkt").className = t === "market" ? "on" : "";
  $("o-lim").className = t === "limit" ? "on" : "";
  $("o-limit").hidden = t !== "limit";
  if (t === "limit" && !$("o-limit").value && ctx.ltp) $("o-limit").value = price(ctx.ltp);
  schedule();
}

async function autoFill() {
  try {
    const p = await api.plan(ctx.symbol);
    ctx.ltp = p.ltp;
    $("o-stop").value = p.stop; $("o-target").value = p.target;
    if (p.qty) $("o-qty").value = p.qty;
    schedule(true);
  } catch (e) { $("o-checks").innerHTML = `<li class="no">${esc(e.message)}</li>`; }
}

async function useMax() {
  const p = await preview();
  if (p && p.max_qty) { $("o-qty").value = p.max_qty; schedule(true); }
  else if (p) $("o-checks").insertAdjacentHTML("afterbegin", `<li class="no">Even 1 share risks more than your max loss with this stop-loss. Move the stop-loss closer or pick another stock.</li>`);
}

function schedule(now) { clearTimeout(timer); timer = setTimeout(preview, now ? 0 : 250); }

async function preview() {
  const o = { s: ctx.symbol, qty: $("o-qty").value || 0, stop: $("o-stop").value || 0, target: $("o-target").value || 0 };
  if (ctx.type === "limit" && $("o-limit").value) o.limit = $("o-limit").value;
  let p;
  try { p = await api.preview(o); } catch (e) {
    $("o-checks").innerHTML = `<li class="no">${esc(e.message)}</li>`; $("o-buy").disabled = true; return null;
  }
  ctx.ltp = p.ltp;
  $("o-ltp").textContent = `NSE, last price ${inr(p.ltp)}`;
  const loss = p.qty ? p.loss_at_stop : null, gain = p.qty ? p.gain_at_target : null;
  const L = Math.max(Math.abs(loss || 0), 0.01), G = Math.max(gain || 0, 0.01);
  $("o-loss").style.flex = String(L); $("o-gain").style.flex = String(G);
  $("o-loss").textContent = loss != null ? "−" + inr(Math.abs(loss)).replace("−", "") : "–";
  $("o-gain").textContent = gain != null ? signed(gain) : "–";
  $("o-checks").innerHTML = p.checks.map(c => `<li class="${c.ok ? "ok" : "no"}">${esc(c.text)}</li>`).join("");
  $("o-margin").innerHTML = p.qty
    ? `Needs ${inr(p.cost)} at ${inr(p.price)}. Available ${inr(p.available)}. Charges about ${inr(p.charges_at_target)}, already included above.`
    : `Available ${inr(p.available)}. Safe maximum here: ${p.max_qty} share${p.max_qty === 1 ? "" : "s"}.`;
  $("o-buy").disabled = !p.ok;
  $("o-buy").textContent = p.qty ? `Buy ${p.qty}` : "Buy";
  ctx.preview = p;
  return p;
}

async function submit() {
  const p = ctx.preview; if (!p || !p.ok) return;
  $("o-buy").disabled = true;
  try {
    const r = await api.order({ symbol: ctx.symbol, qty: p.qty, stop: p.stop, target: p.target, type: ctx.type,
      limit: ctx.type === "limit" ? $("o-limit").value : null });
    closeOrder();
    onDone && onDone(r.position ? `Bought ${r.position.qty} ${r.position.symbol} at ${inr(r.position.avg)}` :
      `Limit order placed for ${ctx.symbol}. It fills if the price comes down to ${inr(+$("o-limit").value)}.`, "good");
  } catch (e) { $("o-checks").innerHTML = `<li class="no">${esc(e.message)}</li>`; $("o-buy").disabled = false; }
}
