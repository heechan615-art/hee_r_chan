"""미국 개별주 장기 과거 PER 시계열.

PER = 야후 주가(분할조정) ÷ TTM EPS(분할 현재기준 보정).
EPS는 SEC EDGAR companyconcept(EarningsPerShareDiluted/Basic)에서 분기 EPS를
'최초 제출(원본)값'으로 모아 TTM(직전 4개 분기 합)을 만들고, 이후 발생한 주식분할
계수로 현재 주식수 기준으로 환산해 야후 분할조정 주가와 정합을 맞춘다.
(미국 전용 — 한국은 DART로 별도 처리 예정)
"""
import os
import io
import re
import time
import bisect
import zipfile
import datetime as dt
import xml.etree.ElementTree as ET
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
    """개별주 주간 과거 PER. 반환 {ticker, series:[{d,per}], latest, asof, source, years}.
    한국(숫자 코드)=DART, 미국=EDGAR. 데이터 없으면 None."""
    if str(ticker).split(".")[0].isdigit():        # 한국 종목(숫자 코드) → DART
        return per_history_kr(ticker)
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
            per = round(price / ae, 2)
            if 0.5 <= per <= 1000:                 # 명백한 데이터 왜곡 제외
                ser.append({"d": pdate.strftime("%Y-%m-%d"), "per": per})
    if len(ser) < 20:
        return None
    out = {"ticker": sym, "series": ser, "latest": ser[-1]["per"], "asof": ser[-1]["d"],
           "source": "SEC EDGAR(EPS)+Yahoo(가격)", "years": round((tq[-1] - tq[0]).days / 365.25, 1)}
    _CACHE[sym] = (now, out)
    return out


# ─────────────────────────── 한국(DART) ───────────────────────────
_DART = "https://opendart.fss.or.kr/api"
_CORP = {}          # stock_code(6) -> corp_code(8)  (프로세스 내 캐시)
_KRCACHE = {}


def _dart_key():
    return os.environ.get("DART_API_KEY")


def _corp_code(stock6):
    """DART 고유번호(corp_code). corpCode.xml(zip)을 최초 1회 받아 매핑 캐시."""
    if not _CORP:
        try:
            r = requests.get(f"{_DART}/corpCode.xml", params={"crtfc_key": _dart_key()}, timeout=40)
            z = zipfile.ZipFile(io.BytesIO(r.content))
            root = ET.fromstring(z.read(z.namelist()[0]))
            for c in root.iter("list"):
                sc = (c.findtext("stock_code") or "").strip()
                if sc and sc.isdigit():
                    _CORP[sc] = (c.findtext("corp_code") or "").strip()
        except Exception:
            pass
    return _CORP.get(stock6)


_DART_VALS = {}     # (corp, year, rc, fs) -> (ts, {"eps","rev"})  PER·PSR이 같은 DART 응답을 공유


def _dart_vals(corp, year, rc, fs):
    """해당 연도·보고서의 기본주당이익(원)과 매출액(원). 신/구 계정ID 모두 매칭."""
    k = (corp, year, rc, fs)
    hit = _DART_VALS.get(k)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    try:
        d = requests.get(f"{_DART}/fnlttSinglAcntAll.json",
                         params={"crtfc_key": _dart_key(), "corp_code": corp, "bsns_year": str(year),
                                 "reprt_code": rc, "fs_div": fs}, timeout=30).json()
    except Exception:
        return {}
    out = {}
    if d.get("status") == "000":
        def amt(it):
            v = (it.get("thstrm_amount") or "").replace(",", "").strip()
            try:
                return float(v)
            except ValueError:
                return None
        for it in d.get("list", []):
            if it.get("sj_div") not in ("IS", "CIS"):        # 손익계산서 또는 포괄손익계산서
                continue
            aid = it.get("account_id") or ""
            nm = (it.get("account_nm") or "").replace(" ", "")
            # 표준 계정ID(BasicEPS) 또는 계정명('기본주당이익'). 우선주는 제외(보통주 기준).
            if "eps" not in out and (("BasicEarningsLossPerShare" in aid) or ("기본주당이익" in nm)) and "우선주" not in nm:
                v = amt(it)
                if v is not None:
                    out["eps"] = v
            if "rev" not in out and (aid in ("ifrs-full_Revenue", "ifrs_Revenue")
                                     or nm in ("매출액", "수익(매출액)", "매출", "영업수익", "매출및지분법손익")):
                v = amt(it)
                if v is not None and v > 0:
                    out["rev"] = v
    _DART_VALS[k] = (time.time(), out)
    return out


def _dart_eps(corp, year, rc, fs):
    """해당 연도·보고서의 기본주당이익(원). 없으면 None."""
    return _dart_vals(corp, year, rc, fs).get("eps")


def _kr_quarterly_eps(corp):
    """분기 EPS {분기말(date): eps(원, 발표당시 주식수 기준)}. 2015~올해.
    분기 thstrm은 회사별로 3개월 또는 누적 → 3분기/연간 비율로 자동 판별."""
    from concurrent.futures import ThreadPoolExecutor
    cy = dt.date.today().year
    ends = lambda y: {1: dt.date(y, 3, 31), 2: dt.date(y, 6, 30), 3: dt.date(y, 9, 30), 4: dt.date(y, 12, 31)}
    years = list(range(2015, cy + 1))
    tasks = [(y, rc) for y in years for rc in ("11013", "11012", "11014", "11011")]

    def fetch(t):
        y, rc = t
        e = _dart_eps(corp, y, rc, "CFS")
        if e is None:
            e = _dart_eps(corp, y, rc, "OFS")
        return t, e

    res = {}
    with ThreadPoolExecutor(max_workers=8) as ex:      # 48콜 병렬 → 첫 호출 대기 단축
        for t, e in ex.map(fetch, tasks):
            res[t] = e

    qeps = {}
    for y in years:
        c1, c2, c3 = res.get((y, "11013")), res.get((y, "11012")), res.get((y, "11014"))
        A = res.get((y, "11011"))
        E = ends(y)
        if c1 is not None:
            qeps[E[1]] = c1                                  # Q1은 항상 단일분기
        cumulative = (A is not None and c3 is not None and abs(A) > 0 and c3 > 0.55 * abs(A))
        if cumulative:                                       # thstrm=누적 → 차분
            if c1 is not None and c2 is not None: qeps[E[2]] = c2 - c1
            if c2 is not None and c3 is not None: qeps[E[3]] = c3 - c2
            if c3 is not None and A is not None:  qeps[E[4]] = A - c3
        else:                                                # thstrm=3개월 → 그대로, Q4만 차분
            if c2 is not None: qeps[E[2]] = c2
            if c3 is not None: qeps[E[3]] = c3
            if None not in (c1, c2, c3, A): qeps[E[4]] = A - (c1 + c2 + c3)
    return qeps


def per_history_kr(ticker):
    """한국 개별주 주간 과거 PER (DART 기본주당이익→TTM, 분할보정 ÷ 야후 주가). ~12년."""
    if not _dart_key():
        return None
    stock6 = re.sub(r"\D", "", str(ticker))[:6]
    if len(stock6) != 6:
        return None
    now = time.time()
    hit = _KRCACHE.get(stock6)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    corp = _corp_code(stock6)
    if not corp:
        return None
    q = _kr_quarterly_eps(corp)
    if len(q) < 8:
        return None
    ends = sorted(q)
    ttm = {}
    for i in range(3, len(ends)):
        seg = ends[i - 3:i + 1]
        if (seg[-1] - seg[0]).days <= 300:
            ttm[seg[-1]] = sum(q[x] for x in seg)
    if len(ttm) < 4:
        return None
    yh = str(ticker) if "." in str(ticker) else stock6 + ".KS"
    try:
        px, splits = _yahoo_weekly(yh)
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
            per = round(price / ae, 2)
            if 0.5 <= per <= 1000:                 # 명백한 데이터 왜곡 제외
                ser.append({"d": pdate.strftime("%Y-%m-%d"), "per": per})
    if len(ser) < 20:
        return None
    out = {"ticker": stock6, "series": ser, "latest": ser[-1]["per"], "asof": ser[-1]["d"],
           "source": "DART(EPS)+Yahoo(가격)", "years": round((tq[-1] - tq[0]).days / 365.25, 1)}
    _KRCACHE[stock6] = (now, out)
    return out


# ─────────────────────────── 과거 PSR (주가 ÷ 주당매출) ───────────────────────────
# PSR = 주가 × 주식수 ÷ TTM 매출. 주식수는 공시 당시 기준이라 이후 분할 계수를 곱해
# 야후 분할조정 주가와 맞춘다(PER의 EPS 보정과 같은 원리).
_PSR_CACHE = {}
_REV_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
             "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet")
_SHARE_TAGS = ("WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic")


_FACTS = {}


def _concept(cik, tag):
    """SEC companyfacts(회사 전체 XBRL 1회 요청)에서 태그 행 목록. 필요한 태그만 캐시.
    (companyconcept 개별 요청은 회사에 따라 빈 값이 오는 경우가 있어 companyfacts 사용)"""
    hit = _FACTS.get(cik)
    if not hit or time.time() - hit[0] > _TTL:
        g = {}
        try:
            r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                             headers=_UA, timeout=30)
            if r.status_code == 200:
                allg = r.json().get("facts", {}).get("us-gaap", {})
                for t in _REV_TAGS + _SHARE_TAGS:
                    if t in allg:
                        g[t] = list(allg[t]["units"].values())[0]
        except Exception:
            pass
        hit = (time.time(), g)
        _FACTS[cik] = hit
    return hit[1].get(tag, [])


def _quarterize(rows, flow=True):
    """XBRL 행 → {분기말(date): 값}. 최초 제출값. flow=True면 Q4 = 연간 − (Q1~Q3),
    False(가중평균 주식수)면 Q4가 없을 때 연간값으로 대체."""
    q, ann = {}, {}
    for x in rows:
        st, e, v, f = x.get("start"), x.get("end"), x.get("val"), x.get("filed")
        if not (st and e and v is not None):
            continue
        d = _days(st, e)
        if 80 <= d <= 100:
            if e not in q or f < q[e][1]:
                q[e] = (v, f)
        elif 350 <= d <= 385:
            if e not in ann or f < ann[e][1]:
                ann[e] = (v, f)

    def near(target):
        return next((e for e in q if abs((dt.date.fromisoformat(e) - target).days) <= 20), None)

    for e, (A, _) in ann.items():
        if e in q:
            continue
        if not flow:
            q[e] = (A, "a")
            continue
        ed = dt.date.fromisoformat(e)
        a = near(ed - dt.timedelta(91)); b = near(ed - dt.timedelta(182)); c = near(ed - dt.timedelta(273))
        if a and b and c:
            q[e] = (A - (q[a][0] + q[b][0] + q[c][0]), "d")
    return {dt.date.fromisoformat(e): v for e, (v, _) in q.items()}


def _ttm(q, max_span):
    ends = sorted(q)
    out = {}
    for i in range(3, len(ends)):
        seg = ends[i - 3:i + 1]
        if (seg[-1] - seg[0]).days <= max_span:
            out[seg[-1]] = sum(q[x] for x in seg)
    return out


def _psr_series(ttm_rev, shares, px, splits):
    """주간 PSR 시계열. shares: {분기말: 주식수(공시 당시)}."""
    tq = sorted(ttm_rev)
    sq = sorted(shares)
    ser = []
    for pdate, price in px:
        i = bisect.bisect_right(tq, pdate) - 1
        if i < 0:
            continue
        qend = tq[i]
        j = bisect.bisect_right(sq, qend + dt.timedelta(days=20)) - 1   # 그 분기(또는 직전)의 주식수
        if j < 0 or (qend - sq[j]).days > 200:
            continue
        f = 1.0
        for sd, ratio in splits:
            if sd > sq[j]:
                f *= ratio
        rev = ttm_rev[qend]
        if not rev or rev <= 0:
            continue
        psr = price * shares[sq[j]] * f / rev
        if 0.02 <= psr <= 3000:
            ser.append({"d": pdate.strftime("%Y-%m-%d"), "psr": round(psr, 3)})
    return ser


def psr_history(ticker):
    """개별주 주간 과거 PSR. 반환 {ticker, series:[{d,psr}], latest, asof, source, years} 또는 None."""
    if str(ticker).split(".")[0].isdigit():
        return psr_history_kr(ticker)
    sym = str(ticker).split(".")[0].upper()
    hit = _PSR_CACHE.get(sym)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    cik = _cik(sym)
    if not cik:
        return None
    rev = {}
    for tag in _REV_TAGS:                      # 회사마다·연도마다 매출 태그가 바뀜 → 합침(앞 태그 우선)
        for k, v in _quarterize(_concept(cik, tag)).items():
            if k not in rev and v and v > 0:
                rev[k] = v
    shares = {}
    for tag in _SHARE_TAGS:
        for k, v in _quarterize(_concept(cik, tag), flow=False).items():
            if k not in shares and v and v > 0:
                shares[k] = v
        if len(shares) >= 8:
            break
    ttm = _ttm(rev, 290)
    if len(ttm) < 4 or not shares:
        return None
    try:
        px, splits = _yahoo_weekly(sym)
    except Exception:
        return None
    ser = _psr_series(ttm, shares, px, splits)
    if len(ser) < 20:
        return None
    tq = sorted(ttm)
    out = {"ticker": sym, "series": ser, "latest": ser[-1]["psr"], "asof": ser[-1]["d"],
           "source": "SEC EDGAR(매출·주식수)+Yahoo(가격)", "years": round((tq[-1] - tq[0]).days / 365.25, 1)}
    _PSR_CACHE[sym] = (time.time(), out)
    return out


def _dart_shares(corp, year, rc):
    """보통주 유통주식수(발행 − 자기주식). DART 주식총수 현황."""
    k = ("SH", corp, year, rc)
    hit = _DART_VALS.get(k)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    v = None
    try:
        d = requests.get(f"{_DART}/stockTotqySttus.json",
                         params={"crtfc_key": _dart_key(), "corp_code": corp, "bsns_year": str(year),
                                 "reprt_code": rc}, timeout=30).json()
        if d.get("status") == "000":
            rows = d.get("list", [])
            num = lambda x: float(str(x).replace(",", "")) if x and str(x).replace(",", "").replace(".", "").isdigit() else None
            row = next((r for r in rows if "보통" in (r.get("se") or "")), None) or \
                next((r for r in rows if "합계" in (r.get("se") or "")), None)
            if row:
                v = num(row.get("distb_stock_co")) or num(row.get("istc_totqy"))
    except Exception:
        v = None
    _DART_VALS[k] = (time.time(), v)
    return v


def psr_history_kr(ticker):
    """한국 개별주 주간 과거 PSR (DART 분기 매출→TTM, DART 유통주식수, 야후 주가)."""
    if not _dart_key():
        return None
    stock6 = re.sub(r"\D", "", str(ticker))[:6]
    if len(stock6) != 6:
        return None
    hit = _PSR_CACHE.get(stock6)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    corp = _corp_code(stock6)
    if not corp:
        return None
    from concurrent.futures import ThreadPoolExecutor
    cy = dt.date.today().year
    years = list(range(2015, cy + 1))
    rcs = ("11013", "11012", "11014", "11011")
    tasks = [(y, rc) for y in years for rc in rcs]

    def fetch(t):
        y, rc = t
        v = _dart_vals(corp, y, rc, "CFS")
        if v.get("rev") is None:
            v = _dart_vals(corp, y, rc, "OFS")
        return t, v.get("rev"), _dart_shares(corp, y, rc)

    res, shr = {}, {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, r, sh in ex.map(fetch, tasks):
            res[t], shr[t] = r, sh
    ends = lambda y: {1: dt.date(y, 3, 31), 2: dt.date(y, 6, 30), 3: dt.date(y, 9, 30), 4: dt.date(y, 12, 31)}
    qrev, shares = {}, {}
    for y in years:
        c1, c2, c3, A = (res.get((y, rc)) for rc in rcs)
        E = ends(y)
        for qi, rc in zip((1, 2, 3, 4), rcs):
            if shr.get((y, rc)):
                shares[E[qi]] = shr[(y, rc)]
        if c1 is not None:
            qrev[E[1]] = c1
        cumulative = (A is not None and c3 is not None and c3 > 0.55 * A)
        if cumulative:
            if c1 is not None and c2 is not None: qrev[E[2]] = c2 - c1
            if c2 is not None and c3 is not None: qrev[E[3]] = c3 - c2
            if c3 is not None and A is not None:  qrev[E[4]] = A - c3
        else:
            if c2 is not None: qrev[E[2]] = c2
            if c3 is not None: qrev[E[3]] = c3
            if None not in (c1, c2, c3, A): qrev[E[4]] = A - (c1 + c2 + c3)
    qrev = {k: v for k, v in qrev.items() if v and v > 0}
    ttm = _ttm(qrev, 300)
    if len(ttm) < 4 or not shares:
        return None
    px, splits = [], []
    for yh in ([str(ticker)] if "." in str(ticker) else [stock6 + ".KS", stock6 + ".KQ"]):
        try:
            px, splits = _yahoo_weekly(yh)
        except Exception:
            px = []
        if px:
            break
    if not px:
        return None
    ser = _psr_series(ttm, shares, px, splits)
    if len(ser) < 20:
        return None
    tq = sorted(ttm)
    out = {"ticker": stock6, "series": ser, "latest": ser[-1]["psr"], "asof": ser[-1]["d"],
           "source": "DART(매출·주식수)+Yahoo(가격)", "years": round((tq[-1] - tq[0]).days / 365.25, 1)}
    _PSR_CACHE[stock6] = (time.time(), out)
    return out
