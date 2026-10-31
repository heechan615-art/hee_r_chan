"""계산 — 성장률(YoY·QoQ), 이익률, 이익률 변화(%p), 비용 비중, 부문 성장률.

모든 결과는 quarter['m'] 에 넣는다. 계산할 재료가 없으면 그 값은 만들지 않는다(빈칸·추정 금지).
"""
from __future__ import annotations

COSTS = ["cost_of_revenue", "rnd", "sales_marketing", "general_admin", "sga", "operating_expenses"]


def _prev_q(q: str, back: int) -> str:
    y, n = int(q[:4]), int(q[-1])
    idx = y * 4 + (n - 1) - back
    return f"{idx // 4}Q{idx % 4 + 1}"


def _growth(cur, base):
    if cur is None or base is None or base == 0:
        return None
    if base < 0:  # 적자 → 흑자 등은 성장률 대신 전환으로 표시
        return None
    return round((cur / base - 1) * 100, 1)


def _ratio(a, b):
    if a is None or not b:
        return None
    return round(a / b * 100, 1)


def series_yoy(series: dict) -> dict:
    """{이름: {분기: 전년 같은 분기 대비 %}}"""
    out = {}
    for name, vals in series.items():
        out[name] = {q: g for q, v in vals.items()
                     if (g := _growth(v, vals.get(_prev_q(q, 4)))) is not None}
    return out


def enrich(data: dict) -> dict:
    if data.get("series"):
        data["series_yoy"] = series_yoy(data["series"])
    if data.get("growth_series"):
        data.setdefault("series_yoy", {}).update(data["growth_series"])
    by_q = {r["calendar_quarter"]: r for r in data["quarters"]}
    for r in data["quarters"]:
        v = r["values"]
        q = r["calendar_quarter"]
        ly = by_q.get(_prev_q(q, 4), {}).get("values", {})
        lq = by_q.get(_prev_q(q, 1), {}).get("values", {})
        m = {}
        for key in ("revenue", "operating_income", "net_income", "fcf", "operating_cash_flow", "capex"):
            m[f"{key}_yoy"] = _growth(v.get(key), ly.get(key))
            m[f"{key}_qoq"] = _growth(v.get(key), lq.get(key))
        rev = v.get("revenue")
        m["gpm"] = _ratio(v.get("gross_profit"), rev)
        m["opm"] = _ratio(v.get("operating_income"), rev)
        m["npm"] = _ratio(v.get("net_income"), rev)
        for key in ("gpm", "opm", "npm"):
            base = {"gpm": _ratio(ly.get("gross_profit"), ly.get("revenue")),
                    "opm": _ratio(ly.get("operating_income"), ly.get("revenue")),
                    "npm": _ratio(ly.get("net_income"), ly.get("revenue"))}[key]
            m[f"{key}_yoy_pp"] = round(m[key] - base, 1) if m[key] is not None and base is not None else None
        for c in COSTS:
            share = _ratio(v.get(c), rev)
            if share is None:
                continue
            m[f"{c}_share"] = share
            base = _ratio(ly.get(c), ly.get("revenue"))
            m[f"{c}_share_yoy_pp"] = round(share - base, 1) if base is not None else None
            m[f"{c}_yoy"] = _growth(v.get(c), ly.get(c))
        if v.get("capex") is not None and v.get("operating_cash_flow"):
            m["capex_to_ocf"] = _ratio(v["capex"], v["operating_cash_flow"])
        r["m"] = {k: x for k, x in m.items() if x is not None}
        for s in r.get("segments", []):
            hist = data.get("series_yoy", {}).get(s["name"], {})
            if _prev_q(q, 1) in hist:
                s["prev_yoy"] = hist[_prev_q(q, 1)]
            if "yoy" not in s:
                g = _growth(s.get("revenue"), s.get("prev"))
                if g is not None:
                    s["yoy"] = g
            g = _growth(s.get("op"), s.get("op_prev"))
            if g is not None:
                s["op_yoy"] = g
    return data
