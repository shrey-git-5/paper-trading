// Formatting helpers shared by every screen.

export function inr(x, opts = {}) {
  if (x === null || x === undefined || x === "" || isNaN(x)) return "–";
  const neg = x < 0;
  let [w, f] = Math.abs(+x).toFixed(opts.dec ?? 2).split(".");
  if (w.length > 3) {
    let h = w.slice(0, -3), t = w.slice(-3), p = [];
    while (h.length > 2) { p.unshift(h.slice(-2)); h = h.slice(0, -2); }
    if (h) p.unshift(h);
    w = p.join(",") + "," + t;
  }
  const body = "₹" + w + (f && (f !== "00" || opts.keepZeros) ? "." + f : "");
  return (neg ? "−" : opts.sign && x > 0 ? "+" : "") + body;
}

export const signed = (x) => inr(x, { sign: true });
export const price = (x) => (x === null || x === undefined || isNaN(x)) ? "–" : (+x).toFixed(2);
export const pct = (x) => (x === null || x === undefined || isNaN(x)) ? "" : (x > 0 ? "+" : "") + (+x).toFixed(2) + "%";
export const tone = (x) => (x > 0 ? "up" : x < 0 ? "down" : "");
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const tick = (v, up) => (up ? Math.ceil(v * 20 - 1e-9) : Math.floor(v * 20 + 1e-9)) / 20;
export const timeOf = (iso) => (iso || "").slice(11, 16);
export const dateOf = (iso) => {
  if (!iso) return "";
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};
