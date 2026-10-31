"""미국 기업 재무 데이터 수집기 — SEC EDGAR XBRL (무료, 키 불필요)

- 티커 → CIK: company_tickers.json
- 재무: companyfacts/CIK##########.json
- 분기값 규칙
  * 3개월짜리 공시값이 있으면 그대로 쓴다.
  * 없으면 "같은 시작일의 누적값(YTD) − 직전 분기까지의 누적값"으로 만든다.
    → 4분기(연간 10-K − 9개월 누적), 현금흐름(누적 공시)이 모두 이 규칙으로 풀린다.
- 같은 기간을 여러 공시가 보고하면 가장 늦게 제출된 값(정정 반영)을 쓴다.
- 태그는 후보 리스트를 분기별로 합친다(기업이 중간에 태그를 바꾸는 경우가 있음, 예: 알파벳 2025년 매출).
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)

# SEC 정책: 연락처가 담긴 User-Agent 필수. HTTP 헤더는 한글을 못 실어서 영문으로 쓴다.
HEADERS = {"User-Agent": "HeeRChan EarningsCards heechan615@gmail.com"}
_last_request = 0.0

# 항목 → (후보 태그, 성격) / flow = 기간 합계(손익·현금흐름)
TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "rnd": ["ResearchAndDevelopmentExpense",
            "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
    "sales_marketing": ["SellingAndMarketingExpense"],
    "general_admin": ["GeneralAndAdministrativeExpense"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets"],
}
EPS_TAGS = ["EarningsPerShareDiluted"]


class SecError(Exception):
    pass


def _get(url: str) -> requests.Response:
    """초당 10회 이하로 요청."""
    global _last_request
    wait = 0.12 - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    r = requests.get(url, headers=HEADERS, timeout=30)
    _last_request = time.time()
    if r.status_code != 200:
        raise SecError(f"SEC 요청 실패 ({r.status_code}): {url}")
    return r


def _cached_json(name: str, url: str, max_age_hours: float, refresh: bool):
    path = CACHE / name
    if path.exists() and not refresh:
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < max_age_hours:
            return json.loads(path.read_text())
    data = _get(url).json()
    path.write_text(json.dumps(data))
    return data


def ticker_to_cik(ticker: str, refresh: bool = False) -> tuple[str, str]:
    """티커 → (10자리 CIK, 영문 회사명)"""
    data = _cached_json("sec_company_tickers.json",
                        "https://www.sec.gov/files/company_tickers.json", 24 * 7, refresh)
    t = ticker.upper().replace(".", "-")
    for row in data.values():
        if row["ticker"].upper() == t:
            return f"{int(row['cik_str']):010d}", row["title"]
    raise SecError(f"SEC 티커 목록에 '{ticker}'가 없어요. 미국 상장 티커가 맞는지 확인해 주세요.")


# ---------- 기간 계산 ----------

def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _month_of(end: date) -> tuple[int, int]:
    """52/53주 회계(예: 9월 28일 마감)를 가장 가까운 월말로 맞춘다. 15일 이전이면 전월."""
    if end.day < 15:
        end = end.replace(day=1) - timedelta(days=1)
    return end.year, end.month


def calendar_quarter(end: date) -> str:
    y, m = _month_of(end)
    return f"{y}Q{(m - 1) // 3 + 1}"


def fiscal_quarter(end: date, fye_month: int) -> tuple[int, int]:
    """(회계연도, 분기). 회계연도는 그 해가 끝나는 연도 기준 (MS 2026년 9월 → FY2027 1Q)."""
    y, m = _month_of(end)
    k = (m - fye_month) % 12
    fq = 4 if k == 0 else k // 3
    fy = y if m <= fye_month else y + 1
    return fy, fq


def quarter_label(end: date, fye_month: int) -> str:
    """카드에 쓰는 이름. 12월 결산이면 '2026 3Q', 아니면 'FY27 1Q (7~9월)'"""
    fy, fq = fiscal_quarter(end, fye_month)
    if fye_month == 12:
        return f"{fy} {fq}Q"
    _, m = _month_of(end)
    m0 = (m - 3) % 12 + 1
    return f"FY{fy % 100:02d} {fq}Q ({m0}~{m}월)"


# ---------- 분기값 만들기 ----------

def _facts_by_period(facts: dict, tags: list[str], unit: str = "USD") -> dict:
    """{(start, end): (val, filed, tag)} — 기간별 최신 제출값. 앞 태그가 우선."""
    out: dict = {}
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for rank, tag in enumerate(tags):
        rows = gaap.get(tag, {}).get("units", {}).get(unit, [])
        for r in rows:
            if "start" not in r or r.get("form", "").startswith("8-K"):
                continue
            key = (r["start"], r["end"])
            prev = out.get(key)
            cand = (rank, r["filed"], r["val"], tag)
            # 우선순위: 태그 순위가 높고(작은 rank) → 같은 태그면 늦게 제출된 값
            if prev is None or (cand[0], _neg(cand[1])) < (prev[0], _neg(prev[1])):
                out[key] = cand
    return {k: (v[2], v[1], v[3]) for k, v in out.items()}


def _neg(s: str) -> str:
    # 날짜 문자열 역순 정렬용 (늦게 제출된 게 먼저 오게)
    return "".join(chr(255 - ord(c)) for c in s)


def _days(start: str, end: str) -> int:
    return (_d(end) - _d(start)).days + 1


def quarterly_series(facts: dict, tags: list[str], unit: str = "USD") -> dict:
    """{분기 말일(str): {'val', 'start', 'method', 'tag', 'filed'}}"""
    periods = _facts_by_period(facts, tags, unit)
    q: dict = {}
    # 1) 3개월짜리 직접 공시
    for (s, e), (v, filed, tag) in periods.items():
        if 80 <= _days(s, e) <= 100:
            q[e] = {"val": v, "start": s, "method": "분기 공시", "tag": tag, "filed": filed}
    # 2) 누적값 차감: 같은 시작일(s)의 누적 e2 − 누적 e1, e1이 e2보다 약 3개월 앞
    by_start: dict = {}
    for (s, e), val in periods.items():
        by_start.setdefault(s, []).append((e, val))
    for s, rows in by_start.items():
        rows.sort()
        for e2, (v2, filed2, tag2) in rows:
            if e2 in q or _days(s, e2) < 150:
                continue
            for e1, (v1, _, _) in rows:
                gap = (_d(e2) - _d(e1)).days
                if 80 <= gap <= 100:
                    q[e2] = {"val": v2 - v1, "start": (_d(e1) + timedelta(days=1)).isoformat(),
                             "method": "누적 차감", "tag": tag2, "filed": filed2}
                    break
    return q


# ---------- 공시 목록 (실적 발표 당일 확인용) ----------

def recent_filings(cik: str, refresh: bool = False) -> dict:
    return _cached_json(f"sec_submissions_{cik}.json",
                        f"https://data.sec.gov/submissions/CIK{cik}.json", 6, refresh)


def latest_earnings_8k(subs: dict) -> dict | None:
    """가장 최근 실적 발표 8-K(Item 2.02)"""
    r = subs["filings"]["recent"]
    cik = int(subs["cik"])
    for i, form in enumerate(r["form"]):
        if form == "8-K" and "2.02" in (r.get("items", [""] * len(r["form"]))[i] or ""):
            acc = r["accessionNumber"][i].replace("-", "")
            return {"filed": r["filingDate"][i],
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"}
    return None


# ---------- 진입점 ----------

def collect(ticker: str, quarter: str, n: int = 6, refresh: bool = False) -> dict:
    """요청 분기(달력 기준 '2026Q3')를 끝으로 최근 n분기 데이터.

    요청 분기가 아직 공시(10-Q/10-K) 전이면 result['missing_target']=True 와
    최근 실적 발표 8-K 링크를 담아 돌려준다. (이때 분기 목록은 공시된 최근 n분기)
    """
    cik, title = ticker_to_cik(ticker, refresh)
    facts = _cached_json(f"sec_facts_{cik}.json",
                         f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", 12, refresh)
    subs = recent_filings(cik, refresh)
    fye_month = int(str(subs.get("fiscalYearEnd") or "1231")[:2])

    series = {k: quarterly_series(facts, tags) for k, tags in TAGS.items()}
    eps = quarterly_series(facts, EPS_TAGS, "USD/shares")

    ends = sorted(series["revenue"].keys())
    if not ends:
        raise SecError(f"{ticker}: XBRL에서 매출 데이터를 찾지 못했어요.")
    by_cq = {calendar_quarter(_d(e)): e for e in ends}

    missing = quarter not in by_cq
    if missing:
        last = ends[-1]
        if calendar_quarter(_d(last)) > quarter:
            raise SecError(f"{ticker}: {quarter} 데이터를 찾지 못했어요 (중간이 비어 있음).")
        target_end = last
    else:
        target_end = by_cq[quarter]
    picked = [e for e in ends if e <= target_end][-n:]

    quarters = []
    for e in picked:
        row = {"end": e, "start": series["revenue"][e]["start"],
               "calendar_quarter": calendar_quarter(_d(e)),
               "fiscal_quarter": "FY%d Q%d" % fiscal_quarter(_d(e), fye_month),
               "label": quarter_label(_d(e), fye_month), "values": {}, "notes": {}}
        for k, s in series.items():
            if e in s:
                row["values"][k] = s[e]["val"]
                row["notes"][k] = f"{s[e]['tag']} · {s[e]['method']}"
        if e in eps:
            row["values"]["eps"] = eps[e]["val"]
        v = row["values"]
        if "gross_profit" not in v and "revenue" in v and "cost_of_revenue" in v:
            v["gross_profit"] = v["revenue"] - v["cost_of_revenue"]
            row["notes"]["gross_profit"] = "매출 − 매출원가로 계산"
        if "operating_cash_flow" in v and "capex" in v:
            v["fcf"] = v["operating_cash_flow"] - v["capex"]
            row["notes"]["fcf"] = "영업현금흐름 − 설비투자로 계산"
        last_filed = max(s[e]["filed"] for s in series.values() if e in s)
        row["source"] = f"SEC EDGAR XBRL (제출 {last_filed})"
        quarters.append(row)

    return {
        "market": "US", "ticker": ticker.upper(), "cik": cik, "name_en": title,
        "currency": "USD", "fiscal_year_end_month": fye_month,
        "requested_quarter": quarter, "missing_target": missing,
        "latest_8k": latest_earnings_8k(subs) if missing else None,
        "quarters": quarters,
    }
