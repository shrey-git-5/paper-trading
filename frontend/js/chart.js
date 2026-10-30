// Today's 5-minute candles as an SVG, with the morning range, your stop-loss and target, and the last price.

const SESSION_START = 9 * 60 + 15;   // 9:15 AM
const SLOTS = 75;                    // 5-minute candles in a full NSE day

export function drawChart(svg, quote, lines = {}) {
  const W = svg.clientWidth || 700, H = svg.clientHeight || 340;
  const pad = { l: 10, r: 70, t: 14, b: 24 };
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const up = css("--up"), down = css("--down"), muted = css("--muted"), line = css("--line"), buy = css("--buy");
  if (!quote || !quote.bars || !quote.bars.length) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" fill="${muted}" font-size="13">No candles yet today. The first one appears at 9:20 AM.</text>`;
    return;
  }
  const bars = quote.bars;
  const range = bars.length >= 3 ? { hi: Math.max(...bars.slice(0, 3).map(b => b.h)), lo: Math.min(...bars.slice(0, 3).map(b => b.l)) } : null;
  let lo = Math.min(...bars.map(b => b.l)), hi = Math.max(...bars.map(b => b.h));
  for (const v of [lines.stop, lines.target, quote.ltp]) if (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const span = (hi - lo) || hi * 0.01; lo -= span * .07; hi += span * .07;
  const cw = (W - pad.l - pad.r) / SLOTS;
  const y = (v) => pad.t + (hi - v) / (hi - lo) * (H - pad.t - pad.b);
  const x = (t) => { const [h, m] = t.split(":").map(Number); return pad.l + ((h * 60 + m) - SESSION_START) / 5 * cw; };
  let s = "";
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4, yy = y(v);
    s += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${yy}" y2="${yy}" stroke="${line}"/>
          <text x="${W - pad.r + 8}" y="${yy + 4}" font-size="11" fill="${muted}">${v.toFixed(2)}</text>`;
  }
  for (const t of ["09:15", "10:30", "12:00", "13:30", "15:00"]) s += `<text x="${x(t)}" y="${H - 6}" font-size="11" fill="${muted}">${t}</text>`;
  const hline = (v, col, label, dash) => {
    const yy = y(v);
    s += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${yy}" y2="${yy}" stroke="${col}" stroke-width="1.3" stroke-dasharray="${dash}"/>
          <rect x="${W - pad.r + 3}" y="${yy - 9}" width="${pad.r - 6}" height="18" rx="3" fill="${col}"/>
          <text x="${W - pad.r + 8}" y="${yy + 4}" font-size="11" fill="#fff" font-weight="600">${label}</text>`;
  };
  if (range) {
    s += `<rect x="${pad.l}" y="${y(range.hi)}" width="${x("09:30") - pad.l}" height="${Math.max(y(range.lo) - y(range.hi), 1)}" fill="${muted}" opacity=".10"/>`;
    hline(range.hi, muted, range.hi.toFixed(1), "3 4");
    hline(range.lo, muted, range.lo.toFixed(1), "3 4");
  }
  for (const b of bars) {
    const xx = x(b.t) + cw * .15, w = Math.max(cw * .7, 1.5), col = b.c >= b.o ? up : down;
    const yo = y(b.o), yc = y(b.c);
    s += `<g><title>${b.t}  open ${b.o}  high ${b.h}  low ${b.l}  close ${b.c}</title>
          <line x1="${xx + w / 2}" x2="${xx + w / 2}" y1="${y(b.h)}" y2="${y(b.l)}" stroke="${col}"/>
          <rect x="${xx}" y="${Math.min(yo, yc)}" width="${w}" height="${Math.max(Math.abs(yc - yo), 1)}" fill="${col}"/></g>`;
  }
  if (lines.stop) hline(lines.stop, down, "SL " + (+lines.stop).toFixed(1), "6 4");
  if (lines.target) hline(lines.target, up, "T " + (+lines.target).toFixed(1), "6 4");
  hline(quote.ltp, buy, (+quote.ltp).toFixed(2), "0");
  svg.innerHTML = s;
}
