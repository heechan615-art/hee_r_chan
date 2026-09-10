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


def _dart_eps(corp, year, rc, fs):
    """해당 연도·보고서의 기본주당이익(원). 신/구 계정ID 모두 매칭. 없으면 None."""
    try:
        d = requests.get(f"{_DART}/fnlttSinglAcntAll.json",
                         params={"crtfc_key": _dart_key(), "corp_code": corp, "bsns_year": str(year),
                                 "reprt_code": rc, "fs_div": fs}, timeout=30).json()
    except Exception:
        return None
    if d.get("status") != "000":
        return None
    for it in d.get("list", []):
        if it.get("sj_div") not in ("IS", "CIS"):        # 손익계산서 또는 포괄손익계산서
            continue
        aid = it.get("account_id") or ""
        nm = it.get("account_nm") or ""
        # 표준 계정ID(BasicEPS) 또는 계정명('기본주당이익'). 우선주는 제외(보통주 기준).
        is_basic = ("BasicEarningsLossPerShare" in aid) or ("기본주당이익" in nm)
        if not is_basic or "우선주" in nm:
            continue
        v = (it.get("thstrm_amount") or "").replace(",", "").strip()
        try:
            return float(v)
        except ValueError:
            continue
    return None


def _kr_quarterly_eps(corp):
    """분기 EPS {분기말(date): eps(원, 발표당시 주식수 기준)}. 2015~올해.
    분기 thstrm은 회사별로 3개월 또는 누적 → 3분기/연간 비율로 자동 판별."""
    cy = dt.date.today().year
    ends = lambda y: {1: dt.date(y, 3, 31), 2: dt.date(y, 6, 30), 3: dt.date(y, 9, 30), 4: dt.date(y, 12, 31)}
    qeps = {}
    for y in range(2015, cy + 1):
        def eps(rc):
            e = _dart_eps(corp, y, rc, "CFS")
            return e if e is not None else _dart_eps(corp, y, rc, "OFS")
        c1, c2, c3 = eps("11013"), eps("11012"), eps("11014")
        A = eps("11011")
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


def kr_debug(ticker):
    """임시 진단: 프로덕션에서 한국 PER이 왜 비는지(키/corp/ DART응답) 확인용."""
    stock6 = re.sub(r"\D", "", str(ticker))[:6]
    out = {"has_key": bool(_dart_key()), "stock6": stock6}
    if not out["has_key"]:
        return out
    try:
        corp = _corp_code(stock6)
        out["corp"] = corp
        out["corp_map_size"] = len(_CORP)
        if corp:
            out["eps_2024_annual"] = _dart_eps(corp, 2024, "11011", "CFS")
    except Exception as e:
        out["err"] = repr(e)[:150]
    return out
