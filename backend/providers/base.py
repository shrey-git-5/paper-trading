"""What every price source must offer. The trading engine only talks to this interface,
so switching between Demo, Upstox and Angel One changes nothing else."""


class ProviderError(Exception):
    """A price source could not answer. The message is shown to you as-is, so it says what to do."""


class Provider:
    name = "base"
    label = "Base"

    def ready(self):
        """(True, "") when it can serve prices; (False, what to do) otherwise."""
        return False, "not configured"

    def universe(self):
        """[{"symbol": "RELIANCE", "name": "Reliance Industries"}...] every NSE equity it knows."""
        raise NotImplementedError

    def snapshot(self, symbols):
        """{SYMBOL: {"ltp", "open", "high", "low", "prev_close", "volume", "pct", "as_of"}} for many stocks."""
        raise NotImplementedError

    def candles(self, symbol, now):
        """Today's 5-minute candles, oldest first: [{"t": "09:15", "o", "h", "l", "c", "v"}]."""
        raise NotImplementedError

    def quote(self, symbol, now):
        snap = self.snapshot([symbol]).get(symbol)
        if not snap:
            raise ProviderError("no price for %s (is it an NSE symbol?)" % symbol)
        return dict(snap, symbol=symbol, bars=self.candles(symbol, now), source=self.label)
