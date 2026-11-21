"""🧮 기업 내재가치 분석 탭 — 계산 재료 묶음 (/api/intrinsic)

계산(DCF·역DCF·잔여이익·배당할인·그레이엄·PER 밴드)은 화면(static/intrinsic.js)에서 한다 —
가정(할인율·성장률 등)을 바꾸면 바로 다시 계산되게. 여기서는 analyze_data 결과에서 재료만 뽑아
'주당' 숫자로 바꾸고, 분석 결과에 없는 배당 이력만 야후에서 더 받는다.
"""
import math
from datetime import datetime

import yfsess

UNIT = {"억원": 1e8, "M$": 1e6}


def _num(v):
    try:
        v = float(v)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def _fx(src, dst):
    """재무제표 통화 → 주가 통화 환율(다를 때만)."""
    if not src or not dst or src == dst:
        return 1.0
    try:
        h = yfsess.ticker(f"{src}{dst}=X").history(period="5d")["Close"].dropna()
        return float(h.iloc[-1]) if len(h) else None
    except Exception:
        return None


def dividends(yf_ticker):
    """배당 이력(연도별 주당 배당 합) · 최근 12개월 배당 · 5년 연평균 증가율."""
    try:
        s = yfsess.ticker(yf_ticker).dividends
    except Exception:
        return None
    if s is None or len(s) == 0:
        return None
    s = s[s > 0]
    idx = s.index.tz_localize(None) if getattr(s.index, "tz", None) is not None else s.index
    s.index = idx
    now = datetime.now()
    ttm = float(s[s.index > now.replace(year=now.year - 1)].sum())
    by = s.groupby(s.index.year).sum()
    years = {int(y): round(float(v), 4) for y, v in by.items() if y < now.year}   # 올해는 아직 덜 받았으니 뺌
    ys = sorted(years)[-5:]   # 최근 5년(4구간) — 더 길면 특별배당(삼성전자 2020년 등)에 끌려감
    cagr = None
    if len(ys) >= 3 and years[ys[0]] > 0 and years[ys[-1]] > 0:
        cagr = (years[ys[-1]] / years[ys[0]]) ** (1 / (len(ys) - 1)) - 1
    return {"ttm": round(ttm, 4), "years": {str(y): years[y] for y in sorted(years)[-8:]}, "cagr": None if cagr is None else round(cagr, 4)}


def build(an, yf_ticker=None):
    """analyze_data 결과(an) → 내재가치 계산 재료. yf_ticker: 배당 이력용 야후 티커(국내는 .KS/.KQ)."""
    price = _num(an.get("price"))
    ps = an.get("peg_sales") or {}
    tm = an.get("target_model") or {}
    disc = tm.get("discount") or {}
    mcap = _num(ps.get("mcap")) or _num(disc.get("mktcap"))
    ev = _num(ps.get("ev"))
    if not price or not mcap:
        raise ValueError("주가나 시가총액을 받지 못해 내재가치를 계산할 수 없어요.")
    shares = mcap / price
    fin = an.get("financials") or {}
    cur = an.get("currency")
    fx = _fx(fin.get("cur"), cur)
    mult = UNIT.get(fin.get("unit"))

    def per_share(arr):
        out = []
        for y, v in zip(fin.get("years") or [], arr or []):
            v = _num(v)
            out.append({"y": str(y).rstrip("E"), "est": str(y).endswith("E"),
                        "v": None if v is None or not mult or not fx else v * mult * fx / shares})
        return out

    roe = [{"y": str(y).rstrip("E"), "est": str(y).endswith("E"), "v": _num(v)}
           for y, v in zip(fin.get("years") or [], fin.get("roe") or [])]
    beta = (disc.get("beta") or {})
    b = _num(beta.get("adjusted")) or _num(beta.get("raw")) or _num(an.get("beta")) or 1.0
    rf, erp, crp, sp = (_num(disc.get(k)) or 0.0 for k in ("rf", "erp", "crp", "size_premium"))
    diag = an.get("diagnosis") or {}
    tg = {t.get("tag"): t for t in (an.get("targets") or [])}
    pt = {t.get("tag"): t for t in (an.get("pbr_targets") or [])}
    band = tg.get("예상EPS") or tg.get("TTM")
    pband = pt.get("TTM")
    yf_ticker = yf_ticker or an.get("ticker")
    return {
        "ticker": an.get("ticker"), "name": an.get("name"), "currency": cur, "market": disc.get("market") or ("KR" if cur == "KRW" else "US"),
        "sector": an.get("sector"), "industry": an.get("industry"),
        "is_fin": bool(diag.get("isFinancial")), "cyclical": bool(an.get("cyclical")),
        "price": price, "shares": shares, "mcap": mcap,
        "net_debt_ps": None if ev is None else (ev - mcap) / shares,
        "fin_unit": fin.get("unit"), "fin_fx": fx if fx != 1.0 else None,
        "fcf": per_share(fin.get("fcf")), "ni": per_share(fin.get("netinc")), "roe": roe,
        "eps_ttm": _num(an.get("eps_ttm")), "eps_fwd": _num(an.get("eps_fwd")), "bps": _num(an.get("bps")),
        "coe": {"rf": rf, "erp": erp, "crp": crp, "size": sp, "beta": round(b, 3)},
        "growth": tm.get("growth"),
        "div": dividends(yf_ticker) if yf_ticker else None,
        "per_band": None if not band else {"basis": band.get("tag"), "eps": band.get("eps"), "bear": band.get("bear"), "neutral": band.get("neutral"), "bull": band.get("bull")},
        "pbr_band": None if not pband else {"bps": pband.get("eps"), "bear": pband.get("bear"), "neutral": pband.get("neutral"), "bull": pband.get("bull")},
        "fcf_margin": _num(ps.get("fcf_margin")),
    }
