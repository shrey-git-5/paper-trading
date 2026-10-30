"""What a round-trip intraday trade costs on NSE (equity, MIS).

Rates as on Zerodha's charges page, Oct 2026, a typical discount broker. Change them in
Settings if your broker differs (Upstox lists intraday brokerage as Rs 20 or 0.05%, lower
of the two)."""


def intraday_charges(qty, buy, sell, rates):
    q = max(int(qty), 0)
    bt, st = q * float(buy), q * float(sell)
    turnover = bt + st
    r = {k: float(v) for k, v in rates.items()}

    def leg(v):
        return min(r["brokerage_cap_inr"], v * r["brokerage_pct"] / 100.0) if v > 0 else 0.0
    out = {
        "brokerage": leg(bt) + leg(st),
        "stt": round(st * r["stt_sell_pct"] / 100.0),                 # Securities Transaction Tax, sell side
        "exchange": turnover * r["exchange_pct"] / 100.0,             # NSE transaction charge
        "sebi": turnover * r["sebi_inr_per_crore"] / 1e7,
        "stamp": round(bt * r["stamp_buy_pct"] / 100.0),              # stamp duty, buy side
        "ipft": turnover * r["ipft_inr_per_crore"] / 1e7,
    }
    out["gst"] = (out["brokerage"] + out["exchange"] + out["sebi"] + out["ipft"]) * r["gst_pct"] / 100.0
    out = {k: round(v, 2) for k, v in out.items()}
    out["total"] = round(sum(out.values()), 2)
    return out
