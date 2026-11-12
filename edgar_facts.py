"""AI 종합 해석용 재무 항목 수집 — 미국: SEC EDGAR companyfacts 1순위, 실패 시 yfinance.

연간(최근 5개 회계연도) + TTM. 현금흐름표 항목은 10-Q가 '연초부터 누적'이라
TTM = 직전 회계연도 + 올해 누적 − 작년 같은 기간 누적.
국내 종목은 여기서 다루지 않는다(가치평가 결과의 WISEfn 재무를 그대로 씀).
값 단위는 원래 통화(달러), 주식수는 주.
"""
import time
import datetime as dt

import per_hist

# 항목별 XBRL 태그 후보 — 회사마다 쓰는 태그가 달라 앞에서부터 연도별로 채움
TAGS = {
    "revenue": per_hist._REV_TAGS,
    "gross_profit": ("GrossProfit",),
    "op_income": ("OperatingIncomeLoss",),
    "nonop": ("NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense"),
    "pretax": ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
    "tax": ("IncomeTaxExpenseBenefit",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "ocf": ("NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements"),
    "da": ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet", "Depreciation"),
    "buyback": ("PaymentsForRepurchaseOfCommonStock",),
    "dividends": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    "acquisitions": ("PaymentsToAcquireBusinessesNetOfCashAcquired", "PaymentsToAcquireBusinessesGross",
                     "PaymentsToAcquireBusinessesAndInterestInAffiliates",
                     "PaymentsToAcquireBusinessesNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets"),
    "divestitures": ("ProceedsFromDivestitureOfBusinesses", "ProceedsFromDivestitureOfBusinessesNetOfCashDivested",
                     "ProceedsFromSaleOfProductiveAssets"),
    "sbc": ("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"),
    "shares_diluted": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
}
LABEL = {"revenue": "매출", "gross_profit": "매출총이익", "op_income": "영업이익", "nonop": "영업외손익", "pretax": "세전이익",
         "tax": "법인세", "net_income": "순이익", "eps_diluted": "희석 EPS", "ocf": "영업현금흐름", "capex": "설비투자",
         "da": "감가상각", "buyback": "자사주 매입", "dividends": "배당", "acquisitions": "인수 지출",
         "divestitures": "사업 매각 수입", "sbc": "주식보상", "shares_diluted": "희석 주식수"}
FLOW_NO_TTM = {"eps_diluted", "shares_diluted"}   # TTM 합산이 의미 없는 항목(주당·평균)

_CACHE = {}
_TTL = 6 * 3600


def _facts(cik):
    """companyfacts에서 필요한 태그 행만 {tag: rows}."""
    want = {t for ts in TAGS.values() for t in ts}
    try:
        r = per_hist.sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        if r.status_code != 200:
            return None
        g = r.json().get("facts", {}).get("us-gaap", {})
    except Exception:
        return None
    out = {}
    for t in want:
        if t in g:
            units = g[t]["units"]
            rows = units.get("USD") or units.get("USD/shares") or units.get("shares") or next(iter(units.values()))
            out[t] = rows
    return out


def _days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def _periods(rows):
    """행 → {(start, end): (val, filed)} 기간값. 같은 기간은 가장 최근 제출값(정정 반영)."""
    out = {}
    for x in rows:
        s, e, v, f = x.get("start"), x.get("end"), x.get("val"), x.get("filed") or ""
        if not (s and e) or v is None:
            continue
        k = (s, e)
        if k not in out or f > out[k][1]:
            out[k] = (v, f)
    return out


def _annual_and_ttm(rows, ttm=True):
    """연간 {회계연도말: 값} + TTM(값, 기준일)."""
    per = _periods(rows)
    ann = {e: v for (s, e), (v, _) in per.items() if 350 <= _days(s, e) <= 385}
    if not ann:
        return {}, None, None
    last_fy = max(ann)
    if not ttm:
        return ann, None, None
    # 올해 누적(직전 회계연도말 이후 시작, 3·6·9개월)
    ytd = [(s, e, v) for (s, e), (v, _) in per.items()
           if s > last_fy and 0 <= _days(last_fy, s) <= 10 and 80 <= _days(s, e) <= 285]
    if not ytd:
        return ann, ann[last_fy], last_fy
    s, e, v = max(ytd, key=lambda r: r[1])
    span = _days(s, e)
    ed = dt.date.fromisoformat(e)
    prev = [pv for (ps, pe), (pv, _) in per.items()
            if abs(_days(ps, pe) - span) <= 12 and abs((ed - dt.date.fromisoformat(pe)).days - 365) <= 20]
    if not prev:
        return ann, ann[last_fy], last_fy
    return ann, ann[last_fy] + v - prev[0], e


def _from_sec(sym):
    cik = per_hist._cik(sym)
    if not cik:
        return None
    facts = _facts(cik)
    if not facts:
        return None
    annual, ttm, src = {}, {}, {}
    ttm_end = None
    for key, tags in TAGS.items():
        merged, t_val, t_end = {}, None, None
        for t in tags:
            if t not in facts:
                continue
            a, tv, te = _annual_and_ttm(facts[t], ttm=key not in FLOW_NO_TTM)
            for k, v in a.items():
                merged.setdefault(k, v)
            # TTM은 최신 기준일이 가장 늦은 태그 우선(회사가 태그를 바꾼 경우 대비)
            if tv is not None and (t_end is None or te > t_end):
                t_val, t_end = tv, te
            if a and key not in src:
                src[key] = t
        if merged:
            annual[key] = merged
        if t_val is not None:
            ttm[key] = t_val
            if key == "revenue":
                ttm_end = t_end
    if "revenue" not in annual:
        return None
    ends = sorted(annual["revenue"])[-5:]
    years = [e[:4] if int(e[5:7]) >= 6 else str(int(e[:4]) - 1) for e in ends]   # 1~5월 결산은 직전 해 회계연도
    ser = {k: [annual.get(k, {}).get(e) for e in ends] for k in TAGS}
    # 연도 끝이 매출과 몇 일 어긋난 태그(52/53주 결산) 보정
    for k in TAGS:
        for i, e in enumerate(ends):
            if ser[k][i] is None and k in annual:
                near = [v for ee, v in annual[k].items() if abs(_days(ee, e)) <= 10]
                if near:
                    ser[k][i] = near[0]
    return {"source": "SEC EDGAR", "fy_ends": ends, "years": years, "annual": ser,
            "ttm": ttm, "ttm_end": ttm_end, "tags": src}


def _from_yahoo(sym):
    """SEC 실패 시 yfinance 연간 재무(최근 4년) + 최근 4분기 합 TTM."""
    import yfsess
    import pandas as pd
    tk = yfsess.ticker(sym)
    try:
        inc, cf = tk.income_stmt, tk.cashflow
        qinc, qcf = tk.quarterly_income_stmt, tk.quarterly_cashflow
    except Exception:
        return None
    if inc is None or inc.empty:
        return None
    rows = {
        "revenue": (inc, ["Total Revenue", "Operating Revenue"], 1),
        "gross_profit": (inc, ["Gross Profit"], 1),
        "op_income": (inc, ["Operating Income"], 1),
        "nonop": (inc, ["Other Non Operating Income Expenses", "Other Income Expense"], 1),
        "pretax": (inc, ["Pretax Income"], 1),
        "tax": (inc, ["Tax Provision"], 1),
        "net_income": (inc, ["Net Income", "Net Income Common Stockholders"], 1),
        "eps_diluted": (inc, ["Diluted EPS"], 1),
        "shares_diluted": (inc, ["Diluted Average Shares"], 1),
        "ocf": (cf, ["Operating Cash Flow"], 1),
        "capex": (cf, ["Capital Expenditure"], -1),
        "da": (cf, ["Depreciation And Amortization", "Depreciation Amortization Depletion"], 1),
        "buyback": (cf, ["Repurchase Of Capital Stock", "Common Stock Payments"], -1),
        "dividends": (cf, ["Cash Dividends Paid", "Common Stock Dividend Paid"], -1),
        "acquisitions": (cf, ["Purchase Of Business"], -1),
        "divestitures": (cf, ["Sale Of Business"], 1),
        "sbc": (cf, ["Stock Based Compensation"], 1),
    }
    qmap = {"income": qinc, "cash": qcf}
    cols = sorted(c for c in inc.columns if not inc[c].isna().all())[-5:]
    ser, ttm = {}, {}
    for k, (df, names, sign) in rows.items():
        r = next((df.loc[n] for n in names if df is not None and n in df.index), None)
        ser[k] = [None if (r is None or c not in r.index or pd.isna(r[c])) else float(r[c]) * sign for c in cols]
        qd = qmap["income" if df is inc else "cash"]
        if k in FLOW_NO_TTM or qd is None or qd.empty:
            continue
        qr = next((qd.loc[n] for n in names if n in qd.index), None)
        if qr is not None:
            vals = [float(qr[c]) for c in sorted(qr.index)[-4:] if not pd.isna(qr[c])]
            if len(vals) == 4:
                ttm[k] = sum(vals) * sign
    return {"source": "Yahoo(yfinance)", "fy_ends": [str(pd.Timestamp(c).date()) for c in cols],
            "years": [str(pd.Timestamp(c).year) for c in cols], "annual": ser, "ttm": ttm,
            "ttm_end": None, "tags": {}}


def _fill(sec, yh):
    """SEC에 없는 항목(예: 매출총이익을 공시하지 않는 회사, 태그가 다른 인수 지출)은 같은 회계연도의 야후 값으로."""
    ymap = {y: i for i, y in enumerate(yh["years"])}
    filled = []
    for k, arr in sec["annual"].items():
        ya = yh["annual"].get(k) or []
        for i, y in enumerate(sec["years"]):
            j = ymap.get(y)
            if arr[i] is None and j is not None and j < len(ya) and ya[j] is not None:
                arr[i] = ya[j]
                if k not in filled:
                    filled.append(k)
        if k not in sec["ttm"] and k in yh["ttm"]:
            sec["ttm"][k] = yh["ttm"][k]
            if k not in filled:
                filled.append(k)
    if filled:
        sec["source"] = "SEC EDGAR(+야후 보충: " + ", ".join(LABEL.get(k, k) for k in filled) + ")"


def us_financials(sym):
    """미국 종목 재무 항목. 반환 {source, years, annual:{항목:[5년]}, ttm:{항목:값}} 또는 None."""
    sym = str(sym).split(".")[0].upper()
    hit = _CACHE.get(sym)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    out = None
    try:
        out = _from_sec(sym)
    except Exception:
        out = None
    try:
        yh = _from_yahoo(sym)
    except Exception:
        yh = None
    if not out:
        out = yh
    elif yh:
        _fill(out, yh)
    _CACHE[sym] = (time.time(), out)
    return out
