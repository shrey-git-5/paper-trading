// Talking to the Python backend. Every call returns parsed JSON or throws an Error with the server's message.

async function call(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  opts.headers = {...(opts.headers || {})};
  const mode = sessionStorage.getItem("indiantrader-mode");
  if (mode === "demo" || mode === "paper") opts.headers["X-Trade-Mode"] = mode;
  const r = await fetch(path, opts);
  if (r.status === 401) { location.href = "/login.html"; throw new Error("Please log in"); }
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

const q = (o) => new URLSearchParams(o).toString();

export const api = {
  state: () => call("/api/state"),
  watchlist: () => call("/api/watchlist"),
  saveWatchlist: (symbols) => call("/api/watchlist", { symbols }),
  quote: (s) => call("/api/quote?" + q({ s })),
  plan: (s) => call("/api/plan?" + q({ s })),
  preview: (o) => call("/api/preview?" + q(o)),
  search: (term) => call("/api/search?" + q({ q: term })),
  order: (o) => call("/api/order", o),
  exit: (id) => call("/api/exit", { id }),
  modify: (id, stop, target) => call("/api/modify", { id, stop, target }),
  cancel: (id) => call("/api/cancel", { id }),
  scan: () => call("/api/scan", {}),
  settings: (o) => call("/api/settings", o),
  reset: (capital) => call("/api/reset", { capital }),
  upstoxApp: (o) => call("/api/upstox/app", o),
  upstoxToken: (token) => call("/api/upstox/token", { token }),
  upstoxForget: () => call("/api/upstox/forget", {}),
  angel: (o) => call("/api/angel", o),
  angelForget: () => call("/api/angel/forget", {}),
};
