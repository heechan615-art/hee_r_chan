"""
동종업계 비교(Peer Comparison) 모듈
====================================
- 자동 피어: 주요 섹터별 비교군을 미리 정의(PEER_GROUPS). 종목이 속한 그룹 자동 판별.
- 수동 피어: 사용자가 추가한 종목도 지표 조회.
- 지표: 선행 PER, PBR, ROE, 영업이익률, 시가총액.
  국내 배수(PER/PBR)는 야후가 안 줘서 네이버로 보강, 나머지는 yfinance.
"""
import re
import time
import yfinance as yf

import kr_data
from valuate import naver_eps, is_korean

# 섹터별 비교군 (한국 투자자 관심 섹터 위주). 코드/티커로 정의.
PEER_GROUPS = {
    "반도체": ["005930", "000660", "MU", "TSM", "NVDA", "INTC"],
    "자동차": ["005380", "000270", "TM", "VWAGY", "GM", "F"],
    "인터넷·플랫폼": ["035420", "035720", "GOOGL", "META", "BABA"],
    "2차전지": ["373220", "006400", "247540", "096770"],
    "빅테크": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "은행·금융": ["105560", "055550", "086790", "316140", "JPM", "BAC"],
    "바이오·제약": ["207940", "068270", "LLY", "PFE", "JNJ"],
    "철강·소재": ["005490", "004020", "NUE", "X"],
    "화학": ["051910", "011170", "DOW", "LYB"],
    "통신": ["017670", "030200", "T", "VZ"],
}

_PM_CACHE = {}   # {ticker: (ts, metrics)}
_PM_TTL = 3600
_MKT_CACHE = {}  # {market: (ts, row)}

# 시장 벤치마크 — 지수는 PER을 안 주므로 대표 ETF로 근사(후행 PER 기준)
_MARKET_ETF = {"US": ("SPY", "S&P500 시장평균"), "KR": ("EWY", "코스피 시장평균")}


def market_row(market):
    """시장 벤치마크 행 — S&P500(SPY)/코스피(EWY 근사)의 후행 PER·PBR. 캐시 1시간."""
    now = time.time()
    hit = _MKT_CACHE.get(market)
    if hit and now - hit[0] < _PM_TTL:
        return hit[1]
    tk, name = _MARKET_ETF.get(market, _MARKET_ETF["US"])
    try:
        info = yf.Ticker(tk).info
        row = {"ticker": "_MKT", "name": name,
               "fwd_per": info.get("trailingPE"), "pbr": info.get("priceToBook"),
               "roe": None, "opmargin": None, "mktcap": None,
               "cur": "KRW" if market == "KR" else "USD", "is_market": True}
        _MKT_CACHE[market] = (now, row)
        return row
    except Exception:
        return None


def peer_group(ticker):
    """종목이 속한 섹터 비교군 반환: (그룹명, [멤버코드…]) 또는 (None, [])."""
    code = re.sub(r"\.(KS|KQ)$", "", ticker.upper())
    for grp, members in PEER_GROUPS.items():
        if code in members:
            return grp, members
    return None, []


def peer_metrics(ticker):
    """종목 하나의 비교 지표. 캐시 1시간.
    반환: {ticker, name, fwd_per, pbr, roe, opmargin, mktcap, cur} 또는 None."""
    key = ticker.upper()
    now = time.time()
    hit = _PM_CACHE.get(key)
    if hit and now - hit[0] < _PM_TTL:
        return hit[1]
    try:
        yf_tk, code, nm = kr_data.resolve_query(ticker)
        if not yf_tk:
            return None
        info = yf.Ticker(yf_tk).info
        kr = is_korean(code or ticker)
        roe = info.get("returnOnEquity")
        om = info.get("operatingMargins")
        out = {
            "ticker": code or ticker.upper(),
            "name": nm or info.get("shortName") or (code or ticker),
            "fwd_per": info.get("forwardPE"),
            "pbr": info.get("priceToBook"),
            "roe": roe * 100 if roe is not None else None,
            "opmargin": om * 100 if om is not None else None,
            "mktcap": info.get("marketCap"),
            "cur": "KRW" if kr else info.get("currency", "USD"),
        }
        if kr:   # 국내 PER/PBR은 네이버로 보강 (야후가 국내 배수를 잘 안 줌)
            nv = naver_eps(code)
            if nv and "_err" not in nv:
                out["pbr"] = nv.get("pbr") or out["pbr"]
                out["fwd_per"] = nv.get("per_fwd") or out["fwd_per"]
        _PM_CACHE[key] = (now, out)
        return out
    except Exception:
        return None


def compare(ticker, extra=None):
    """비교 결과: 자동 피어 그룹 + 수동 추가(extra) 종목들의 지표.
    반환: {group, base, peers:[…]} — base는 현재 종목, peers는 비교군(자신 제외)."""
    grp, members = peer_group(ticker)
    base_code = re.sub(r"\.(KS|KQ)$", "", ticker.upper())
    codes = list(members)
    for e in (extra or []):
        yf_tk, c, _ = kr_data.resolve_query(e)
        c = c or (e.upper() if yf_tk else None)
        if c and c not in codes:
            codes.append(c)
    # 자기 자신 포함해 전부 조회, base는 별도 표시
    rows = []
    for c in codes:
        m = peer_metrics(c)
        if m:
            m["is_base"] = (m["ticker"] == base_code)
            rows.append(m)
    if base_code not in [r["ticker"] for r in rows]:
        bm = peer_metrics(ticker)
        if bm:
            bm["is_base"] = True
            rows.insert(0, bm)
    # 시장 벤치마크 행 (검색 종목 바로 아래에 표시하도록 플래그만; 위치는 프론트)
    mkt = market_row("KR" if is_korean(ticker) else "US")
    return {"group": grp, "rows": rows, "market": mkt}
