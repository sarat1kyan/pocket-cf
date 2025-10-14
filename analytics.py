from typing import Dict, Any, List, Tuple
from utils import bytes_to_human, num, sparkline, make_pre_table

def _get(z: Dict[str, Any], key: str, default=None):
    return (z or {}).get(key, default)

def _zones(gql: Dict[str, Any]):
    return _get(_get(_get(gql, "data", {}), "viewer", {}), "zones", [])

def _groups_from_any(gql: Dict[str, Any]) -> List[Dict[str, Any]]:
    zones = _zones(gql)
    if not zones:
        return []
    # Prefer Adaptive; gracefully fall back to fixed if present.
    for node_name in (
        "httpRequestsAdaptiveGroups",
        "httpRequests1hGroups",
        "httpRequests1mGroups",
    ):
        groups = _get(zones[0], node_name, [])
        if groups:
            return groups
    return []

def timeseries_from_graphql(gql: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups = _groups_from_any(gql)
    out: List[Dict[str, Any]] = []
    for g in groups:
        dims = _get(g, "dimensions", {}) or {}
        sums = _get(g, "sum", {}) or {}
        dt = dims.get("datetime") or dims.get("datetimeHour") or dims.get("datetimeMinute") or dims.get("date")
        # request count can be:
        #  - Adaptive: top-level g["count"]
        #  - Fixed:    sum.requests (legacy)
        req = (g.get("count") or 0) or (sums.get("requests") or 0)
        # bytes can be:
        #  - Adaptive: sum.edgeResponseBytes
        #  - Fixed:    sum.bytes
        byt = sums.get("edgeResponseBytes") or sums.get("bytes") or 0
        # visits (adaptive sum.visits, or legacy uniques)
        vis = sums.get("visits") or sums.get("uniques") or 0
        out.append({"datetime": dt, "count": req, "bytes": byt, "visits": vis})
    out.sort(key=lambda x: x.get("datetime") or "")
    return out

def summary_for_timeseries(ts: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_req = sum((x.get("count") or 0) for x in ts)
    total_bytes = sum((x.get("bytes") or 0) for x in ts)
    total_visits = sum((x.get("visits") or 0) for x in ts)
    trend = sparkline([x.get("count") or 0 for x in ts], max_len=60)
    return {"requests": total_req, "bytes": total_bytes, "visits": total_visits, "trend": trend}

def colos_from_graphql(gql: Dict[str, Any], top_n: int = 10) -> List[Tuple[str, int, int]]:
    zones = _zones(gql)
    groups = zones[0].get("httpRequestsAdaptiveGroups", []) if zones else []
    rows = []
    for g in groups:
        dims = _get(g, "dimensions", {}) or {}
        sums = _get(g, "sum", {}) or {}
        # requests: top-level count; bytes: sum.edgeResponseBytes
        rows.append((dims.get("coloCode") or "-", g.get("count") or 0, sums.get("edgeResponseBytes") or 0))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:top_n]

def format_timeseries_summary_for_html(ts: List[Dict[str, Any]]) -> str:
    summ = summary_for_timeseries(ts)
    parts = [
        f"<b>Requests:</b> <code>{num(summ['requests'])}</code>",
        f"<b>Transfer:</b> <code>{bytes_to_human(summ['bytes'])}</code>",
        f"<b>Visits:</b> <code>{num(summ['visits'])}</code>",
    ]
    if summ.get("trend"):
        parts.append(f"<b>Trend:</b> <code>{summ['trend']}</code>")
    return " • ".join(parts)

def format_colos_for_html(rows: List[Tuple[str, int, int]]) -> str:
    header = ["Colo", "Requests", "Transfer"]
    body = [[colo or "-", num(c), bytes_to_human(b)] for colo, c, b in rows]
    return make_pre_table(body, header)

def format_security_for_html(gql: Dict[str, Any], top_n: int = 10) -> str:
    zones = _zones(gql)
    if not zones:
        return "<i>No data.</i>"
    groups = zones[0].get("firewallEventsAdaptiveGroups", [])
    groups.sort(key=lambda g: g.get("count") or 0, reverse=True)
    rows = []
    for g in groups[:top_n]:
        dims = g.get("dimensions", {}) or {}
        action = dims.get("action")
        rule = dims.get("ruleId")
        src = dims.get("source")
        count = g.get("count") or 0
        rows.append([action or "-", rule or "-", src or "-", num(count)])
    if not rows:
        return "<i>No security events in the selected window.</i>"
    return make_pre_table(rows, ["Action", "Rule", "Source", "Count"])
