"""한국 기업 재무 데이터 수집기 — OpenDART (무료, .env 의 DART_API_KEY 필요)

- 종목코드 → 고유번호: corpCode.xml(zip) 받아서 cache/ 에 저장
- 재무: fnlttSinglAcntAll.json (연결 CFS 우선, 없으면 별도 OFS)
- 분기값 규칙 (응답 구조 확인 2026-10-29, 삼성전자)
  * 손익(IS/CIS): 1·반기·3분기 보고서 thstrm_amount = 그 분기 3개월, thstrm_add_amount = 누적
                  사업보고서 thstrm_amount = 연간 → 4분기 = 연간 − 3분기 누적
  * 현금흐름(CF): thstrm_amount = 누적 → 분기값 = 당기 누적 − 직전 분기 누적
- 12월 결산 기업 기준. 계정은 표준 account_id 우선, 없으면 계정 이름으로 찾는다.
"""
from __future__ import annotations

import io
import json
import os
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

import requests

try:  # 밸류AI 서버에는 python-dotenv가 없음 (키는 환경변수로)
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*a, **k):
        return False

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")

API = "https://opendart.fss.or.kr/api"
REPORTS = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}  # 분기 → reprt_code
REPORT_NAMES = {1: "1분기보고서", 2: "반기보고서", 3: "3분기보고서", 4: "사업보고서"}

# 항목 → (표준 account_id 후보, 계정 이름 후보, 성격 'is' 손익 / 'cf' 현금흐름)
ACCOUNTS = {
    "revenue": (["ifrs-full_Revenue"], ["매출액", "수익(매출액)", "영업수익", "매출"], "is"),
    "cost_of_revenue": (["ifrs-full_CostOfSales"], ["매출원가"], "is"),
    # 영업수익−영업비용 구조(카카오·네이버·금융사 등)는 매출원가가 없다 → 매출총이익도 만들지 않음
    "operating_expenses": (["dart_OperatingExpenses"], ["영업비용"], "is"),
    "gross_profit": (["ifrs-full_GrossProfit"], ["매출총이익"], "is"),
    "sga": (["dart_TotalSellingGeneralAdministrativeExpenses"],
            ["판매비와관리비", "판매비와 관리비", "판매비 및 관리비"], "is"),
    "operating_income": (["dart_OperatingIncomeLoss"], ["영업이익", "영업이익(손실)"], "is"),
    "net_income": (["ifrs-full_ProfitLossAttributableToOwnersOfParent", "ifrs-full_ProfitLoss"],
                   ["지배기업 소유주지분", "지배기업의 소유주에게 귀속되는 당기순이익",
                    "당기순이익", "분기순이익", "반기순이익", "당기순이익(손실)"], "is"),
    "operating_cash_flow": (["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
                            ["영업활동현금흐름", "영업활동으로 인한 현금흐름"], "cf"),
    "capex": (["ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
               "ifrs-full_PurchaseOfPropertyPlantAndEquipment"],
              ["유형자산의 취득", "유형자산의취득"], "cf"),
}
NET_INCOME_NOTE = {
    "ifrs-full_ProfitLossAttributableToOwnersOfParent": "지배주주 귀속",
    "ifrs-full_ProfitLoss": "연결 당기순이익(지배주주 구분 없음)",
}


class DartError(Exception):
    pass


def _key() -> str:
    k = os.environ.get("DART_API_KEY", "").strip()
    if not k:
        raise DartError("DART_API_KEY가 없어요. .env.example 을 .env 로 복사하고 키를 넣어 주세요.")
    return k


def _get(path: str, **params) -> requests.Response:
    params["crtfc_key"] = _key()
    r = requests.get(f"{API}/{path}", params=params, timeout=60)
    if r.status_code != 200:
        raise DartError(f"OpenDART 요청 실패 ({r.status_code}): {path}")  # URL엔 키가 있어 출력 안 함
    return r


def _check_status(data: dict) -> None:
    st = data.get("status")
    if st in ("010", "011", "012", "901"):
        raise DartError(f"OpenDART 키 문제 ({st}): {data.get('message')}")
    if st == "020":
        raise DartError("OpenDART 하루 요청 한도(2만 회)를 넘었어요. 내일 다시 해 주세요.")


# ---------- 종목코드 → 고유번호 ----------

def stock_to_corp(stock_code: str, refresh: bool = False) -> tuple[str, str]:
    """종목코드 → (고유번호 8자리, 회사명)"""
    path = CACHE / "dart_corpcode.json"
    if refresh or not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
        r = _get("corpCode.xml")
        if r.content[:2] != b"PK":
            _check_status(r.json())
            raise DartError("고유번호 파일을 받지 못했어요.")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(z.read(z.namelist()[0]))
        table = {}
        for el in root.iter("list"):
            sc = (el.findtext("stock_code") or "").strip()
            if sc:
                table[sc] = [el.findtext("corp_code"), el.findtext("corp_name")]
        path.write_text(json.dumps(table, ensure_ascii=False))
    table = json.loads(path.read_text())
    if stock_code not in table:
        raise DartError(f"종목코드 '{stock_code}'를 찾지 못했어요. 상장 종목코드 6자리가 맞는지 확인해 주세요.")
    return tuple(table[stock_code])


# ---------- 보고서 받기 ----------

def fetch_report(corp: str, year: int, q: int, refresh: bool = False) -> tuple[list, str] | None:
    """(계정 목록, 'CFS'/'OFS') 또는 아직 없으면 None. 있는 보고서는 계속 캐시, 없음은 6시간."""
    for fs in ("CFS", "OFS"):
        path = CACHE / f"dart_{corp}_{year}_{REPORTS[q]}_{fs}.json"
        data = None
        if path.exists() and not refresh:
            cached = json.loads(path.read_text())
            if cached.get("status") == "000" or time.time() - path.stat().st_mtime < 6 * 3600:
                data = cached
        if data is None:
            data = _get("fnlttSinglAcntAll.json", corp_code=corp, bsns_year=str(year),
                        reprt_code=REPORTS[q], fs_div=fs).json()
            _check_status(data)
            path.write_text(json.dumps(data, ensure_ascii=False))
        if data.get("status") == "000" and data.get("list"):
            return data["list"], fs
    return None


def _num(s) -> float | None:
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _find(rows: list, key: str) -> tuple[dict, str] | None:
    """계정 행 찾기. 손익은 IS → CIS 순, 현금흐름은 CF."""
    ids, names, kind = ACCOUNTS[key]
    sj = ["IS", "CIS"] if kind == "is" else ["CF"]
    for div in sj:
        part = [r for r in rows if r.get("sj_div") == div]
        for aid in ids:
            for r in part:
                if r.get("account_id") == aid:
                    return r, aid
        for nm in names:
            for r in part:
                if r.get("account_nm", "").replace(" ", "") == nm.replace(" ", ""):
                    return r, r.get("account_id") or nm
    return None


# ---------- 공시 검색 (잠정실적) ----------

def provisional_filings(corp: str, since: date) -> list[dict]:
    """since 이후 '영업(잠정)실적' 공시 목록"""
    try:
        data = _get("list.json", corp_code=corp, bgn_de=since.strftime("%Y%m%d"),
                    end_de=date.today().strftime("%Y%m%d"), page_count="100").json()
    except DartError:
        return []
    if data.get("status") != "000":
        return []
    out = []
    for r in data.get("list", []):
        if "잠정" in r.get("report_nm", "") and "실적" in r.get("report_nm", ""):
            out.append({"date": r["rcept_dt"], "title": r["report_nm"].strip(),
                        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}"})
    return out


# ---------- 진입점 ----------

def _qkey(y: int, q: int) -> str:
    return f"{y}Q{q}"


def _prev(y: int, q: int) -> tuple[int, int]:
    return (y, q - 1) if q > 1 else (y - 1, 4)


def collect(stock_code: str, quarter: str, n: int = 6, refresh: bool = False) -> dict:
    corp, name = stock_to_corp(stock_code, refresh)
    ty, tq = int(quarter[:4]), int(quarter[-1])

    # 필요한 보고서: 요청 분기부터 거슬러 n+4분기(누적 차감·10-Q 미제출 대비) 정도
    reports: dict = {}
    y, q = ty, tq
    for _ in range(n + 5):
        got = fetch_report(corp, y, q, refresh)
        if got:
            reports[(y, q)] = got
        y, q = _prev(y, q)

    def cum_value(y, q, key):
        """손익·현금흐름의 누적값 (q분기까지)."""
        if (y, q) not in reports:
            return None
        rows, _ = reports[(y, q)]
        hit = _find(rows, key)
        if not hit:
            return None
        r, _ = hit
        if ACCOUNTS[key][2] == "is" and q in (2, 3):
            return _num(r.get("thstrm_add_amount"))
        return _num(r.get("thstrm_amount"))

    quarters = []
    y, q = ty, tq
    missing = (ty, tq) not in reports
    for _ in range(n + 5):
        if len(quarters) == n:
            break
        if (y, q) in reports:
            rows, fs = reports[(y, q)]
            row = {"calendar_quarter": _qkey(y, q), "fiscal_quarter": f"FY{y} Q{q}",
                   "label": f"{y} {q}Q", "fs": fs, "values": {}, "notes": {}}
            for key, (_, _, kind) in ACCOUNTS.items():
                hit = _find(rows, key)
                if not hit:
                    continue
                aid = hit[1]
                val, how = None, ""
                if kind == "is" and q < 4:
                    val, how = _num(hit[0].get("thstrm_amount")), "분기 3개월"
                else:
                    cur = cum_value(y, q, key)
                    if q == 1:
                        val, how = cur, "1분기 누적 = 분기"
                    else:
                        prev = cum_value(y, q - 1, key)
                        if cur is not None and prev is not None:
                            val = cur - prev
                            how = ("연간 − 3분기 누적" if q == 4 and kind == "is"
                                   else f"{q}분기 누적 − {q - 1}분기 누적")
                if val is None:
                    continue
                if key == "capex":
                    val = abs(val)
                row["values"][key] = val
                note = NET_INCOME_NOTE.get(aid, aid) if key == "net_income" else aid
                row["notes"][key] = f"{note} · {how}"
            v = row["values"]
            if "gross_profit" not in v and "revenue" in v and "cost_of_revenue" in v:
                v["gross_profit"] = v["revenue"] - v["cost_of_revenue"]
                row["notes"]["gross_profit"] = "매출 − 매출원가로 계산"
            if "operating_cash_flow" in v and "capex" in v:
                v["fcf"] = v["operating_cash_flow"] - v["capex"]
                row["notes"]["fcf"] = "영업현금흐름 − 설비투자로 계산"
            row["source"] = f"OpenDART {y}년 {REPORT_NAMES[q]} ({'연결' if fs == 'CFS' else '별도'})"
            quarters.append(row)
        elif quarters:
            break  # 중간이 비면 거기서 멈춤 (빈칸 안 만들기)
        y, q = _prev(y, q)
    quarters.reverse()
    if not quarters:
        raise DartError(f"{stock_code} {name}: {quarter} 전후 정기보고서를 찾지 못했어요.")

    prov = []
    if missing:
        qe_month = tq * 3
        prov = provisional_filings(corp, date(ty, qe_month, 1))

    fs_set = {r["fs"] for r in quarters}
    return {
        "market": "KR", "ticker": stock_code, "corp_code": corp, "name_ko": name,
        "currency": "KRW", "fiscal_year_end_month": 12,
        "requested_quarter": quarter, "missing_target": missing,
        "provisional": prov, "mixed_fs": len(fs_set) > 1,
        "quarters": quarters,
    }
