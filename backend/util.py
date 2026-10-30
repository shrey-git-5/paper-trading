"""Small shared helpers: time in IST, rupee formatting, safe JSON files."""

import datetime
import json
import os

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def ist_now():
    """Current time in India as a naive datetime (no timezone attached)."""
    return datetime.datetime.now(IST).replace(tzinfo=None, microsecond=0)


def ingroup(x, dec=2):
    """Indian digit grouping: 123456.5 -> '1,23,456.50'."""
    neg = x < 0
    s = ("%." + str(dec) + "f") % abs(float(x))
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + ("." + frac if frac else "")


def inr(x):
    x = round(float(x), 2)
    s = ingroup(abs(x))
    if s.endswith(".00"):
        s = s[:-3]
    return ("-₹" if x < 0 else "₹") + s


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, doc, private=False):
    """Write atomically, so a crash never leaves half a file. private=True: only your user can read it."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def round_tick(x, down=True):
    """Round to the 5-paise grid most NSE stocks trade on."""
    import math
    v = float(x) * 20
    return round((math.floor(v + 1e-9) if down else math.ceil(v - 1e-9)) / 20.0, 2)
