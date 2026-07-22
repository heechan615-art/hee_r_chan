"""
개별 종목 공포탐욕지수(Fear & Greed Index) 계산 모듈
=====================================================
5개 지표를 각각 0~100점으로 환산한 뒤 평균 → 종합 지수.
  0에 가까울수록 공포(과매도), 100에 가까울수록 탐욕(과열).

새 지표 추가 방법 (모듈화):
  1) score_xxx(hist, info) 함수를 만들고 (score, detail) 튜플 반환
  2) INDICATORS 리스트에 dict 한 줄 추가
  → 앱 화면(게이지/막대)에 자동 반영됨.
  (예: PER 밴드 위치, 뉴스 센티먼트 등)
"""
import math
import os
import re
import time
import numpy as np
import pandas as pd
import requests
import yfinance as yf
import yfsess


def _load_env():
    """모듈 폴더의 .env에서 환경변수 로드 (FINNHUB_API_KEY 등) + gemini_key.txt.
    이미 설정된 환경변수는 덮어쓰지 않음."""
    base = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(base, ".env")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        except Exception:
            pass
    gk = os.path.join(base, "gemini_key.txt")   # 뉴스 채점 폴백용 (app.py와 동일 키)
    if os.path.exists(gk) and not os.environ.get("GEMINI_API_KEY"):
        try:
            with open(gk, encoding="utf-8") as f:
                k = f.read().strip()
            if k:
                os.environ["GEMINI_API_KEY"] = k
        except Exception:
            pass


_load_env()


def clamp(x, lo=0.0, hi=100.0):
    """점수를 0~100 범위로 자름."""
    return float(min(max(x, lo), hi))


# ----------------------------- 개별 지표 -----------------------------
def score_momentum(hist, info=None):
    """① 모멘텀: 현재가 vs 125일 이동평균 이격도.
    이평 대비 +10% 이상 → 100점(탐욕), -10% 이하 → 0점(공포), 사이는 선형 보간."""
    close = hist["Close"]
    if len(close) < 125:
        return None, "데이터 부족(125일 미만)"
    ma = float(close.rolling(125).mean().iloc[-1])
    disp = float(close.iloc[-1]) / ma - 1          # 이격도
    score = clamp((disp + 0.10) / 0.20 * 100)      # -10%→0, +10%→100
    return score, f"125일 이평 대비 {disp*100:+.1f}%"


def score_rsi(hist, info=None):
    """② RSI(14일): 값을 그대로 점수로 사용 (70↑ 과매수=탐욕, 30↓ 과매도=공포).
    Wilder 방식(지수이동평균)으로 계산."""
    close = hist["Close"]
    if len(close) < 30:
        return None, "데이터 부족"
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = float((100 - 100 / (1 + rs)).iloc[-1])
    if math.isnan(rsi):
        return None, "계산 불가"
    return clamp(rsi), f"RSI {rsi:.0f}"


def score_52w(hist, info=None):
    """③ 52주 밴드 위치: (현재가-52주최저) ÷ (52주최고-52주최저) × 100.
    최고가 부근 → 탐욕, 최저가 부근 → 공포."""
    close = hist["Close"]
    yr = close.iloc[-252:] if len(close) >= 252 else close
    hi, lo = float(yr.max()), float(yr.min())
    if hi == lo:
        return None, "밴드 폭 0"
    pos = (float(close.iloc[-1]) - lo) / (hi - lo) * 100
    return clamp(pos), f"52주 밴드 하단 {pos:.0f}% 지점"


def score_volume(hist, info=None):
    """④ 거래량: 최근 5일 평균 vs 90일 평균 비율.
    상승 추세에서 거래량 급증 → 탐욕(50점 위), 하락 추세에서 급증 → 공포(50점 아래).
    급증이 없으면(비율≈1) 중립 50점."""
    vol, close = hist["Volume"], hist["Close"]
    if len(vol) < 95 or vol.iloc[-90:].mean() <= 0:
        return None, "데이터 부족"
    ratio = float(vol.iloc[-5:].mean() / vol.iloc[-90:].mean())
    trend = float(close.iloc[-1] / close.iloc[-6] - 1)   # 최근 5일 수익률로 방향 판단
    surge = clamp((ratio - 1.0) / 1.0 * 100) / 100        # 1배→0, 2배 이상→1
    score = 50 + 50 * surge if trend >= 0 else 50 - 50 * surge
    arrow = "상승" if trend >= 0 else "하락"
    return clamp(score), f"90일 평균의 {ratio:.1f}배 ({arrow} 중)"


def score_volatility(hist, info=None):
    """⑤ 변동성: 최근 20일 변동성 vs 90일 변동성 비율.
    변동성 급등은 공포 신호 → 비율 1.5배 이상이면 0점, 0.5배 이하면 100점, 1배=50점."""
    ret = hist["Close"].pct_change().dropna()
    if len(ret) < 95:
        return None, "데이터 부족"
    v20 = float(ret.iloc[-20:].std())
    v90 = float(ret.iloc[-90:].std())
    if v90 <= 0:
        return None, "계산 불가"
    ratio = v20 / v90
    score = clamp((1.5 - ratio) / 1.0 * 100)   # 0.5배→100, 1.5배→0
    return score, f"90일 대비 {ratio:.2f}배"


def score_per_band(hist, info=None):
    """⑥ PER 밴드 위치: 최근 5년 일별 PER 시계열에서 현재 PER의 백분위(0~100).
    - PER(t) = 주가(t) ÷ TTM EPS 근사(연간 EPS 사이 시간 보간 + 현재 TTM 앵커)
    - PER이 음수(적자)인 구간은 분포에서 제외
    - 적자 등으로 계산 불가면 (None, ...) 반환 → 평균에서 자동 제외
    필요 데이터는 info["_eps_series"](연간 EPS 시계열), info["_eps_ttm"](현재 TTM EPS)로
    주입받음 — 가치평가 앱은 이미 받아둔 값 재사용, 단독 실행은 compute_index가 조회."""
    info = info or {}
    eps = info.get("_eps_series")
    if eps is None or (hasattr(eps, "empty") and eps.empty):
        return None, "연간 EPS 데이터 없음"
    eps = eps.dropna()
    eps = eps[eps > 0]                      # 적자 연도 제외
    if eps.empty:
        return None, "적자 기업 — PER 계산 불가"
    eps.index = pd.to_datetime(eps.index)
    eps = eps.sort_index()
    close = hist["Close"].copy()
    close.index = pd.to_datetime(close.index)
    end = close.index[-1]
    ttm = info.get("_eps_ttm")
    if ttm and ttm > 0 and end > eps.index[-1]:   # 마지막 앵커 = 현재 TTM EPS
        eps = pd.concat([eps, pd.Series({end: float(ttm)})])
    start = max(end - pd.DateOffset(years=5), eps.index[0])
    c5 = close[close.index >= start]
    if len(c5) < 120:
        return None, "PER 시계열 부족"
    denom = eps.reindex(eps.index.union(c5.index)).interpolate(method="time")
    denom = denom.reindex(c5.index).ffill()
    per = (c5 / denom).dropna()
    per = per[per > 0]                      # 음수 PER 구간 제외
    if len(per) < 120:
        return None, "유효 PER 구간 부족"
    cur = float(per.iloc[-1])
    pct = float((per < cur).mean() * 100)   # 백분위 = 점수
    yrs = (per.index[-1] - per.index[0]).days / 365.25
    return clamp(pct), f"{yrs:.1f}년 분포의 백분위 {pct:.0f}% (PER {cur:.1f})"


# --- 뉴스 센티먼트: Finnhub 호출 캐시 (무료 플랜 분당 60회 제한 고려) ---
_SENT_CACHE = {}          # {symbol: (timestamp, json)}
_SENT_TTL = 15 * 60       # 15분


def _gemini_headline_score(heads, kind="주식"):
    """헤드라인 목록 → Gemini로 투자심리 0~100 채점. (점수, 설명) 반환.
    미국(Finnhub 헤드라인)·국내(네이버 헤드라인) 공용."""
    gkey = os.environ.get("GEMINI_API_KEY")
    if not gkey:
        return None, "Gemini 키 필요"
    prompt = (f"다음은 한 {kind}의 최근 뉴스 헤드라인이다. 전반적인 투자 심리를 "
              "0(극도로 부정적/공포)~100(극도로 긍정적/탐욕) 사이 정수 하나로만 답해라. "
              "숫자 외 다른 글자는 쓰지 마라.\n\n" + "\n".join(f"- {h}" for h in heads))
    try:
        g = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
            headers={"x-goog-api-key": gkey, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 64, "temperature": 0,
                                       "thinkingConfig": {"thinkingLevel": "low"}}},
            timeout=20)
        if g.status_code != 200:
            return None, f"AI 채점 실패 ({g.status_code})"
        text = g.json()["candidates"][0]["content"]["parts"][0]["text"]
        m = re.search(r"\d{1,3}", text)
        v = clamp(float(m.group()))
        return v, f"헤드라인 {len(heads)}개 AI 채점 {v:.0f}점"
    except Exception:
        return None, "AI 응답 해석 실패"


def _us_news_raw(sym, key):
    """미국: Finnhub news-sentiment(유료) → 실패 시 company-news 헤드라인 → Gemini."""
    r = requests.get("https://finnhub.io/api/v1/news-sentiment",
                     params={"symbol": sym, "token": key}, timeout=8)
    if r.status_code == 200:
        data = r.json()
        score = data.get("companyNewsScore")
        src = "뉴스 점수"
        if score is None:
            score = (data.get("sentiment") or {}).get("bullishPercent")
            src = "긍정 기사 비중"
        if score is not None:
            return clamp(float(score) * 100), f"{src} {float(score)*100:.0f}%"
    elif r.status_code not in (401, 403):
        return None, f"API 응답 {r.status_code}"
    to = time.strftime("%Y-%m-%d")
    frm = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
    r = requests.get("https://finnhub.io/api/v1/company-news",
                     params={"symbol": sym, "from": frm, "to": to, "token": key}, timeout=8)
    if r.status_code != 200:
        return None, f"뉴스 조회 실패 ({r.status_code})"
    heads = [h for h in (it.get("headline", "").strip() for it in (r.json() or [])[:10]) if h]
    if not heads:
        return None, "최근 7일 뉴스 없음"
    return _gemini_headline_score(heads, "미국 주식")


_VIX_CACHE = [0.0, None]


def _load_vix():
    """VIX 지수 2년치 (캐시 6시간). 미국 시장 공포지수."""
    now = time.time()
    if _VIX_CACHE[1] is not None and now - _VIX_CACHE[0] < 6 * 3600:
        return _VIX_CACHE[1]
    try:
        v = yfsess.ticker("^VIX").history(period="2y")["Close"].dropna()
        v.index = v.index.tz_localize(None)
        _VIX_CACHE[0], _VIX_CACHE[1] = now, v
        return v if len(v) else None
    except Exception:
        return None


def _market_vol(market):
    """시장 변동성지수 시계열 — 미국 VIX / 한국 VKOSPI. (이름, 시계열) 반환."""
    if market == "US":
        return "VIX", _load_vix()
    if market == "KR":
        try:
            import kr_data  # 지연 임포트 (순환 방지)
            return "VKOSPI", kr_data.load_vkospi()
        except Exception:
            return "VKOSPI", None
    return None, None


def score_vix(hist, info=None):
    """⑧ 시장 공포(VIX/VKOSPI): 시장 변동성지수의 1년 역백분위 → 0~100.
    지수가 높으면(시장 공포↑) 낮은 점수(공포), 낮으면 높은 점수(안주=탐욕).
    개별 종목의 자기 변동성이 못 잡는 '거시 심리'를 보완 — 백테스트로 예측력 개선 확인.
    미국=VIX, 한국=VKOSPI. 조회 실패 시 자동 제외."""
    info = info or {}
    name, v = _market_vol(info.get("_market"))
    if not name:
        return None, "지원 시장 아님"
    if v is None or len(v) < 60:
        return None, f"{name} 조회 실패"
    cur = float(v.iloc[-1])
    yr = v.iloc[-252:] if len(v) >= 252 else v
    pctl = float((yr < cur).mean())
    return clamp((1 - pctl) * 100), f"{name} {cur:.1f} (1년 {pctl*100:.0f}%ile)"


def score_news(hist, info=None):
    """⑦ 뉴스 센티먼트 → 0~100점.
    - 미국: Finnhub 헤드라인 → Gemini 채점
    - 한국: 네이버 헤드라인(info['_news_headlines']) → Gemini 채점
    - 실패/데이터 없음 → (None, ...)로 평균에서 자동 제외. 15분 캐시."""
    info = info or {}
    market = info.get("_market")
    sym = (info.get("_symbol") or "").upper().split(".")[0]
    now = time.time()
    ckey = f"{market}:{sym}"
    hit = _SENT_CACHE.get(ckey)
    if hit and now - hit[0] < _SENT_TTL:
        s, detail = hit[1]
        return s, detail + " (캐시)"
    try:
        if market == "KR":
            heads = [str(h).strip() for h in (info.get("_news_headlines") or []) if h][:10]
            if not heads:
                return None, "국내 뉴스 없음"
            s, detail = _gemini_headline_score(heads, "한국 주식")
        elif market == "US":
            if not re.fullmatch(r"[A-Z\-]{1,6}", sym):
                return None, "지원 심볼 아님"
            key = os.environ.get("FINNHUB_API_KEY")
            if not key:
                return None, ".env에 FINNHUB_API_KEY 없음"
            s, detail = _us_news_raw(sym, key)
        else:
            return None, "지원 시장 아님"
    except Exception as e:
        return None, f"호출 실패: {repr(e)[:50]}"
    _SENT_CACHE[ckey] = (now, (s, detail))
    return s, detail


# --------------------- 지표 레지스트리 (여기에 추가) ---------------------
INDICATORS = [
    {"key": "momentum", "name": "모멘텀 (125일 이격도)", "func": score_momentum,
     "tip": "주가가 장기 평균선보다 얼마나 위/아래에 있는지 — 많이 위면 과열(탐욕)"},
    {"key": "rsi", "name": "RSI (14일)", "func": score_rsi,
     "tip": "최근 상승/하락 강도 — 70 이상은 과매수(탐욕), 30 이하는 과매도(공포)"},
    {"key": "band52", "name": "52주 밴드 위치", "func": score_52w,
     "tip": "1년 최고~최저 사이에서 현재가의 위치 — 최고가 부근일수록 탐욕"},
    {"key": "volume", "name": "거래량 (5일 vs 90일)", "func": score_volume,
     "tip": "평소보다 거래가 얼마나 몰렸는지 — 오르며 몰리면 탐욕, 빠지며 몰리면 공포"},
    {"key": "volatility", "name": "변동성 (20일 vs 90일)", "func": score_volatility,
     "tip": "주가 출렁임이 평소보다 커졌는지 — 변동성 급등은 공포 신호"},
    {"key": "per_band", "name": "PER 밴드 위치 (5년)", "func": score_per_band,
     "tip": "현재 PER이 5년 역사에서 얼마나 비싼 위치인지 — 백분위가 높을수록 탐욕"},
    {"key": "vix", "name": "시장 공포 (VIX/VKOSPI)", "func": score_vix,
     "tip": "시장 전체의 변동성지수 (미국 VIX·한국 VKOSPI) — 시장이 겁먹으면 공포, 안주하면 탐욕"},
    {"key": "news", "name": "뉴스 센티먼트", "func": score_news,
     "tip": "최근 뉴스 논조가 얼마나 낙관적인지 (Finnhub) — 낙관 일색이면 탐욕"},
]

# 구간 정의: (상한, 라벨, 색상)
LEVELS = [
    (25, "극공포", "#d64550"),
    (45, "공포", "#e8883a"),
    (55, "중립", "#b0a94e"),
    (75, "탐욕", "#7fbf6b"),
    (100, "극탐욕", "#2e9e57"),
]


def level_of(score):
    """점수 → (라벨, 색상)."""
    for hi, label, color in LEVELS:
        if score <= hi:
            return label, color
    return LEVELS[-1][1], LEVELS[-1][2]


# ----------------------------- 종합 계산 -----------------------------
def compute_from_hist(hist, info=None):
    """이미 받아둔 OHLCV DataFrame으로 지수 계산 (가치평가 앱 통합용 — 중복 조회 방지).
    반환: {total, level, color, scores:[{name,score,detail,tip,color}]} 또는 None"""
    if hist is None or hist.empty:
        return None
    # yfinance가 국내 종목 등에서 최신 행에 NaN 종가를 넣는 경우가 있음(장중/데이터 지연)
    # → NaN이 지표에 번져 전체 평균을 오염시키므로 종가 결측 행은 제거.
    hist = hist[hist["Close"].notna()]
    if len(hist) < 30:
        return None
    info = info or {}
    scores = []
    for ind in INDICATORS:
        try:
            s, detail = ind["func"](hist, info)
        except Exception as e:
            s, detail = None, f"오류: {repr(e)[:60]}"
        # 2차 방어: NaN 점수는 None으로 바꿔 평균에서 제외 (평균 오염 방지)
        if s is not None and (not isinstance(s, (int, float)) or math.isnan(float(s))):
            s, detail = None, "데이터 결측"
        scores.append({"key": ind["key"], "name": ind["name"], "tip": ind["tip"],
                       "score": s, "detail": detail,
                       "color": level_of(s)[1] if s is not None else "#666"})
    valid = [x["score"] for x in scores if x["score"] is not None]
    if not valid:
        return None
    total = float(np.mean(valid))
    label, color = level_of(total)
    return {"total": total, "level": label, "color": color, "scores": scores}


def timeline_from_hist(hist, per_daily=None, weeks=104, market=None):
    """주간 공포탐욕지수 타임라인 (최근 ~2년). [{d, v}] 리스트 반환.
    각 지표를 시계열로 벡터화 계산 후 평균 — 스팟 계산과 동일한 공식.
    미국(market=='US')은 VIX 역백분위도 포함. 뉴스 센티먼트는 과거 재현 불가라 제외."""
    if hist is None or hist.empty or len(hist) < 300:
        return None
    df = hist[hist["Close"].notna()]
    c, v = df["Close"], df["Volume"]
    S = {}
    # ① 모멘텀: 125일 이평 이격도 ±10% → 0~100
    ma = c.rolling(125).mean()
    S["momentum"] = (c / ma - 1 + 0.10) / 0.20 * 100
    # ② RSI(14)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    S["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    # ③ 52주 밴드 위치
    hi, lo = c.rolling(252).max(), c.rolling(252).min()
    S["band52"] = (c - lo) / (hi - lo).replace(0, np.nan) * 100
    # ④ 거래량: 5일 vs 90일 급증 × 추세 방향
    vr = v.rolling(5).mean() / v.rolling(90).mean().replace(0, np.nan)
    surge = (vr - 1).clip(0, 1)
    sign = np.sign(c.pct_change(5)).replace(0, 1)   # 보합은 상승 취급 (스팟과 동일)
    S["volume"] = 50 + sign * surge * 50
    # ⑤ 변동성: 20일 vs 90일
    ret = c.pct_change()
    volr = ret.rolling(20).std() / ret.rolling(90).std().replace(0, np.nan)
    S["volatility"] = (1.5 - volr) / 1.0 * 100
    Sw = pd.DataFrame(S).clip(0, 100).resample("W-FRI").last()
    # ⑥ PER 밴드 위치: 각 주간 시점에서 직전 5년 분포의 백분위
    if per_daily is not None and len(per_daily) >= 260:
        pw = {}
        for t in Sw.index:
            win = per_daily[(per_daily.index <= t) &
                            (per_daily.index >= t - pd.DateOffset(years=5))]
            if len(win) >= 120:
                pw[t] = float((win < win.iloc[-1]).mean() * 100)
        Sw["per_band"] = pd.Series(pw)
    # ⑧ 시장 공포(VIX/VKOSPI): 각 주 직전 1년 역백분위
    if market in ("US", "KR"):
        _, vx = _market_vol(market)
        if vx is not None and len(vx) >= 60:
            vw = vx.resample("W-FRI").last().dropna()
            pv = {}
            for t in Sw.index:
                win = vw[(vw.index <= t) & (vw.index >= t - pd.DateOffset(years=1))]
                if len(win) >= 20:
                    pv[t] = (1 - float((win < win.iloc[-1]).mean())) * 100
            if pv:
                Sw["vix"] = pd.Series(pv)
    comp = Sw.mean(axis=1, skipna=True).dropna().iloc[-weeks:]
    if len(comp) < 8:
        return None
    return [{"d": t.strftime("%Y-%m-%d"), "v": round(float(x), 1)} for t, x in comp.items()]


def compute_index(ticker):
    """티커 하나의 공포탐욕지수 계산 (Streamlit 단독 앱용 — 직접 조회).
    반환: {ticker, name, price, total, level, color, scores:[...]}"""
    ticker = ticker.strip()
    # 통합 리졸버: 한글 회사명·6자리 코드 → .KS/.KQ, 영문 티커는 그대로
    try:
        import kr_data  # 지연 임포트 (순환 참조 방지)
        yf_ticker, code6, _nm = kr_data.resolve_query(ticker)
        if yf_ticker is None:
            raise ValueError(f"'{ticker}' 종목을 찾을 수 없습니다. 이름/티커를 확인하세요.")
        if code6:
            ticker = code6
    except ImportError:
        yf_ticker = ticker + ".KS" if re.fullmatch(r"\d{6}", ticker) else ticker
    ticker = ticker.upper()
    tk = yfsess.ticker(yf_ticker)
    hist = tk.history(period="6y", interval="1d")   # PER 밴드 지표용 5년 + 여유
    if hist.empty or len(hist) < 30:
        raise ValueError(f"'{ticker}' 주가 데이터를 찾을 수 없습니다. 티커를 확인하세요.")
    hist.index = hist.index.tz_localize(None)
    try:
        info = dict(tk.info)
    except Exception:
        info = {}
    # PER 밴드·뉴스·VIX 지표용 컨텍스트 주입
    info["_symbol"] = ticker
    info["_market"] = "KR" if re.fullmatch(r"\d{6}", ticker) else "US"
    info["_eps_ttm"] = info.get("trailingEps")
    try:
        df = tk.income_stmt
        for row in ("Diluted EPS", "Basic EPS"):
            if df is not None and not df.empty and row in df.index:
                s = df.loc[row].dropna()
                if not s.empty:
                    info["_eps_series"] = s.sort_index()
                    break
    except Exception:
        pass
    r = compute_from_hist(hist, info)
    if r is None:
        raise ValueError("지표를 하나도 계산하지 못했습니다.")
    r.update({
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "price": info.get("currentPrice") or info.get("regularMarketPrice")
                 or float(hist["Close"].iloc[-1]),
        "currency": info.get("currency", ""),
    })
    return r


if __name__ == "__main__":
    import sys
    for t in (sys.argv[1:] or ["NVDA"]):
        r = compute_index(t)
        print(f"\n{r['name']} ({r['ticker']}) — 종합 {r['total']:.0f}점 [{r['level']}]")
        for s in r["scores"]:
            v = "N/A" if s["score"] is None else f"{s['score']:.0f}점"
            print(f"  {s['name']:<22} {v:>6}  {s['detail']}")
