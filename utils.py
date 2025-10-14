from typing import List, Iterable, Any
import math
from html import escape as _escape

def escape(s: Any) -> str:
    return _escape(str(s), quote=False)

def bytes_to_human(n: int) -> str:
    if not n:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = int(math.floor(math.log(n, 1024))) if n > 0 else 0
    val = n / (1024 ** i) if n > 0 else 0
    return f"{val:.2f} {units[i]}"

def num(n: Any) -> str:
    if n is None:
        return "0"
    try:
        return f"{int(n):,}"
    except Exception:
        try:
            return f"{float(n):,.2f}"
        except Exception:
            return str(n)

def pct(part: float, total: float) -> str:
    if not total:
        return "0%"
    return f"{(part/total)*100:.1f}%"

def _calc_widths(rows: List[List[str]]) -> List[int]:
    w = [0] * len(rows[0]) if rows else []
    for r in rows:
        for i, cell in enumerate(r):
            w[i] = max(w[i], len(str(cell)))
    return w

def make_pre_table(rows: List[List[Any]], header: List[str]) -> str:
    """
    Returns an HTML <pre> block with monospaced, aligned columns.
    Telegram supports <pre> but NOT <table>.
    """
    hdr = [str(h) for h in header]
    body = [[str(c) for c in r] for r in rows]
    widths = _calc_widths([hdr] + body)

    def fmt(row: List[str]) -> str:
        padded = [row[i].ljust(widths[i]) for i in range(len(widths))]
        return "  ".join(padded)

    lines = [fmt(hdr), "  ".join("-" * w for w in widths)]
    for r in body:
        lines.append(fmt(r))

    content = "\n".join(lines)
    return f"<pre>{escape(content)}</pre>"

def _downsample(seq: List[float], max_len: int = 60) -> List[float]:
    if len(seq) <= max_len:
        return seq
    # simple bucketed max sampler
    bucket = len(seq) / max_len
    out = []
    i = 0.0
    while int(i) < len(seq):
        j = min(len(seq), int(i + bucket))
        out.append(max(seq[int(i):j]))
        i += bucket
    return out[:max_len]

def sparkline(values: Iterable[float], max_len: int = 60) -> str:
    ticks = "▁▂▃▄▅▆▇"
    vals = [0 if v is None else float(v) for v in values]
    vals = _downsample(vals, max_len=max_len)
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return ticks[0] * len(vals)
    out = []
    for v in vals:
        idx = int((v - lo) / (hi - lo) * (len(ticks) - 1))
        out.append(ticks[idx])
    return "".join(out)
