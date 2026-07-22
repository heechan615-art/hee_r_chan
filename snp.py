"""
S&P500 밸류에이션 대시보드 — 데이터 모듈 (자체 완결형)
========================================================
초보 투자자용 한 페이지 요약:
  ① S&P500 PER (2020년~현재) → 평균 ± 표준편차(σ) 1~3 밴드 (고평가/저평가)
  ② 밸류에이션 구간 (+3~-3σ)
  ③ EPS 성장 계산기 — 현재 EPS × (1 + GDP성장률 + 기대인플레이션) × 현재 PER = 추정 지수
  ④ CNN 공포·탐욕 지수 + 최근 1년 타임라인
  ⑤ VIX 변동성지수

외부 소스: multpl.com(PER·EPS), CNN(공탐), Yahoo Finance(VIX), FRED(GDPNow·BEI, 키 있으면).
모든 호출은 브라우저 지문 위장(curl_cffi) + 6시간 캐시. 방문 시 만료됐으면 자동 갱신.
"""
import os
import time
import datetime as dt
import statistics


# ------------------------------------------------------------------ 공통
def _creq():
    from curl_cffi import requests as creq
    return creq


_CACHE = {"ts": 0.0, "data": None}
_TTL = 6 * 3600  # 6시간


def _num(x):
    try:
        return round(float(x), 1)
    except (TypeError, ValueError):
        return None


# ------------------------------------------- ① PER (2020년부터 현재까지)
PE_START = dt.datetime(2020, 1, 1)


def sp500_pe_history(start=PE_START):
    """multpl.com에서 S&P500 PER(월별) — start 이후 + 평균/σ밴드 통계."""
    creq = _creq()
    r = creq.get("https://www.multpl.com/s-p-500-pe-ratio/table/by-month",
                 impersonate="chrome", timeout=25)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    table = soup.find("table", id="datatable")
    rows = []
    for tr in table.find_all("tr")[1:]:
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) != 2:
            continue
        try:
            d = dt.datetime.strptime(tds[0], "%b %d, %Y")
            v = float(tds[1].replace("†", "").replace(",", "").strip())
        except ValueError:
            continue
        rows.append((d, v))
    rows.sort(key=lambda x: x[0])                      # 과거→현재
    rows = [x for x in rows if x[0] >= start]
    if not rows:
        raise RuntimeError("PER 데이터를 받지 못했습니다.")

    series = [{"date": d.strftime("%Y-%m"), "pe": round(v, 2)} for d, v in rows]
    vals = [v for _, v in rows]
    mean = statistics.mean(vals)
    sd = statistics.pstdev(vals)
    current = vals[-1]
    bands = {k: round(mean + k * sd, 2) for k in (3, 2, 1, 0, -1, -2, -3)}
    z = (current - mean) / sd if sd else 0.0
    return {
        "series": series, "current": round(current, 2),
        "mean": round(mean, 2), "std": round(sd, 2), "bands": bands,
        "z": round(z, 2), "points": len(vals),
        "start": series[0]["date"], "end": series[-1]["date"],
    }


# ------------------------------------------------------------ ② 추정 EPS
def sp500_eps():
    """S&P500 EPS(TTM, multpl 실적표 — 최신값은 추정치 †)."""
    creq = _creq()
    from bs4 import BeautifulSoup
    out = {"ttm": None, "asof": None, "prev_year": None}
    try:
        r = creq.get("https://www.multpl.com/s-p-500-earnings/table/by-year",
                     impersonate="chrome", timeout=25)
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table", id="datatable")
        vals = []
        for tr in table.find_all("tr")[1:]:
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) != 2:
                continue
            try:
                d = dt.datetime.strptime(tds[0], "%b %d, %Y")
                v = float(tds[1].replace("†", "").replace(",", "").strip())
            except ValueError:
                continue
            vals.append((d, v))
        if vals:
            vals.sort(key=lambda x: x[0], reverse=True)
            out["ttm"] = round(vals[0][1], 2)
            out["asof"] = vals[0][0].strftime("%Y-%m-%d")
            if len(vals) > 1:
                out["prev_year"] = round(vals[1][1], 2)
    except Exception:
        pass
    return out


# ------------------------------------------------------------ ③ CNN 공포·탐욕
def cnn_fear_greed():
    """CNN 공포·탐욕 지수 (0~100) + 최근 1년 타임라인."""
    creq = _creq()
    r = creq.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                 impersonate="chrome", timeout=20)
    j = r.json()
    fg = j.get("fear_and_greed", {})
    score = fg.get("score")
    score = round(float(score)) if score is not None else None

    hist = []
    raw = (j.get("fear_and_greed_historical") or {}).get("data") or []
    for i, p in enumerate(raw):
        if i % 3 and i != len(raw) - 1:       # 3개당 1개(+마지막점 포함)
            continue
        try:
            ms = float(p["x"]); y = round(float(p["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        d = dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
        hist.append({"date": d, "score": y})

    return {
        "score": score, "rating": fg.get("rating"), "label": _fg_label(score),
        "prev_close": _num(fg.get("previous_close")),
        "week_ago": _num(fg.get("previous_1_week")),
        "month_ago": _num(fg.get("previous_1_month")),
        "history": hist,
    }


def _fg_label(s):
    if s is None:
        return "-"
    if s <= 24:
        return "극도의 공포"
    if s <= 44:
        return "공포"
    if s <= 55:
        return "중립"
    if s <= 75:
        return "탐욕"
    return "극도의 탐욕"


# ------------------------------------------------------------ ④ VIX
_VIX_CACHE = [0.0, None]


def vix_now():
    """VIX 변동성지수 현재값 + 초보용 등급.

    fear_greed._load_vix()를 재사용한다. 원래는 ^VIX를 period="10d"로 직접 받았는데
    로컬에선 되지만 Render에서는 늘 None이었다(야후가 클라우드 IP의 단기 조회를 막는 듯).
    같은 앱의 검증된 경로를 쓰면 6시간 캐시도 공유돼 야후 호출이 한 번으로 준다.
    """
    val = None
    try:
        now = time.time()
        if _VIX_CACHE[1] is not None and now - _VIX_CACHE[0] < _TTL:
            val = _VIX_CACHE[1]
        else:
            import fear_greed
            v = fear_greed._load_vix()
            if v is not None and len(v):
                val = round(float(v.iloc[-1]), 2)
                _VIX_CACHE[0], _VIX_CACHE[1] = now, val
    except Exception:
        val = None
    return {"value": val, "label": _vix_label(val), "level": _vix_level(val)}


# 0~20 매우 안전 / 20~28 불안전 / 28~37 위험 / 37~48 매우 위험 / 48~ 초고위험
_VIX_BANDS = [(20, "매우 안전", "safe"), (28, "불안전", "warn"),
              (37, "위험", "danger"), (48, "매우 위험", "danger2"),
              (999, "초고위험", "danger3")]


def _vix_label(v):
    if v is None:
        return "-"
    for hi, name, _ in _VIX_BANDS:
        if v < hi:
            return name
    return "초고위험"


def _vix_level(v):
    if v is None:
        return ""
    for hi, _, lvl in _VIX_BANDS:
        if v < hi:
            return lvl
    return "danger3"


# ------------------------------------------ ⑤ EPS 성장 계산기 기본값(FRED)
_FRED_CACHE = {}


def _fred_latest(series_id):
    """FRED 시계열 최신값 (key, date). FRED_API_KEY 없거나 실패 시 (None, None)."""
    import requests
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return None, None
    now = time.time()
    hit = _FRED_CACHE.get(series_id)
    if hit and now - hit[0] < _TTL:
        return hit[1], hit[2]
    start = time.strftime("%Y-%m-%d", time.localtime(now - 400 * 86400))
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series_id, "api_key": key, "file_type": "json",
                    "observation_start": start, "sort_order": "desc", "limit": 10},
            timeout=10)
        if r.status_code != 200:
            return None, None
        for o in r.json().get("observations", []):
            if o.get("value") not in (".", "", None):
                val = round(float(o["value"]), 2)
                _FRED_CACHE[series_id] = (now, val, o["date"])
                return val, o["date"]
    except Exception:
        pass
    return None, None


def macro_defaults():
    """EPS 성장 추정용 기본 입력값.
    GDP성장률 = 애틀랜타 연은 GDPNow(FRED: GDPNOW),
    물가 = 10년 기대인플레이션 BEI(FRED: T10YIE). 화면에서 수정 가능."""
    gdp, gdp_d = _fred_latest("GDPNOW")
    bei, bei_d = _fred_latest("T10YIE")
    return {"gdp": gdp, "gdp_date": gdp_d, "bei": bei, "bei_date": bei_d}


# ------------------------------------------------------------ 통합(캐시)
def overview(force=False):
    """대시보드 전체 데이터. 6시간 캐시 — 방문 시 만료됐으면 자동 갱신."""
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["ts"] < _TTL:
        d = dict(_CACHE["data"])
        d["cached"] = True
        return d

    errors = []
    try:
        pe = sp500_pe_history()
    except Exception as e:
        pe = None
        errors.append(f"PER: {repr(e)[:120]}")
    try:
        eps = sp500_eps()
    except Exception as e:
        eps = None
        errors.append(f"EPS: {repr(e)[:120]}")
    try:
        fg = cnn_fear_greed()
    except Exception as e:
        fg = None
        errors.append(f"공포탐욕: {repr(e)[:120]}")
    vix = vix_now()
    macro = macro_defaults()

    data = {"pe": pe, "eps": eps, "macro": macro, "fear_greed": fg, "vix": vix,
            "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "errors": errors, "cached": False}
    if pe:                       # PER 성공 시에만 캐시 저장
        _CACHE["ts"] = now
        _CACHE["data"] = data
    return data


if __name__ == "__main__":
    import json
    print(json.dumps(overview(force=True), ensure_ascii=False, indent=2))
