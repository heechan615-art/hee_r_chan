"""수동 입력 YAML 병합 — inputs/{ticker}_{quarter}.yaml 이 있으면 자동 수집값보다 우선.

- overrides: 해당 분기 값을 덮어쓴다. 그 분기가 아직 공시 전이라 없으면 새 분기 줄을 만든다.
- segments: 부문별 매출(·영업이익)과 전년 값(prev) → 성장률은 metrics.py 에서 계산.
- 단위: unit 이 B(십억달러)·조원·억원이면 원 단위로 바꾼다. eps 는 변환하지 않는다.
"""
from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
UNITS = {"B": 1e9, "M": 1e6, "조원": 1e12, "억원": 1e8, "원": 1, "USD": 1}
NO_SCALE = {"eps"}


def path_for(ticker: str, quarter: str) -> Path:
    return ROOT / "inputs" / f"{ticker}_{quarter}.yaml"


def load(ticker: str, quarter: str) -> dict | None:
    p = path_for(ticker, quarter)
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text()) or {}


def _scale(m: dict, unit: str) -> dict:
    k = UNITS.get(unit, 1)
    return {key: (v if key in NO_SCALE else v * k) for key, v in m.items() if v is not None}


def _quarter_end(q: str) -> date:
    y, n = int(q[:4]), int(q[-1])
    m = n * 3
    return date(y, m, calendar.monthrange(y, m)[1])


def merge(data: dict, manual: dict, quarter: str) -> list[str]:
    """data 를 제자리에서 고치고 안내 문구 목록을 돌려준다."""
    msgs = []
    unit = str(manual.get("unit", "B"))
    k = UNITS.get(unit, 1)
    src = manual.get("source")
    if not src:
        raise ValueError("수동 입력 파일에 source(출처)가 없어요. 출처 없는 숫자는 카드에 넣지 않아요.")

    over = _scale(manual.get("overrides") or {}, unit)
    qs = data["quarters"]
    row = next((r for r in qs if r["calendar_quarter"] == quarter), None)
    if row is None:
        if not over:
            raise ValueError(f"{quarter} 정기보고서가 없는데 수동 입력 파일에 overrides 숫자가 없어요.")
        end = _quarter_end(quarter)
        fye = data.get("fiscal_year_end_month", 12)
        if data["market"] == "US":
            from collectors.sec import fiscal_quarter, quarter_label
            label = quarter_label(end, fye)
            fq = "FY%d Q%d" % fiscal_quarter(end, fye)
        else:
            label, fq = f"{quarter[:4]} {quarter[-1]}Q", f"FY{quarter[:4]} Q{quarter[-1]}"
        row = {"calendar_quarter": quarter, "fiscal_quarter": fq, "label": label,
               "end": end.isoformat(), "values": {}, "notes": {}}
        qs.append(row)
        msgs.append(f"{quarter}: 정기보고서 전이라 수동 입력값으로 새로 만들었어요.")
    for key, v in over.items():
        row["values"][key] = v
        row["notes"][key] = "수동 입력"
    v = row["values"]
    if "cost_of_revenue" in over and "revenue" in v:
        v["gross_profit"] = v["revenue"] - v["cost_of_revenue"]
    if {"operating_cash_flow", "capex"} <= over.keys():
        v["fcf"] = v["operating_cash_flow"] - v["capex"]
    if over:  # 이번 분기 숫자를 수동 값으로 덮어쓴 경우에만 '발표 자료 기준(감사 전)'
        row["source"] = src
        row["manual"] = True
    row["status"] = manual.get("status")

    segs = []
    for s in manual.get("segments") or []:
        seg = {"name": s["name"], "hide_growth": bool(s.get("hide_growth")), "icon": s.get("icon")}
        for f in ("revenue", "prev", "op", "op_prev"):
            if s.get(f) is not None:
                seg[f] = s[f] * k
        if s.get("yoy") is not None:
            seg["yoy"] = float(s["yoy"])
        segs.append(seg)
    if segs:
        row["segments"] = segs
        total = sum(s.get("revenue", 0) for s in segs)
        rev = v.get("revenue")
        if rev:
            diff = rev - total
            if abs(diff) / rev > 0.01:
                row["segment_gap"] = diff
                msgs.append(f"⚠️  부문 매출 합계와 전사 매출 차이 {diff / rev:+.1%} → '기타/조정'으로 표시해요.")

    cons = {kk: vv for kk, vv in (manual.get("consensus") or {}).items()
            if vv is not None and kk != "source"}
    if cons:
        row["consensus"] = _scale(cons, unit)
        row["consensus_source"] = (manual.get("consensus") or {}).get("source") or "컨센서스(출처 미기재)"
    # 부문·지표 분기 이력 {이름: {분기: 값}} — 둔화·가속 판단, 이슈 카드 추세 차트용
    if manual.get("series"):
        data["series"] = {name: {str(q): v * k for q, v in vals.items()}
                          for name, vals in manual["series"].items()}
    # 회사가 금액 없이 성장률만 발표하는 항목(예: MS Azure) {이름: {분기: %}}
    if manual.get("growth_series"):
        data["growth_series"] = {name: {str(q): float(v) for q, v in vals.items()}
                                 for name, vals in manual["growth_series"].items()}
    if manual.get("growth_in_panel"):  # 핵심지표 부문 패널에 같이 보여 줄 성장률 항목
        data["growth_in_panel"] = list(manual["growth_in_panel"])
    if manual.get("price_reaction"):
        data["price_reaction"] = manual["price_reaction"]
    if manual.get("flow_mode"):
        data["flow_mode"] = manual["flow_mode"]
    if manual.get("company"):
        data["name_display"] = manual["company"]
    if manual.get("highlight"):
        data["highlight"] = manual["highlight"]
    data["manual_source"] = src
    return msgs
