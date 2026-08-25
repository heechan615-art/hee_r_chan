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
import io
import re
import json
import time
import datetime as dt
import statistics

import config as C


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
_RAW_PE = {"ts": 0.0, "rows": None}   # 전체(1871~) 월별 원본 캐시 — 기간 전환 시 재조회 방지


def _fetch_pe_rows():
    """multpl.com 전체 월별 PER(1871~현재) 원본. 6시간 캐시."""
    now = time.time()
    if _RAW_PE["rows"] and now - _RAW_PE["ts"] < _TTL:
        return _RAW_PE["rows"]
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
    if rows:
        _RAW_PE["ts"], _RAW_PE["rows"] = now, rows
    return rows


def sp500_pe_history(start=PE_START):
    """선택 기간(start 이후)의 PER 시계열 + 평균/σ밴드 통계. 원본은 캐시라 기간 전환이 빠름."""
    rows = [x for x in _fetch_pe_rows() if x[0] >= start]
    if not rows:
        raise RuntimeError("PER 데이터를 받지 못했습니다.")

    series = [{"date": d.strftime("%Y-%m"), "pe": round(v, 2)} for d, v in rows]
    vals = [v for _, v in rows]
    mean = statistics.mean(vals)
    sd = statistics.pstdev(vals)
    current = vals[-1]
    bands = {k: round(mean + k * sd, 2) for k in (3, 2, 1, 0, -1, -2, -3)}
    z = (current - mean) / sd if sd else 0.0
    all_rows = _RAW_PE["rows"] or rows
    return {
        "series": series, "current": round(current, 2),
        "mean": round(mean, 2), "std": round(sd, 2), "bands": bands,
        "z": round(z, 2), "points": len(vals),
        "start": series[0]["date"], "end": series[-1]["date"],
        "min_year": all_rows[0][0].year,      # 원본에서 가장 오래된 연도(전체 옵션용)
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


# ---- EPS 시계열(월별, 1871~) — PER과 같은 방식의 추이 차트용 ----
_RAW_EPS = {"ts": 0.0, "rows": None}


def _fetch_eps_rows():
    """multpl.com 전체 월별 S&P500 EPS(TTM, 1871~현재) 원본. 6시간 캐시."""
    now = time.time()
    if _RAW_EPS["rows"] and now - _RAW_EPS["ts"] < _TTL:
        return _RAW_EPS["rows"]
    creq = _creq()
    from bs4 import BeautifulSoup
    r = creq.get("https://www.multpl.com/s-p-500-earnings/table/by-month",
                 impersonate="chrome", timeout=25)
    soup = BeautifulSoup(r.text, "lxml")
    table = soup.find("table", id="datatable")
    rows = []
    for tr in table.find_all("tr")[1:]:
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) != 2:
            continue
        try:
            d = dt.datetime.strptime(tds[0], "%b %d, %Y")
            v = float(tds[1].replace("†", "").replace(",", "").replace("$", "").strip())
        except ValueError:
            continue
        rows.append((d, v))
    rows.sort(key=lambda x: x[0])
    if rows:
        _RAW_EPS["ts"], _RAW_EPS["rows"] = now, rows
    return rows


def sp500_eps_history(start):
    """선택 기간의 EPS(TTM) 시계열 + 성장률/연평균성장률(CAGR). σ밴드 없음(절대값이라)."""
    rows = [x for x in _fetch_eps_rows() if x[0] >= start]
    if len(rows) < 2:
        return None
    series = [{"date": d.strftime("%Y-%m"), "eps": round(v, 2)} for d, v in rows]
    first, last = rows[0][1], rows[-1][1]
    last_d = rows[-1][0]
    growth = (last / first - 1) * 100 if first > 0 else None
    years = (last_d - rows[0][0]).days / 365.25
    cagr = ((last / first) ** (1 / years) - 1) * 100 if (first > 0 and years >= 1) else None

    # 향후 2년 예상 EPS — CAGR을 복리로 적용, 매끄러운 곡선 위해 월별 24개 포인트
    projection, proj_1y, proj_2y = [], None, None
    if cagr is not None:
        m_rate = (1 + cagr / 100.0) ** (1 / 12.0) - 1        # 월 복리율
        for k in range(1, 25):
            y = last_d.year + (last_d.month - 1 + k) // 12
            mo = (last_d.month - 1 + k) % 12 + 1
            projection.append({"date": dt.datetime(y, mo, 1).strftime("%Y-%m"),
                               "eps": round(last * (1 + m_rate) ** k, 2)})
        proj_1y = round(last * (1 + cagr / 100.0), 2)         # +1년
        proj_2y = round(last * (1 + cagr / 100.0) ** 2, 2)    # +2년

    return {
        "series": series, "current": round(last, 2),
        "start_eps": round(first, 2), "start": series[0]["date"], "end": series[-1]["date"],
        "points": len(series),
        "growth_pct": round(growth, 1) if growth is not None else None,
        "cagr": round(cagr, 1) if cagr is not None else None,
        "projection": projection,
        "proj_1y": proj_1y, "proj_2y": proj_2y,
        "proj_1y_year": last_d.year + 1, "proj_2y_year": last_d.year + 2,
    }


def sp500_eps_qoq(start, horizon=4):
    """분기말 TTM EPS(월별 테이블에서 3·6·9·12월 샘플링) + 전분기比(QoQ) +
    평균 QoQ를 복리로 적용한 향후 horizon개 분기 추정. multpl이 최신 분기까지만
    실적을 주므로, 다음 분기(4~6·7~9·10~12월) TTM EPS를 이 방식으로 예측한다."""
    q, seen = [], set()
    for d, v in _fetch_eps_rows():
        if d < start or d.month not in (3, 6, 9, 12):
            continue
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            q.append((d, v))
    if len(q) < 3:
        return None
    series = []
    for i, (d, v) in enumerate(q):
        qoq = round((v / q[i - 1][1] - 1) * 100, 2) if i >= 1 and q[i - 1][1] > 0 else None
        series.append({"date": d.strftime("%Y-%m"), "eps": round(v, 2), "qoq": qoq})
    # 평균 QoQ = 분기 성장비의 기하평균(= 분기 CAGR)
    ratios = [q[i][1] / q[i - 1][1] for i in range(1, len(q)) if q[i - 1][1] > 0]
    avg_qoq = None
    if ratios:
        gm = 1.0
        for r in ratios:
            gm *= r
        avg_qoq = round((gm ** (1.0 / len(ratios)) - 1) * 100, 2)
    # 향후 분기 추정 — 마지막 실제 TTM에서 avg_qoq 복리
    proj, last_d, cur = [], q[-1][0], q[-1][1]
    dd = last_d
    if avg_qoq is not None:
        rate = avg_qoq / 100.0
        for _ in range(horizon):
            m, y = dd.month + 3, dd.year
            if m > 12:
                m -= 12
                y += 1
            dd = dt.datetime(y, m, 1)
            cur *= (1 + rate)
            proj.append({"date": dd.strftime("%Y-%m"), "eps": round(cur, 2),
                         "qoq": avg_qoq})
    return {"series": series, "projection": proj, "avg_qoq": avg_qoq,
            "current": round(q[-1][1], 2), "last_date": last_d.strftime("%Y-%m"),
            "start": series[0]["date"], "end": series[-1]["date"], "points": len(series)}


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
# 기간 옵션: 롤링(최근 N년, 오늘 기준) + 고정연도 + 전체
PERIODS = [
    {"id": "10y",  "label": "최근 10년"},
    {"id": "20y",  "label": "최근 20년"},
    {"id": "2020", "label": "2020년~"},
    {"id": "2000", "label": "2000년~"},
    {"id": "all",  "label": "전체"},
]
_PERIOD_IDS = {p["id"] for p in PERIODS}
_BASE = {"ts": 0.0, "data": None}                 # PER 외 지표(EPS/공탐/VIX/매크로) 캐시


def _period_start(period):
    """기간 id → 시작 datetime. 10y/20y는 오늘 기준 롤링."""
    n = dt.datetime.now()
    if period == "10y":
        return dt.datetime(n.year - 10, n.month, 1)
    if period == "20y":
        return dt.datetime(n.year - 20, n.month, 1)
    if period == "all":
        return dt.datetime(1800, 1, 1)            # 원본 전체(1871~)
    try:
        return dt.datetime(int(period), 1, 1)      # 고정 연도
    except (TypeError, ValueError):
        return dt.datetime(2020, 1, 1)


# ============================================================ 자동 데이터 수급
# 디스크 영속 캐시 — Render 무료 티어는 슬립되므로 "요청 시 갱신 + TTL".
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_CACHE_FILE = os.path.join(_DATA_DIR, "snp_cache.json")


def _disk_load():
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _disk_save(store):
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False)
        os.replace(tmp, _CACHE_FILE)
    except Exception:
        pass


_STORE = _disk_load()


def _cached(key, ttl, fetcher, validate=None, force=False):
    """요청 시 갱신 + TTL + 디스크 영속 + 마지막 성공값 폴백. (data, asof, fresh)."""
    now = time.time()
    ent = _STORE.get(key)
    if not force and ent and now - ent.get("ts", 0) < ttl and ent.get("data") is not None:
        return ent["data"], ent.get("asof"), False
    try:
        data = fetcher()
        if data is not None and (validate is None or validate(data)):
            asof = dt.date.today().isoformat()
            _STORE[key] = {"ts": now, "data": data, "asof": asof}
            _disk_save(_STORE)
            return data, asof, True
    except Exception:
        pass
    if ent and ent.get("data") is not None:
        return ent["data"], ent.get("asof"), False
    return None, None, False


# ---------------------------------------- FRED (SEP 전망 · S&P500 지수)
def _fred_obs(series_id, n=15):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return []
    import requests
    r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id": series_id, "api_key": key,
                             "file_type": "json", "sort_order": "desc", "limit": n},
                     timeout=12)
    if r.status_code != 200:
        return []
    return [(o.get("date"), o.get("value")) for o in r.json().get("observations", [])]


def _sep_year(series_id, lr_series, year):
    for d, v in _fred_obs(series_id):
        if d and d[:4] == str(year) and v not in (".", "", None):
            return round(float(v), 2)
    for d, v in _fred_obs(lr_series, 6):
        if v not in (".", "", None):
            return round(float(v), 2)
    return None


def fetch_sep():
    """FOMC SEP 중앙값 — 실질GDP성장률/헤드라인 PCE, 2027·2028 (longer-run 폴백)."""
    gdp27 = _sep_year("GDPC1MD", "GDPC1MDLR", 2027)
    gdp28 = _sep_year("GDPC1MD", "GDPC1MDLR", 2028)
    pce27 = _sep_year("PCECTPIMD", "PCECTPIMDLR", 2027)
    pce28 = _sep_year("PCECTPIMD", "PCECTPIMDLR", 2028)
    if gdp27 is None or pce27 is None:
        return None
    return {"gdp": {"2027": gdp27, "2028": gdp28},
            "pce": {"2027": pce27, "2028": pce28}}


def fetch_index():
    """현재 S&P500 지수 — FRED SP500, 실패 시 Finnhub 폴백."""
    for d, v in _fred_obs("SP500", 10):
        if v not in (".", "", None):
            return {"value": round(float(v), 2), "date": d, "source": "FRED"}
    key = os.environ.get("FINNHUB_API_KEY")
    if key:
        try:
            import requests
            r = requests.get("https://finnhub.io/api/v1/quote",
                             params={"symbol": "^GSPC", "token": key}, timeout=8)
            c = (r.json() or {}).get("c")
            if c:
                return {"value": round(float(c), 2),
                        "date": dt.date.today().isoformat(), "source": "Finnhub"}
        except Exception:
            pass
    return None


# ---------------------------------------- FactSet Earnings Insight (주간 PDF)
_FACTSET_URL = ("https://advantage.factset.com/hubfs/Website/Resources%20Section/"
                "Research%20Desk/Earnings%20Insight/EarningsInsight_{d}.pdf")
_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December")


def _recent_fridays(n=8):
    out, d = [], dt.date.today()
    while len(out) < n:
        if d.weekday() == 4:
            out.append(d)
        d -= dt.timedelta(days=1)
    return out


def parse_factset_bytes(content):
    """FactSet Earnings Insight PDF → 지수/선행·후행 P/E → EPS 역산.
    (CY 연간 EPS는 차트 이미지라 텍스트 추출 불가 → 선행 12M EPS = 지수÷선행P/E)"""
    import pypdf
    rd = pypdf.PdfReader(io.BytesIO(content))
    txt = "\n".join(p.extract_text() for p in rd.pages)
    txt = re.sub(r"(?<=\d)\s(?=\d)", "", txt)
    def f(pat):
        m = re.search(pat, txt)
        return float(m.group(1).replace(",", "")) if m else None
    idx = f(r"closing price of ([\d,]+\.\d+)")
    fpe = f(r"forward 12-month P/E ratio is (\d+\.\d+)")
    tpe = f(r"trailing 12-month P/E ratio is (\d+\.\d+)")
    tgt = f(r"target price for the S&P 500 is ([\d,]+\.\d+)")
    md = re.search(rf"({_MONTHS})\s*(\d{{1,2}}),\s*(20\d\d)", txt)
    fwd = round(idx / fpe, 2) if idx and fpe else None
    ttm = round(idx / tpe, 2) if idx and tpe else None
    if not (ttm and fwd):
        return None
    return {"index": idx, "fwd_pe": fpe, "ttm_pe": tpe, "target": tgt,
            "fwd_eps": fwd, "ttm_eps": ttm,
            "report_date": md.group(0) if md else None}


def _factset_valid(d):
    if not d:
        return False
    ttm, fwd = d.get("ttm_eps") or 0, d.get("fwd_eps") or 0
    return C.EPS_SANITY_MIN <= ttm <= C.EPS_SANITY_MAX and 200 <= fwd <= 700


def fetch_factset():
    creq = _creq()
    for fri in _recent_fridays(8):
        url = _FACTSET_URL.format(d=fri.strftime("%m%d%y"))
        try:
            r = creq.get(url, impersonate="chrome", timeout=30)
            if r.status_code == 200 and len(r.content) > 50000:
                p = parse_factset_bytes(r.content)
                if _factset_valid(p):
                    return p
        except Exception:
            continue
    return None


# ---------------------------------------- 파생 계산 (매크로·컨센서스 밸류)
def compute_valuation(index_val, ttm_eps, fwd_eps, sep):
    bands = C.PER_BANDS

    def matrix(eps):
        return {"bear": round(eps * bands[0]), "base": round(eps * bands[1]),
                "bull": round(eps * bands[2])}

    def upside(t):
        return {k: (round((v / index_val - 1) * 100, 1) if index_val else None)
                for k, v in t.items()}

    out = {"per_bands": bands, "eps_premium": C.EPS_PREMIUM,
           "ten_year_avg_fwd_per": C.TEN_YEAR_AVG_FORWARD_PER}
    macro = None
    if ttm_eps and sep:
        nom27 = sep["gdp"]["2027"] + sep["pce"]["2027"]
        nom28 = sep["gdp"]["2028"] + sep["pce"]["2028"]
        g27 = nom27 / 100 + C.EPS_PREMIUM / 100
        g28 = nom28 / 100 + C.EPS_PREMIUM / 100
        eps27 = ttm_eps * (1 + g27)
        eps28 = eps27 * (1 + g28)
        macro = {"nominal": {"2027": round(nom27, 2), "2028": round(nom28, 2)},
                 "eps_growth": {"2027": round(g27 * 100, 2), "2028": round(g28 * 100, 2)},
                 "eps": {"2027": round(eps27, 2), "2028": round(eps28, 2)},
                 "targets": {"2027": matrix(eps27), "2028": matrix(eps28)}}
        macro["upside"] = {"2027": upside(macro["targets"]["2027"]),
                           "2028": upside(macro["targets"]["2028"])}
    cons = None
    if fwd_eps:
        cons = {"fwd_eps": fwd_eps,
                "fwd_per": round(index_val / fwd_eps, 2) if index_val else None,
                "targets": matrix(fwd_eps)}
        cons["upside"] = upside(cons["targets"])
    gap = None
    if macro and cons:
        mb = macro["targets"]["2027"]["base"]
        cb = cons["targets"]["base"]
        gap = round((cb - mb) / mb * 100, 1) if mb else None
    out["macro"], out["consensus"], out["gap"] = macro, cons, gap
    return out


def apply_factset_upload(content):
    """사용자가 올린 FactSet PDF 파싱 → 캐시 저장. 성공 시 dict / 실패 None."""
    p = parse_factset_bytes(content)
    if not _factset_valid(p):
        return None
    _STORE["factset"] = {"ts": time.time(), "data": p, "asof": dt.date.today().isoformat()}
    _disk_save(_STORE)
    return p


def overview(force=False, period="2020"):
    """대시보드 데이터. period로 PER 기간 선택(σ밴드 재계산). PER 외 지표는 6시간 캐시 공유."""
    now = time.time()
    period = str(period)
    if period not in _PERIOD_IDS:
        period = "2020"

    errors = []
    start_dt = _period_start(period)
    # ① PER — 기간별 재계산 (원본 rows는 캐시라 빠름)
    try:
        pe = sp500_pe_history(start_dt)
    except Exception as e:
        pe = None
        errors.append(f"PER: {repr(e)[:120]}")
    # ①-b EPS 추이 — 같은 기간 (원본 캐시)
    try:
        eps_hist = sp500_eps_history(start_dt)
    except Exception as e:
        eps_hist = None
        errors.append(f"EPS추이: {repr(e)[:120]}")
    try:
        eps_qoq = sp500_eps_qoq(start_dt)
    except Exception as e:
        eps_qoq = None
        errors.append(f"EPS QoQ: {repr(e)[:120]}")

    # ② PER 외 지표 — 기간과 무관, 6시간 캐시 공유
    if not force and _BASE["data"] and now - _BASE["ts"] < _TTL:
        base = _BASE["data"]
        cached = True
    else:
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
        base = {"eps": eps, "fear_greed": fg, "vix": vix_now(), "macro": macro_defaults()}
        if eps or fg:
            _BASE["ts"], _BASE["data"] = now, base
        cached = False

    # ③ 자동 밸류에이션 파이프라인 — SEP·지수·FactSet (소스별 TTL + 디스크 폴백)
    fs, fs_asof, _ = _cached("factset", C.TTL_FACTSET, fetch_factset, _factset_valid, force)
    sep, sep_asof, _ = _cached("sep", C.TTL_SEP, fetch_sep, force=force)
    idx, idx_asof, _ = _cached("index", C.TTL_INDEX, fetch_index, force=force)
    ttm_eps = fs.get("ttm_eps") if fs else None
    fwd_eps = fs.get("fwd_eps") if fs else None
    index_val = (idx or {}).get("value") or (fs or {}).get("index")
    valuation = compute_valuation(index_val, ttm_eps, fwd_eps, sep)
    captions = {
        "factset": {"asof": fs_asof, "report_date": (fs or {}).get("report_date"),
                    "source": "FactSet Earnings Insight"},
        "sep": {"asof": sep_asof, "source": "FRED · FOMC SEP"},
        "index": {"asof": idx_asof, "date": (idx or {}).get("date"),
                  "source": "FRED / S&P Dow Jones Indices"},
    }

    data = {"pe": pe, "eps_hist": eps_hist, "eps_qoq": eps_qoq,
            "period": period, "periods": PERIODS,
            "index": idx or ({"value": (fs or {}).get("index"), "date": None,
                              "source": "FactSet"} if fs else None),
            "factset": fs, "sep": sep, "valuation": valuation,
            "config": {"eps_premium": C.EPS_PREMIUM, "per_bands": C.PER_BANDS,
                       "growth_2028_assumption": C.GROWTH_2028_ASSUMPTION,
                       "ten_year_avg_fwd_per": C.TEN_YEAR_AVG_FORWARD_PER},
            "captions": captions,
            "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "errors": errors, "cached": cached}
    data.update(base)
    return data


if __name__ == "__main__":
    import json
    print(json.dumps(overview(force=True), ensure_ascii=False, indent=2))
