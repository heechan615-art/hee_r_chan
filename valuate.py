"""
빠른 기업 가치평가 프로토타입 (v0.2)  국내+미국
================================================
기능
  1) EPS(TTM)/예상EPS, 현재PER/예상PER
       - 미국: yfinance
       - 국내: 네이버 금융 per_table 스크래핑 (EPS/추정EPS = FnGuide 컨센서스)
  2) 과거 PER 밴드(최저/평균/최고) + 이상치 연도 자동 제외(IQR)
  3) 실적 vs 멀티플 분해 (로그분해) + ASCII 시각화
  4) 목표주가 3개 (TTM / 예상EPS 기준)

주의: 데이터는 야후/네이버 기준 추정치. 예상EPS는 증권사 컨센서스.
      투자판단의 참고용이며 정답이 아님.

사용법:
  python valuate.py                # 기본 종목들
  python valuate.py NVDA 005930.KS AAPL 000660.KS
"""
import sys, os, re, math, html, warnings
warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup

from fear_greed import compute_from_hist, timeline_from_hist
import rates
import kr_data

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


# ----------------------------- 유틸 -----------------------------
def fmt(x, unit=""):
    if x is None or (isinstance(x, float) and (pd.isna(x) or math.isinf(x))):
        return "N/A"
    try:
        return f"{x:,.2f}{unit}"
    except Exception:
        return str(x)


def bar(pct, width=20):
    """0~100 비중을 ASCII 막대로."""
    n = int(round(pct / 100 * width))
    return "█" * n + "░" * (width - n)


def is_korean(ticker):
    t = ticker.upper()
    return t.endswith(".KS") or t.endswith(".KQ") or re.fullmatch(r"\d{6}", t) is not None


def kr_code(ticker):
    return re.sub(r"\.(KS|KQ)$", "", ticker.upper())


# ----------------------- 네이버 국내 EPS -----------------------
def naver_eps(ticker):
    """국내 종목 per_table에서 EPS/PER/추정EPS/추정PER 파싱."""
    code = kr_code(ticker)
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        r = requests.get(url, headers=UA, timeout=10)
        r.encoding = "utf-8"  # 네이버 금융이 UTF-8로 전환됨(과거 euc-kr). 한글 라벨 매칭에 필수.
        soup = BeautifulSoup(r.text, "lxml")
        t = soup.find("table", class_="per_table")
        if not t:
            return {}
        out = {}
        for tr in t.find_all("tr"):
            th = tr.find("th")
            if not th:
                continue
            label = th.get_text(" ", strip=True)
            ems = [e.get_text(strip=True).replace(",", "") for e in tr.find_all("em")]
            nums = []
            for e in ems:
                try:
                    nums.append(float(e))
                except ValueError:
                    pass
            if label.startswith("PER") and len(nums) >= 2:
                out["per"], out["eps_ttm"] = nums[0], nums[1]
            elif label.startswith("추정PER") and len(nums) >= 2:
                out["per_fwd"], out["eps_fwd"] = nums[0], nums[1]
            elif label.startswith("PBR") and len(nums) >= 2:
                out["pbr"], out["bps"] = nums[0], nums[1]
        # 현재가
        today = soup.find("p", class_="no_today")
        if today:
            m = re.search(r"[\d,]+", today.get_text())
            if m:
                out["price"] = float(m.group().replace(",", ""))
        return out
    except Exception as e:
        return {"_err": repr(e)[:100]}


# ------------------ 네이버 기업실적분석 (연간 PER/PBR) ------------------
def naver_annual(ticker):
    """네이버 종목 메인의 '기업실적분석' 표에서 최근 연간 실적 파싱.
    네이버 기준 = 연말 종가 ÷ 지배주주 EPS/BPS, 마지막 열은 컨센서스 예상(E).
    반환 예: {"years": ["2023","2024","2025","2026E"], "per": [...], "pbr": [...], ...}"""
    code = kr_code(ticker)
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        r = requests.get(url, headers=UA, timeout=10)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "lxml")
        table = None
        for t in soup.find_all("table"):
            cap = t.find("caption")
            if cap and "기업실적분석" in cap.get_text():
                table = t
                break
        if not table:
            return None
        head_rows = table.find("thead").find_all("tr")
        n_annual = 4  # '최근 연간 실적' 열 수 (colspan에서 읽되 기본 4)
        for th in head_rows[0].find_all("th"):
            if "연간" in th.get_text():
                n_annual = int(th.get("colspan", 4))
        periods = [th.get_text(" ", strip=True) for th in head_rows[1].find_all("th")][:n_annual]
        years = []
        for p in periods:
            m = re.match(r"(\d{4})", p)
            years.append((m.group(1) if m else p) + ("E" if "(E)" in p else ""))
        out = {"years": years}
        want = {"EPS": "eps", "PER": "per", "BPS": "bps", "PBR": "pbr"}
        for tr in table.find("tbody").find_all("tr"):
            th = tr.find("th")
            if not th:
                continue
            lbl = th.get_text(" ", strip=True)
            key = next((v for k, v in want.items() if lbl.startswith(k)), None)
            if not key:
                continue
            vals = []
            for td in tr.find_all("td")[:n_annual]:
                txt = td.get_text(strip=True).replace(",", "")
                try:
                    vals.append(float(txt))
                except ValueError:
                    vals.append(None)
            out[key] = vals
        return out if ("per" in out or "pbr" in out) else None
    except Exception:
        return None


# ----------------------- 공통 데이터 로드 -----------------------
def get_annual_eps(tk):
    try:
        df = tk.income_stmt
    except Exception:
        return pd.Series(dtype=float)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    for row in ("Diluted EPS", "Basic EPS"):
        if row in df.index:
            s = df.loc[row].dropna()
            if not s.empty:
                return s.sort_index()  # 오래된→최신
    return pd.Series(dtype=float)


def get_annual_bps(tk):
    """연간 BPS(주당순자산) 시계열 = 자본총계 / 주식수. PBR 밴드용."""
    try:
        bs = tk.balance_sheet
    except Exception:
        return pd.Series(dtype=float)
    if bs is None or bs.empty:
        return pd.Series(dtype=float)
    eq = sh = None
    for row in ("Stockholders Equity", "Common Stock Equity",
                "Total Equity Gross Minority Interest"):
        if row in bs.index:
            eq = bs.loc[row].dropna()
            break
    for row in ("Ordinary Shares Number", "Share Issued",
                "Common Stock Shares Outstanding"):
        if row in bs.index:
            sh = bs.loc[row].dropna()
            break
    if eq is None or eq.empty or sh is None or sh.empty:
        return pd.Series(dtype=float)
    out = {}
    for date, e in eq.items():
        s = sh.get(date)
        if s and s > 0:
            out[date] = float(e) / float(s)
    return pd.Series(out).sort_index()


def price_at(hist, date, window=20):
    d = pd.Timestamp(date)
    w = hist[(hist.index >= d - pd.Timedelta(days=window)) &
             (hist.index <= d + pd.Timedelta(days=window))]
    if not w.empty:
        return float(w.mean())  # ±window일 평균으로 특정일 노이즈 완화
    w = hist[hist.index <= d]
    return float(w.iloc[-1]) if not w.empty else None


# ----------------------- PER 밴드(이상치 제외) -----------------------
def per_band(eps_series, hist):
    pers = {}
    for date, e in eps_series.items():
        if e is None or pd.isna(e) or e <= 0:
            continue
        end = pd.Timestamp(date)
        w = hist[(hist.index >= end - pd.DateOffset(years=1)) & (hist.index <= end)]
        if w.empty:
            continue
        pers[end.year] = float(w.mean()) / float(e)
    if not pers:
        return None
    vals = pd.Series(pers)
    # IQR 이상치 제외
    q1, q3 = vals.quantile(0.25), vals.quantile(0.75)
    iqr = q3 - q1
    lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    clean = vals[(vals >= lo_f) & (vals <= hi_f)]
    outliers = vals[(vals < lo_f) | (vals > hi_f)]
    band = clean if len(clean) >= 2 else vals
    return {
        "all": pers,
        "outliers": list(outliers.index),
        "min": float(band.min()),
        "avg": float(band.mean()),
        "median": float(band.median()),
        "max": float(band.max()),
    }


# ----------------- 표준편차 밴드 (주간 배수 시계열) -----------------
def ratio_daily(val_series, hist, years=5, cur_val=None, fwd_map=None, forward=False):
    """최근 N년 '일별' 배수(PER/PBR) 시계열 (pd.Series).
    각 날의 배수 = 주가 ÷ EPS/BPS 근사(연간 값 사이를 시간 보간).
    - trailing(기본): 그 시점까지 발표된 TTM 근사로 나눔 (과거 멀티플).
    - forward=True: 그 시점 '1년 뒤' 예상 EPS/BPS로 나눔 (선행 멀티플).
      fwd_map(미래 예상 앵커 {날짜: 값})을 보간에 포함해 최근 구간까지 채움.
    - cur_val(현재 TTM)을 마지막 앵커로 추가. 음수 구간 제외."""
    if val_series is None or val_series.empty or hist.empty:
        return None
    vs = val_series.dropna()
    vs = vs[vs > 0]
    if vs.empty:
        return None
    vs.index = pd.to_datetime(vs.index)
    vs = vs.sort_index()
    end = hist.index[-1]
    if cur_val and cur_val > 0 and end > vs.index[-1]:
        vs = pd.concat([vs, pd.Series({end: float(cur_val)})])
    if fwd_map:  # 미래 예상 앵커 (선행 계산용)
        vs = pd.concat([vs, pd.Series({pd.Timestamp(k): float(v)
                                       for k, v in fwd_map.items() if v and v > 0})])
        vs = vs[~vs.index.duplicated(keep="last")].sort_index()
    start = max(end - pd.DateOffset(years=years), vs.index[0])
    h = hist[hist.index >= start].dropna()
    if len(h) < 120:  # 최소 ~6개월치는 있어야 의미 있음
        return None
    curve = vs.reindex(vs.index.union(h.index)).interpolate(method="time")
    if forward:
        # 각 날짜의 분모 = 1년 뒤 EPS/BPS → 커브 인덱스를 1년 당김
        curve = curve.copy()
        curve.index = curve.index - pd.DateOffset(years=1)
        curve = curve[~curve.index.duplicated(keep="last")].sort_index()
        denom = curve.reindex(curve.index.union(h.index)).interpolate(method="time")
        denom = denom.reindex(h.index)
    else:
        denom = curve.reindex(h.index).ffill()
    denom = denom[denom > 0]
    ratio = (h / denom).dropna()
    ratio = ratio[ratio > 0]
    return ratio if len(ratio) >= 120 else None


def sigma_from_ratio(ratio, trim=0.02):
    """일별 배수 시계열 → σ밴드 요약.
    이상치 처리: 음수는 이미 제외, 추가로 상/하위 trim(기본 2%) 극단값을
    잘라낸 뒤 평균·표준편차 계산 (표시용 시계열은 전체 유지, 주간 다운샘플)."""
    if ratio is None or len(ratio) < 120:
        return None
    lo_q, hi_q = ratio.quantile(trim), ratio.quantile(1 - trim)
    core = ratio[(ratio >= lo_q) & (ratio <= hi_q)]
    mean_, std_ = float(core.mean()), float(core.std())
    if not (std_ > 0):
        return None
    weekly = ratio.resample("W-FRI").last().dropna()
    return {
        "series": [{"d": t.strftime("%Y-%m-%d"), "v": round(float(v), 4)}
                   for t, v in weekly.items()],
        "mean": mean_, "std": std_, "cur": float(ratio.iloc[-1]),
        "years": round((ratio.index[-1] - ratio.index[0]).days / 365.25, 1),
        "trim_pct": trim * 100,
    }


def sigma_series(val_series, hist, years=5, cur_val=None):
    """(호환용) 배수 σ밴드 요약 — ratio_daily + sigma_from_ratio."""
    return sigma_from_ratio(ratio_daily(val_series, hist, years, cur_val))


# ------------------ 네이버 연간 표 → 밴드 변환 ------------------
def band_from_naver(nv, key):
    """네이버 기업실적분석 연간 값(per/pbr)으로 밴드 dict 생성 (per_band와 같은 형태).
    확정 실적만 통계에 사용, 예상(E)은 est로 분리해 차트에만 점선 표시.
    3년뿐이라 IQR 이상치 제거는 불가 — 이익 급감/급증 연도가 그대로 밴드에 반영됨."""
    if not nv or not nv.get(key):
        return None
    actual, est = {}, {}
    for y, v in zip(nv["years"], nv[key]):
        if v is None:
            continue
        (est if y.endswith("E") else actual)[int(y[:4])] = float(v)
    if len(actual) < 2:
        return None
    s = pd.Series(actual)
    return {
        "all": actual, "est": est, "outliers": [], "src": "naver",
        "min": float(s.min()), "avg": float(s.mean()),
        "median": float(s.median()), "max": float(s.max()),
    }


# ----------------------- 실적 vs 멀티플 분해 -----------------------
def decompose(eps_series, hist, price_now):
    """최근 약 1년 주가변화를 실적 vs 멀티플로 로그분해.
    - 가격: 1년 전 종가(p0) → 현재가(p1). 최근 상승/하락을 반영.
    - EPS: 최신 연간실적(e1) vs 1년 전 시점의 연간실적(e0).
      소스 일관성 위해 둘 다 yfinance 연간(분기 EPS는 4~5개뿐이라 정밀 TTM 불가 → 연간 근사).
    - 각 시점 PER = 그 시점 주가 ÷ 그때까지 발표된 최신 연간 EPS."""
    eps = eps_series[eps_series > 0]
    if len(eps) < 2 or hist.empty:
        return None
    e0, e1 = float(eps.iloc[-2]), float(eps.iloc[-1])
    end = hist.index[-1]
    p1 = float(price_now) if (price_now and price_now > 0) else float(hist.iloc[-1])
    p0 = price_at(hist, end - pd.DateOffset(years=1))
    if not (p0 and p0 > 0 and p1 > 0):
        return None
    per0, per1 = p0 / e0, p1 / e1
    L_earn = math.log(e1 / e0)
    L_mult = math.log(per1 / per0)
    denom = abs(L_earn) + abs(L_mult) or 1e-9
    return {
        "eps_y0": int(pd.Timestamp(eps.index[-2]).year),
        "eps_y1": int(pd.Timestamp(eps.index[-1]).year),
        "price_chg": p1 / p0 - 1,
        "eps_chg": e1 / e0 - 1,
        "per_chg": per1 / per0 - 1,
        "w_earn": abs(L_earn) / denom * 100,
        "w_mult": abs(L_mult) / denom * 100,
        "per0": per0, "per1": per1,
    }


# ----------------------------- 뉴스 -----------------------------
def _yf_news(tk, n):
    """yfinance 영문 뉴스(폴백)."""
    out = []
    try:
        for item in (tk.news or [])[:n]:
            c = item.get("content", item) if isinstance(item, dict) else {}
            title = c.get("title") or item.get("title")
            cu = c.get("canonicalUrl") or c.get("clickThroughUrl")
            link = cu.get("url") if isinstance(cu, dict) else item.get("link", "")
            prov = c.get("provider")
            pub = prov.get("displayName") if isinstance(prov, dict) else item.get("publisher", "")
            if title:
                out.append({"title": title, "link": link or "", "publisher": pub or ""})
    except Exception:
        pass
    return out


def get_news(tk, ticker, info, n=6):
    """네이버 모바일 뉴스 API로 한국어 기사 수집(국내·해외 모두). 실패 시 yfinance 영문 폴백."""
    hdr = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
           "Referer": "https://m.stock.naver.com/"}
    if is_korean(ticker):
        codes = [kr_code(ticker)]
    else:
        ex = (info.get("exchange") or "").upper()
        suf = {"NMS": ".O", "NGM": ".O", "NCM": ".O", "NYQ": ".N",
               "PCX": ".A", "ASE": ".A", "BATS": ".O"}.get(ex, ".O")
        base = ticker.upper()
        codes = list(dict.fromkeys([base + suf, base + ".O", base + ".N"]))  # 접미사 후보(중복 제거)
    for code in codes:
        try:
            r = requests.get(
                f"https://m.stock.naver.com/api/news/stock/{code}?pageSize={n}&page=1",
                headers=hdr, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            items = []
            for grp in (data if isinstance(data, list) else []):
                items += grp.get("items", [])
            out = []
            for it in items[:n]:
                title = re.sub(r"<[^>]+>", "", html.unescape(it.get("title", ""))).strip()
                oid, aid = it.get("officeId", ""), it.get("articleId", "")
                link = f"https://n.news.naver.com/mnews/article/{oid}/{aid}" if oid and aid else ""
                if title:
                    out.append({"title": title, "link": link, "publisher": it.get("officeName", "")})
            if out:
                return out
        except Exception:
            continue
    return _yf_news(tk, n)


# ------------------- 이익성장률 추정 (직접 전망 목표가용) -------------------
def growth_block(tk, nv_annual, eps_ttm, eps_fwd, eps_series):
    """성장률 후보(연율)와 추천값. 후보:
      - fy1:  예상EPS ÷ TTM − 1 (컨센서스 1년 점프)
      - hist: 과거 연간 EPS CAGR (국내는 네이버 확정실적, 미국은 yfinance)
      - anl:  애널리스트 내년 성장률 (미국, yfinance growth_estimates '+1y')
      - lt:   애널리스트 장기 성장률 (LTG, 있을 때만)
    추천 = 후보 중앙값을 [-20%, +40%]로 클램프 — 시클리컬 극단값(+277% 등) 방어."""
    cands = {}
    if eps_ttm and eps_ttm > 0 and eps_fwd and eps_fwd > 0:
        cands["fy1"] = eps_fwd / eps_ttm - 1
    vals = None
    if nv_annual and nv_annual.get("eps"):
        vals = [v for y, v in zip(nv_annual["years"], nv_annual["eps"])
                if not y.endswith("E") and v and v > 0]
    elif eps_series is not None and not eps_series.empty:
        vals = [float(v) for v in eps_series.values if v and v > 0]
    if vals and len(vals) >= 2 and vals[0] > 0 and vals[-1] > 0:
        cands["hist"] = (vals[-1] / vals[0]) ** (1 / (len(vals) - 1)) - 1
    try:  # 미국: 애널리스트 성장률 (국내 티커는 보통 데이터 없음 → 조용히 생략)
        ge = tk.growth_estimates
        col = "stockTrend" if "stockTrend" in ge.columns else ge.columns[0]
        for row, key in (("+1y", "anl"), ("LTG", "lt")):
            if row in ge.index and pd.notna(ge.loc[row, col]):
                cands[key] = float(ge.loc[row, col])
    except Exception:
        pass
    if not cands:
        return None
    # 추천(시작 성장률): 애널리스트 내년 추정 > 장기(LTG) > 중앙값 순으로 채택.
    # 어차피 감쇠(fade) 모델의 '첫해' 값이라 이후 해마다 둔화됨 — 상한 30%.
    vs = sorted(cands.values())
    n = len(vs)
    med = vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2
    base = cands.get("anl", cands.get("lt", med))
    return {"cands": {k: round(v, 4) for k, v in cands.items()},
            "suggest": round(min(max(base, -0.20), 0.30), 4)}


# ------------------- 재무 흐름 (가치평가용 재무제표 요약) -------------------
def _us_financials(tk):
    """미국: yfinance 손익/재무상태/현금흐름에서 연도별 시계열(백만달러).
    확정 연간만(무료 소스는 재무 예상 없음). 실패 항목은 None."""
    def row(df, names):
        if df is None or df.empty:
            return None
        for nm in names:
            if nm in df.index:
                return df.loc[nm]
        return None
    try:
        inc, bs, cf = tk.income_stmt, tk.balance_sheet, tk.cashflow
    except Exception:
        return None
    rev = row(inc, ["Total Revenue", "Operating Revenue"])
    if rev is None or rev.empty:
        return None
    cols = sorted(rev.dropna().index)          # 오래된→최신 (연말 Timestamp)
    years = [str(pd.Timestamp(c).year) for c in cols]

    def series(r):
        if r is None:
            return [None] * len(cols)
        return [None if (c not in r.index or pd.isna(r[c])) else float(r[c]) / 1e6
                for c in cols]

    opinc = row(inc, ["Operating Income", "Operating Income Or Loss"])
    netinc = row(inc, ["Net Income", "Net Income Common Stockholders"])
    debt = row(bs, ["Total Debt", "Total Liabilities Net Minority Interest"])
    equity = row(bs, ["Stockholders Equity", "Common Stock Equity"])
    ocf = row(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
    fcf = row(cf, ["Free Cash Flow"])
    rev_v, op_v, ni_v = series(rev), series(opinc), series(netinc)
    debt_v, eq_v = series(debt), series(equity)
    # 파생 지표: 부채비율(부채/자본×100), 영업이익률(영업이익/매출×100)
    dr = [None if (d is None or e in (None, 0)) else round(d / e * 100, 1)
          for d, e in zip(debt_v, eq_v)]
    om = [None if (o is None or r in (None, 0)) else round(o / r * 100, 1)
          for o, r in zip(op_v, rev_v)]
    roe = [None if (n is None or e in (None, 0)) else round(n / e * 100, 1)
           for n, e in zip(ni_v, eq_v)]   # ROE = 순이익/자본
    ocf_v, fcf_v = series(ocf), series(fcf)
    # FY+1 예상 컨센서스 병합 (stockanalysis, 무료는 1년) — 확정 마지막보다 뒤 연도만
    try:
        sym = getattr(tk, "ticker", "") or ""
        fc = _us_forecast(sym) if sym else None
        if fc and fc.get("year") and years and int(fc["year"]) > int(years[-1]):
            years.append(fc["year"] + "E")
            rev_v.append(fc.get("revenue")); op_v.append(fc.get("opinc"))
            ni_v.append(fc.get("netinc")); ocf_v.append(None); fcf_v.append(fc.get("fcf"))
            dr.append(None); roe.append(None)
            om.append(round(fc["opinc"] / fc["revenue"] * 100, 1)
                      if (fc.get("opinc") and fc.get("revenue")) else None)
    except Exception:
        pass
    return {"years": years, "revenue": rev_v, "opinc": op_v, "netinc": ni_v, "roe": roe,
            "ocf": ocf_v, "fcf": fcf_v, "debtratio": dr, "opmargin": om,
            "unit": "M$", "cur": "USD"}


_US_FC_CACHE = {}   # {symbol: (ts, dict)}


def _us_forecast(symbol):
    """미국 FY+1 재무 컨센서스 — stockanalysis.com forecast 페이지 (무료는 1년만,
    2년 뒤부터는 [PRO] 유료 잠금). curl_cffi로 브라우저 지문 위장. 실패 시 None.
    반환: {"year": "2027", "revenue","opinc","netinc","fcf"(백만달러)}."""
    import time as _t
    now = _t.time()
    hit = _US_FC_CACHE.get(symbol)
    if hit and now - hit[0] < 3600:
        return hit[1]
    out = None
    try:
        from curl_cffi import requests as creq
        r = creq.get(f"https://stockanalysis.com/stocks/{symbol.lower()}/forecast/",
                     impersonate="chrome", timeout=15)
        if r.status_code == 200:
            t = r.text

            def arr(field):
                m = re.search(rf'\b{field}:\[([^\]]+)\]', t)
                return m.group(1).split(",") if m else None

            yrs = arr("fiscalYear")
            rev = arr("revenue")
            if yrs and rev:
                # 값이 숫자인 마지막 인덱스 = FY+1 예상 (그 뒤는 "[PRO]")
                def num(a, i):
                    try:
                        return float(a[i])
                    except (ValueError, TypeError, IndexError):
                        return None
                li = -1
                for i in range(len(rev)):
                    if num(rev, i) is not None:
                        li = i
                if li >= 0:
                    op, ni, fcf = arr("operatingIncome"), arr("netIncome"), arr("freeCashFlow")
                    yr = re.sub(r'"', "", yrs[li]).strip()
                    out = {"year": yr,
                           "revenue": num(rev, li) / 1e6 if num(rev, li) else None,
                           "opinc": num(op, li) / 1e6 if op and num(op, li) else None,
                           "netinc": num(ni, li) / 1e6 if ni and num(ni, li) else None,
                           "fcf": num(fcf, li) / 1e6 if fcf and num(fcf, li) else None}
    except Exception:
        out = None
    _US_FC_CACHE[symbol] = (now, out)
    return out


def _us_quarterly(tk):
    """미국 분기 매출·영업익·순익 (QoQ용, 백만달러). 최근 순."""
    try:
        q = tk.quarterly_income_stmt
        if q is None or q.empty:
            return None
        cols = sorted(q.dropna(how="all").columns)[-6:]
        def s(names):
            for nm in names:
                if nm in q.index:
                    return [None if pd.isna(q.loc[nm, c]) else float(q.loc[nm, c])/1e6 for c in cols]
            return [None]*len(cols)
        return {"quarters": [f"{str(pd.Timestamp(c).year)[2:]}Q{(pd.Timestamp(c).month-1)//3+1}" for c in cols],
                "revenue": s(["Total Revenue"]), "opinc": s(["Operating Income"]),
                "netinc": s(["Net Income", "Net Income Common Stockholders"])}
    except Exception:
        return None


def build_financials(tk, nv_annual, kr_code=None):
    """국내(WISEfn)·미국(yfinance) 공통 재무 흐름 구조 + 분기(QoQ) + ROE.
    반환: {years, revenue, opinc, netinc, roe, ocf, fcf, debtratio, opmargin,
           quarterly:{quarters,revenue,opinc,netinc}, unit, cur}"""
    keys = ("revenue", "opinc", "netinc", "roe", "ocf", "fcf", "debtratio", "opmargin")
    if nv_annual and nv_annual.get("revenue"):   # WISEfn(국내) — 재무 행 보유(억원)
        out = {"years": nv_annual["years"], "unit": "억원", "cur": "KRW"}
        for k in keys:
            out[k] = nv_annual.get(k) or [None] * len(nv_annual["years"])
        if kr_code:   # 분기(QoQ)
            q = kr_data.wisefn_annual(kr_code, freq="Q")
            if q and q.get("quarters"):
                out["quarterly"] = {"quarters": q["quarters"],
                                    "revenue": q.get("revenue"), "opinc": q.get("opinc"),
                                    "netinc": q.get("netinc")}
        return out
    us = _us_financials(tk)
    if us:
        us["quarterly"] = _us_quarterly(tk)
    return us


# ------------------- 재무 안정성 AI 판단 -------------------
_FIN_CMT_CACHE = {}   # {name: (ts, comment)}


def fin_ai_comment(name, fin):
    """재무 지표 흐름을 Gemini로 요약 → 안정/불안정 판단 + 근거 코멘트.
    반환: {"verdict": "안정"|"보통"|"불안정", "text": "..."} / 실패 시 None. 1시간 캐시."""
    if not fin or not fin.get("years"):
        return None
    import time as _t
    now = _t.time()
    hit = _FIN_CMT_CACHE.get(name)
    if hit and now - hit[0] < 3600:
        return hit[1]
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    yrs = fin["years"]

    def line(label, arr, suf=""):
        if not arr:
            return None
        pairs = [f"{y} {v:.0f}{suf}" for y, v in zip(yrs, arr) if v is not None]
        return f"{label}: " + ", ".join(pairs) if pairs else None

    unit = fin.get("unit", "")
    rows = [line("매출("+unit+")", fin.get("revenue")),
            line("영업이익률(%)", fin.get("opmargin"), "%"),
            line("순이익("+unit+")", fin.get("netinc")),
            line("ROE(%)", fin.get("roe"), "%"),
            line("부채비율(%)", fin.get("debtratio"), "%"),
            line("잉여현금흐름("+unit+")", fin.get("fcf"))]
    body = "\n".join(r for r in rows if r)
    prompt = (
        f"종목: {name}\n최근 재무 흐름(E=예상):\n{body}\n\n"
        "위 재무제표를 근거로 이 기업의 재무 안정성을 평가해줘.\n"
        "규칙:\n"
        "- 첫 줄에 한 단어로 판정: '안정' 또는 '보통' 또는 '불안정'\n"
        "- 그 다음 줄부터 한국어 2~3문장으로 근거를 구체 수치와 함께. "
        "매출 성장 추세, 수익성(영업이익률·ROE), 부채비율, 현금흐름(FCF) 중 "
        "핵심 근거만 짚어줘. 서론·군더더기 없이 결론부터.\n"
        "- 안정이면 무엇 때문에 안정인지, 불안정이면 무엇 때문에 불안정인지 명확히.")
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 400, "temperature": 0.3,
                                       "thinkingConfig": {"thinkingBudget": 0}}},
            timeout=25)
        if r.status_code != 200:
            return None
        text = "".join(p.get("text", "") for p in
                       (r.json()["candidates"][0]["content"].get("parts") or [])).strip()
        if not text:
            return None
        first = text.split("\n", 1)[0]
        verdict = "안정" if "안정" in first and "불안정" not in first else \
                  ("불안정" if "불안정" in first else "보통")
        rest = text.split("\n", 1)[1].strip() if "\n" in text else text
        out = {"verdict": verdict, "text": rest}
        _FIN_CMT_CACHE[name] = (now, out)
        return out
    except Exception:
        return None


# ------------------- 양국 10년물 금리 (헤더 표시용) -------------------
def _both_rates():
    """미국(FRED)·한국(ECOS) 10년물 최신 금리를 함께 반환 (캐시라 추가 조회 거의 없음).
    실패한 쪽은 None."""
    out = {"us": None, "kr": None}
    try:
        s = rates.fred_series("DGS10")
        if s is not None and not s.empty:
            out["us"] = {"rate": float(s.iloc[-1]), "date": str(s.index[-1].date())}
    except Exception:
        pass
    try:
        k = kr_data.ecos_rate10y()
        if k is not None and not k.empty:
            out["kr"] = {"rate": float(k.iloc[-1]), "date": str(k.index[-1].date())}
    except Exception:
        pass
    return out


# ------------------- 공포탐욕지수 (이미 받은 데이터 재사용) -------------------
def _fear_greed(hist_df, info, ticker, eps_series, ttm_eps, per_daily=None, news_titles=None):
    """분석 중 이미 확보한 주가/EPS를 fear_greed 지표에 주입 — 추가 조회 최소화.
    (뉴스 센티먼트만 Finnhub 1회 호출, 15분 캐시·실패 시 자동 제외)
    타임라인(주간 ~2년)도 함께 계산해 결과에 포함."""
    if not len(hist_df):
        return None
    fg_info = dict(info) if info else {}
    fg_info["_symbol"] = ticker            # 국내 6자리는 score_news에서 자동 스킵
    fg_info["_eps_series"] = eps_series    # PER 밴드 지표용 연간 EPS
    fg_info["_eps_ttm"] = ttm_eps
    market = "KR" if is_korean(ticker) else "US"   # VIX는 미국만
    fg_info["_market"] = market
    fg_info["_news_headlines"] = [t for t in (news_titles or []) if t]  # 국내 뉴스 센티먼트용
    try:
        r = compute_from_hist(hist_df.iloc[-1300:], fg_info)  # 최근 ~5년
        if r:
            try:
                r["timeline"] = timeline_from_hist(hist_df.iloc[-1300:], per_daily, market=market)
            except Exception:
                r["timeline"] = None
        return r
    except Exception:
        return None


# ----------------------------- 분석 (데이터 반환) -----------------------------
def analyze_data(ticker):
    """모든 계산을 수행하고 구조화된 dict를 반환. 출력(CLI/웹)과 분리."""
    ticker = ticker.strip()
    # 통합 리졸버: 한글 회사명("삼성전자")·6자리 코드 → 야후 티커(.KS/.KQ 자동),
    # 영문 티커는 그대로. 못 찾으면 안내 메시지.
    yf_ticker, kr_code6, kr_name = kr_data.resolve_query(ticker)
    if yf_ticker is None:
        raise ValueError(f"'{ticker}' 종목을 찾을 수 없습니다. "
                         "이름 철자를 확인하세요 (상장폐지/거래정지 종목일 수도 있습니다).")
    if kr_code6:
        ticker = kr_code6  # 이후 네이버 조회 등은 6자리 코드 기준
    tk = yf.Ticker(yf_ticker)
    try:
        info = tk.info
    except Exception:
        info = {}
    # 국내는 네이버 자동완성의 한글 종목명 우선 (yfinance는 영문 축약명)
    name = kr_name or info.get("shortName") or info.get("longName") or ticker
    cur = info.get("currency", "")

    try:
        # 밴드용으로 최대한 긴 주가 이력(무료 소스라 EPS/BPS는 4~5년이 한계).
        # OHLCV 전체를 받아두고 Close는 밴드/σ에, 전체는 공포탐욕지수에 재사용.
        hist_df = tk.history(period="11y", interval="1d")
        hist_df.index = hist_df.index.tz_localize(None)
        hist = hist_df["Close"]
    except Exception:
        hist_df = pd.DataFrame()
        hist = pd.Series(dtype=float)

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    ttm_eps = info.get("trailingEps")
    fwd_eps = info.get("forwardEps")
    cur_per = info.get("trailingPE")
    fwd_per = info.get("forwardPE")
    cur_pbr = info.get("priceToBook")
    cur_bps = info.get("bookValue")

    # 국내: 네이버로 EPS/PER/PBR 보강 + 연간 실적 표(연말 종가 기준, 예상 포함)
    src = "yfinance"
    nv_annual = None
    if is_korean(ticker):
        # WISEfn(확정 5년+컨센서스 3년) 우선, 실패 시 네이버 기업실적분석(3+1년) 폴백
        nv_annual = kr_data.wisefn_annual(ticker) or naver_annual(ticker)
        nv = naver_eps(ticker)
        if nv and "_err" not in nv:
            ttm_eps = nv.get("eps_ttm", ttm_eps)
            fwd_eps = nv.get("eps_fwd", fwd_eps)
            cur_per = nv.get("per", cur_per)
            fwd_per = nv.get("per_fwd", fwd_per)
            cur_pbr = nv.get("pbr", cur_pbr)
            cur_bps = nv.get("bps", cur_bps)
            price = nv.get("price", price)
            cur = "KRW"
            src = "네이버(EPS/PBR)+yfinance(밴드)"
    if price is None and not hist.empty:
        price = float(hist.iloc[-1])

    eps_series = get_annual_eps(tk)
    bps_series = get_annual_bps(tk)
    # 국내: 밴드를 네이버 연간 표(연말 종가·지배주주) 기준으로 — 그래프·통계·목표주가 일관성.
    # 미국(네이버 표 없음): 기존 방식(연평균 주가 ÷ yfinance EPS/BPS).
    band = band_from_naver(nv_annual, "per") or (per_band(eps_series, hist) if not hist.empty else None)
    pbr_band = band_from_naver(nv_annual, "pbr") or (per_band(bps_series, hist) if not hist.empty else None)

    # 표준편차 밴드 (일별 PER/PBR 시계열, 최대 5년) — 과거(TTM) + 선행(forward) 둘 다
    # 선행 앵커: 국내는 WISEfn 예상 연도(2026E~2028E), 미국은 예상 EPS/BPS(FY+1)
    fwd_eps_map, fwd_bps_map = {}, {}
    if nv_annual and nv_annual.get("years"):
        for i, y in enumerate(nv_annual["years"]):
            if y.endswith("E"):
                yy = pd.Timestamp(int(y[:4]), 12, 31)
                if nv_annual.get("eps") and nv_annual["eps"][i]:
                    fwd_eps_map[yy] = nv_annual["eps"][i]
                if nv_annual.get("bps") and nv_annual["bps"][i]:
                    fwd_bps_map[yy] = nv_annual["bps"][i]
    if not fwd_eps_map and fwd_eps and not hist.empty:
        fwd_eps_map[hist.index[-1] + pd.DateOffset(years=1)] = fwd_eps

    per_daily = ratio_daily(eps_series, hist, cur_val=ttm_eps) if not hist.empty else None
    sigma = sigma_from_ratio(per_daily)
    pbr_daily = ratio_daily(bps_series, hist, cur_val=cur_bps) if not hist.empty else None
    pbr_sigma = sigma_from_ratio(pbr_daily)
    sigma_fwd = sigma_from_ratio(ratio_daily(eps_series, hist, cur_val=ttm_eps,
                                fwd_map=fwd_eps_map, forward=True)) if not hist.empty else None
    pbr_sigma_fwd = sigma_from_ratio(ratio_daily(bps_series, hist, cur_val=cur_bps,
                                fwd_map=fwd_bps_map, forward=True)) if not hist.empty else None

    # 목표주가 모델용: 10년물 금리 + 금리↔PER/PBR 회귀 (실패해도 앱은 계속)
    # 국내 → 한국은행 ECOS 국고채 10년 / 미국 → FRED DGS10.
    # ECOS 키 없음·오류 시 rate_info=None → 프론트에서 할인/보정 기능만 비활성화.
    rate_info = pbr_reg = None
    try:
        if is_korean(ticker):
            ks = kr_data.ecos_rate10y()
            if ks is not None:
                rate_info = rates.rate_block(per_daily, series=ks, label="한국 국고채 10년")
                if rate_info and pbr_daily is not None:
                    pb = rates.rate_block(pbr_daily, series=ks, label="한국 국고채 10년")
                    pbr_reg = pb.get("reg") if pb else None
        else:
            rate_info = rates.rate_block(per_daily)
            if rate_info and pbr_daily is not None:
                pb = rates.rate_block(pbr_daily)  # FRED는 캐시라 추가 호출 없음
                pbr_reg = pb.get("reg") if pb else None
    except Exception:
        pass

    # 시클리컬 판별: 연간 EPS YoY 변동이 크면(±50%↑ 또는 적자 연도) 시클리컬로 간주.
    # → PER 밴드 참고가는 왜곡되기 쉬우니 PBR 쪽을 우선 보라고 안내하기 위함.
    if nv_annual and nv_annual.get("eps"):
        eps_hist = [v for y, v in zip(nv_annual["years"], nv_annual["eps"])
                    if not y.endswith("E") and v is not None]
    else:
        eps_hist = [float(v) for v in eps_series.dropna().values]
    cyclical = cyc_max = None
    if len(eps_hist) >= 2:
        yoys = [abs(b / a - 1) for a, b in zip(eps_hist, eps_hist[1:]) if a and a > 0]
        cyc_max = max(yoys) if yoys else None
        cyclical = any(v <= 0 for v in eps_hist) or (cyc_max is not None and cyc_max >= 0.5)

    # 최근 52주 고가/저가 (현재가 대비 낙폭/상승폭 참고용)
    hi52 = lo52 = None
    if not hist.empty:
        recent = hist[hist.index >= hist.index[-1] - pd.DateOffset(years=1)]
        if not recent.empty:
            hi52, lo52 = float(recent.max()), float(recent.min())

    targets = []
    if band:
        for eps, tag in ((ttm_eps, "TTM"), (fwd_eps, "예상EPS")):
            if eps and eps > 0:
                targets.append({
                    "tag": tag, "eps": eps,
                    "bear": eps * band["min"],
                    "neutral": eps * band["median"],
                    "bull": eps * band["max"],
                    "upside_pct": (eps * band["median"] / price - 1) * 100 if price else None,
                })

    # PBR 목표주가: BPS(TTM) + 예상BPS 근사 (예상BPS 컨센서스는 무료 소스에 없음)
    # 예상BPS ≈ BPS + 예상EPS × (1-배당성향) — 이익 중 유보분만 자본에 가산.
    # 한계: 자사주 매입(AAPL 등)은 배당성향에 안 잡혀 과대추정될 수 있음 → 주석으로 표기.
    pbr_targets = []
    if pbr_band and cur_bps and cur_bps > 0:
        cands = [(cur_bps, "TTM", None)]
        if fwd_eps and fwd_eps > 0:
            payout = info.get("payoutRatio") or 0
            payout = min(max(float(payout), 0.0), 1.0)  # 0~1로 클램프
            fwd_bps = cur_bps + fwd_eps * (1 - payout)
            cands.append((fwd_bps, "예상BPS",
                          f"BPS + 예상EPS×(1-배당성향 {payout*100:.0f}%) 근사 · 자사주 매입 미반영"))
        for v, tag, note in cands:
            pbr_targets.append({
                "tag": tag, "eps": v, "note": note,
                "bear": v * pbr_band["min"],
                "neutral": v * pbr_band["median"],
                "bull": v * pbr_band["max"],
                "upside_pct": (v * pbr_band["median"] / price - 1) * 100 if price else None,
            })

    # 선행 BPS/PBR: 국내는 컨센서스 첫 E연도(FY+1), 미국은 예상BPS 근사
    fwd_bps = None
    if nv_annual and nv_annual.get("bps"):
        for y, v in zip(nv_annual["years"], nv_annual["bps"]):
            if y.endswith("E") and v:
                fwd_bps = float(v)
                break  # 첫 예상 연도(FY+1)만 — 2027E/2028E는 칩으로 별도 제공
    elif len(pbr_targets) > 1:
        fwd_bps = pbr_targets[1]["eps"]
    fwd_pbr = price / fwd_bps if (price and fwd_bps and fwd_bps > 0) else None

    news = get_news(tk, ticker, info)   # 뉴스 센티먼트(국내)에도 재사용 → 미리 계산
    fin_data = build_financials(tk, nv_annual, kr_code=(ticker if is_korean(ticker) else None))
    fin_comment = fin_ai_comment(name, fin_data)   # 재무 안정성 AI 판단

    return {
        "ticker": ticker, "name": name, "currency": cur, "source": src,
        "price": price, "eps_ttm": ttm_eps, "per_ttm": cur_per,
        "eps_fwd": fwd_eps, "per_fwd": fwd_per,
        "pbr_ttm": cur_pbr, "bps": cur_bps,
        "bps_fwd": fwd_bps, "pbr_fwd": fwd_pbr,
        "band": band, "pbr_band": pbr_band, "targets": targets,
        "pbr_targets": pbr_targets, "sigma": sigma, "pbr_sigma": pbr_sigma,
        "sigma_fwd": sigma_fwd, "pbr_sigma_fwd": pbr_sigma_fwd,
        "naver_annual": nv_annual,
        "cyclical": cyclical, "cyc_max": cyc_max,
        "eps_hist": [round(float(v), 4) for v in eps_hist] if eps_hist else [],
        "financials": fin_data, "fin_comment": fin_comment,
        "fear_greed": _fear_greed(hist_df, info, ticker, eps_series, ttm_eps, per_daily,
                                  news_titles=[n.get("title") for n in (news or [])]),
        "target_model": {"rate": rate_info, "pbr_reg": pbr_reg,
                         "growth": growth_block(tk, nv_annual, ttm_eps, fwd_eps, eps_series),
                         "rates_both": _both_rates()},
        "hi52": hi52, "lo52": lo52,
        "decompose": decompose(eps_series, hist, price),
        "news": news,
        "error": None,
    }


# ----------------------------- CLI 출력 -----------------------------
def print_report(d):
    cur = d["currency"]
    print("=" * 62)
    print(f"  {d['name']}  ({d['ticker']})   [{d['source']}]")
    print("=" * 62)
    print("[기본]")
    print(f"  현재가       : {fmt(d['price'])} {cur}")
    print(f"  EPS(TTM)     : {fmt(d['eps_ttm'])}      현재 PER : {fmt(d['per_ttm'])}")
    print(f"  예상EPS(Fwd) : {fmt(d['eps_fwd'])}      예상 PER : {fmt(d['per_fwd'])}")
    print(f"  BPS          : {fmt(d.get('bps'))}      현재 PBR : {fmt(d.get('pbr_ttm'))}")

    band = d["band"]
    yrs = len(band["all"]) if band else 0
    print(f"\n[과거 PER 밴드] (확보 {yrs}년)")
    if band:
        print("  연도별: " + ", ".join(f"{y}:{v:.1f}" for y, v in sorted(band["all"].items())))
        if band["outliers"]:
            print(f"  ⚠️ 이상치 제외: {band['outliers']} (이익 급감/급증 해)")
        print(f"  → 최저 {band['min']:.1f} / 평균 {band['avg']:.1f} / "
              f"중앙값 {band['median']:.1f} / 최고 {band['max']:.1f}")

    pb = d.get("pbr_band")
    print(f"\n[과거 PBR 밴드] (확보 {len(pb['all']) if pb else 0}년)")
    if pb:
        print("  연도별: " + ", ".join(f"{y}:{v:.2f}" for y, v in sorted(pb["all"].items())))
        print(f"  → 최저 {pb['min']:.2f} / 평균 {pb['avg']:.2f} / "
              f"중앙값 {pb['median']:.2f} / 최고 {pb['max']:.2f}")
    else:
        print("  N/A (BPS 히스토리 부족)")

    if band:
        print("\n[목표주가]")
        for t in d["targets"]:
            print(f"  [{t['tag']}] EPS {fmt(t['eps'])} 기준")
            print(f"     비관 {fmt(t['bear'])} / 중립 {fmt(t['neutral'])} "
                  f"/ 낙관 {fmt(t['bull'])} {cur}")
            if t["upside_pct"] is not None:
                print(f"     → 중립(중앙값) 대비 현재가: {t['upside_pct']:+.1f}%")
    else:
        print("  N/A (EPS 히스토리 부족)")

    if d.get("hi52") and d.get("lo52") and d.get("price"):
        p = d["price"]
        print("\n[최근 52주 가격]")
        print(f"  최고 {fmt(d['hi52'])} (현재가 {(p/d['hi52']-1)*100:+.1f}%) / "
              f"최저 {fmt(d['lo52'])} (현재가 {(p/d['lo52']-1)*100:+.1f}%)")

    dc = d["decompose"]
    print("\n[주가변화 요인분해: 실적 vs 멀티플] (최근 1년)")
    if dc:
        print(f"  기간: 1년 전 → 현재 (주가 {dc['price_chg']*100:+.1f}%)")
        print(f"  실적(EPS {dc['eps_y0']}→{dc['eps_y1']} 연간) {dc['eps_chg']*100:+6.1f}%  "
              f"{bar(dc['w_earn'])} 비중 {dc['w_earn']:4.0f}%")
        print(f"  멀티플(PER)              {dc['per_chg']*100:+6.1f}%  "
              f"{bar(dc['w_mult'])} 비중 {dc['w_mult']:4.0f}%")
        drv = "실적" if dc["w_earn"] >= dc["w_mult"] else "멀티플"
        print(f"  → 최근 1년 변화는 '{drv}' 주도"
              + ("" if drv == "실적" else " (내/외부요인 구분은 뉴스분석 필요)"))
    else:
        print("  N/A (연간 EPS 2개 이상 필요)")

    if d.get("news"):
        print("\n[최근 뉴스]")
        for n in d["news"]:
            print(f"  - {n['title']}")
    print()


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["NVDA", "005930.KS", "AAPL", "000660.KS"]
    for t in tickers:
        try:
            print_report(analyze_data(t))
        except Exception as e:
            print(f"[{t}] 분석 실패: {repr(e)[:120]}\n")
