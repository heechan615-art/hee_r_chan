"""미국 개별주 장기 과거 PER 시계열.

PER = 야후 주가(분할조정) ÷ TTM EPS(분할 현재기준 보정).
EPS는 SEC EDGAR companyconcept(EarningsPerShareDiluted/Basic)에서 분기 EPS를
'최초 제출(원본)값'으로 모아 TTM(직전 4개 분기 합)을 만들고, 이후 발생한 주식분할
계수로 현재 주식수 기준으로 환산해 야후 분할조정 주가와 정합을 맞춘다.
(미국 전용 — 한국은 DART로 별도 처리 예정)
"""
import time
import bisect
import datetime as dt
import requests

# SEC는 연락처가 담긴 User-Agent를 요구
_UA = {"User-Agent": "hirchan-valuation research contact@example.com"}
_CIK = {}
_CACHE = {}
_TTL = 6 * 3600


def _cik(sym):
    if not _CIK:
        try:
            m = requests.get("https://www.sec.gov/files/company_tickers.json",
                             headers=_UA, timeout=20).json()
            for v in m.values():
                _CIK[v["ticker"].upper()] = str(v["cik_str"]).zfill(10)
        except Exception:
            pass
    return _CIK.get(sym.upper())


def _days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def _eps_quarterly(cik):
    """분기 EPS {period_end(date): eps} — 최초 제출값 기준, Q4는 연간-합으로 보정."""
    j = None
    for tag in ("EarningsPerShareDiluted", "EarningsPerShareBasic"):
        try:
            r = requests.get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json",
                             headers=_UA, timeout=20)
            if r.status_code == 200:
                j = r.json()
                break
        except Exception:
            pass
    if not j:
        return {}
    rows = list(j["units"].values())[0]
    q, ann = {}, {}
    for x in rows:
        s, e, v, f = x.get("start"), x.get("end"), x.get("val"), x.get("filed")
        if not (s and e and v is not None):
            continue
        d = _days(s, e)
        if 80 <= d <= 100:                       # 3개월(단일 분기)
            if e not in q or f < q[e][1]:        # 최초 제출값
                q[e] = (v, f)
        elif 350 <= d <= 385:                    # 연간
            if e not in ann or f < ann[e][1]:
                ann[e] = (v, f)

    def near(target):
        return next((e for e in q if abs((dt.date.fromisoformat(e) - target).days) <= 20), None)

    for e, (A, _) in ann.items():                # Q4 = 연간 - (Q1+Q2+Q3)
        if e in q:
            continue
        ed = dt.date.fromisoformat(e)
        a = near(ed - dt.timedelta(91)); b = near(ed - dt.timedelta(182)); c = near(ed - dt.timedelta(273))
        if a and b and c:
            q[e] = (A - (q[a][0] + q[b][0] + q[c][0]), "d")
    return {dt.date.fromisoformat(e): v for e, (v, _) in q.items()}


def _yahoo_weekly(sym):
    """야후 주봉 종가(분할조정) [(date, close)] + 분할 [(date, ratio)].
    Render 등 클라우드 IP에서 일반 requests는 야후가 차단 → curl_cffi(크롬 위장) 우선."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    params = {"range": "20y", "interval": "1wk", "events": "split"}
    j = None
    try:
        from curl_cffi import requests as creq
        j = creq.get(url, params=params, impersonate="chrome", timeout=15).json()
    except Exception:
        j = None
    if not j or not (j.get("chart") or {}).get("result"):
        j = requests.get(url, params=params, headers=_UA, timeout=20).json()   # 폴백
    r = j["chart"]["result"][0]
    ts, cl = r["timestamp"], r["indicators"]["quote"][0]["close"]
    px = [(dt.datetime.utcfromtimestamp(t).date(), c) for t, c in zip(ts, cl) if c]
    sp = (r.get("events", {}) or {}).get("splits", {}) or {}
    splits = sorted((dt.datetime.utcfromtimestamp(s["date"]).date(), s["numerator"] / s["denominator"])
                    for s in sp.values())
    return px, splits


def per_history(ticker):
    """미국 개별주 주간 과거 PER. 반환 {ticker, series:[{d,per}], latest, asof, source, years}.
    미국이 아니거나 EDGAR에 없으면 None."""
    sym = str(ticker).split(".")[0].upper()
    now = time.time()
    hit = _CACHE.get(sym)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    cik = _cik(sym)
    if not cik:
        return None
    q = _eps_quarterly(cik)
    if len(q) < 8:
        return None
    ends = sorted(q)
    ttm = {}
    for i in range(3, len(ends)):
        seg = ends[i - 3:i + 1]
        if (seg[-1] - seg[0]).days <= 290:
            ttm[seg[-1]] = sum(q[x] for x in seg)
    if len(ttm) < 4:
        return None
    try:
        px, splits = _yahoo_weekly(sym)
    except Exception:
        return None
    tq = sorted(ttm)

    def adj_eps(qend):
        f = 1.0
        for sd, ratio in splits:
            if sd > qend:
                f *= ratio
        return ttm[qend] / f if f else None

    ser = []
    for pdate, price in px:
        i = bisect.bisect_right(tq, pdate) - 1
        if i < 0:
            continue
        ae = adj_eps(tq[i])
        if ae and ae > 0:
            ser.append({"d": pdate.strftime("%Y-%m-%d"), "per": round(price / ae, 2)})
    if len(ser) < 20:
        return None
    out = {"ticker": sym, "series": ser, "latest": ser[-1]["per"], "asof": ser[-1]["d"],
           "source": "SEC EDGAR(EPS)+Yahoo(가격)", "years": round((tq[-1] - tq[0]).days / 365.25, 1)}
    _CACHE[sym] = (now, out)
    return out
