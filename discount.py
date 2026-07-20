"""
요구수익률(할인율) 자동 계산 모듈 — CAPM 확장
==============================================
요구수익률 = Rf + 조정β × ERP + CRP + 사이즈 프리미엄

각 구성요소:
  Rf   : 무위험이자율 (미국 FRED DGS10 / 한국 ECOS 국고채10년)
  β    : 2년 주간 수익률 회귀 베타 → 조정베타(블룸버그식)
  ERP  : 주식위험프리미엄 (다모다란 내재 ERP, 상수·수동 업데이트)
  CRP  : 국가 리스크 프리미엄 (다모다란 국가테이블, 상수·수동)
  size : 사이즈 프리미엄 (시가총액 구간별, 토글)

프론트가 ERP·사이즈 토글을 실시간 조절하므로, 이 모듈은 재료(Rf·회귀β·CRP·
시총)만 계산해 넘기고 최종 합산은 프론트에서 조립한다.
"""
import time
import numpy as np
import pandas as pd
import yfinance as yf

import rates
import kr_data

# --- 다모다란 기준 상수 (config) — 매월/분기 수동 업데이트, 스크래핑 금지 ---
ERP_US = 4.5   # 미국 주식위험프리미엄(%) — 다모다란 내재 ERP. 매월 damodaran.com에서 갱신.
CRP_KR = 0.7   # 한국 국가리스크프리미엄(%) — 다모다란 국가별 테이블. 수동 갱신.

_BENCH_CACHE = {}   # {bench: (ts, 주간수익률)}
_BENCH_TTL = 86400  # 하루 1회


def get_risk_free(market):
    """무위험이자율(%) — 미국 FRED DGS10 / 한국 ECOS 국고채10년.
    실패 시 기본값 4.0 반환."""
    try:
        s = kr_data.ecos_rate10y() if market == "KR" else rates.fred_series("DGS10")
        if s is not None and len(s):
            return float(s.iloc[-1])
    except Exception:
        pass
    return 4.0


def _bench_weekly_returns(bench):
    """벤치마크 지수 2년 주간 수익률 (캐시 1일). 미국 ^GSPC / 한국 ^KS11."""
    now = time.time()
    hit = _BENCH_CACHE.get(bench)
    if hit and now - hit[0] < _BENCH_TTL:
        return hit[1]
    try:
        b = yf.Ticker(bench).history(period="2y")["Close"]
        b.index = b.index.tz_localize(None)
        r = b.resample("W-FRI").last().pct_change().dropna()
        _BENCH_CACHE[bench] = (now, r)
        return r if len(r) else None
    except Exception:
        return None


def get_beta(hist_close, market):
    """2년 주간 수익률 회귀 베타 + 조정베타.
    hist_close: 종목 종가 시계열(pd.Series). 벤치마크는 시장에 따라 자동 선택.
    조정베타 = raw×2/3 + 1.0×1/3 (블룸버그식, 1로 수렴시켜 극단 완화).
    데이터 부족(주간 30개 미만) 시 β=1.0 기본값.
    반환: {"raw","adjusted","method":"회귀"|"기본값","n"}"""
    bench = "^KS11" if market == "KR" else "^GSPC"
    try:
        s = hist_close.copy()
        s.index = pd.to_datetime(s.index)
        sw = s.resample("W-FRI").last().pct_change().dropna()
        bw = _bench_weekly_returns(bench)
        if bw is not None:
            df = pd.concat([sw, bw], axis=1).dropna()
            df.columns = ["s", "b"]
            if len(df) >= 30 and df["b"].var() > 0:
                raw = float(df["s"].cov(df["b"]) / df["b"].var())
                adj = raw * (2 / 3) + 1.0 * (1 / 3)
                return {"raw": round(raw, 3), "adjusted": round(adj, 3),
                        "method": "회귀", "n": int(len(df))}
    except Exception:
        pass
    return {"raw": 1.0, "adjusted": 1.0, "method": "기본값", "n": 0}


def size_premium(market, mktcap):
    """시가총액 구간별 사이즈 프리미엄(%p).
    미국: 100억$↑ 0 / 20억~100억$ 1.0 / 20억$↓ 2.0
    한국: 10조원↑ 0 / 2조~10조원 1.0 / 2조원↓ 2.0"""
    if not mktcap:
        return 0.0
    if market == "KR":
        t = mktcap / 1e12   # 조원
        return 0.0 if t >= 10 else (1.0 if t >= 2 else 2.0)
    b = mktcap / 1e9        # 십억달러
    return 0.0 if b >= 10 else (1.0 if b >= 2 else 2.0)


def discount_data(hist_close, market, mktcap):
    """프론트로 넘길 요구수익률 재료 묶음. 최종 합산·토글은 프론트에서.
    반환: {rf, erp, crp, beta:{raw,adjusted,method,n}, size_premium, mktcap, market}"""
    beta = get_beta(hist_close, market)
    return {
        "rf": round(get_risk_free(market), 3),
        "erp": ERP_US,
        "crp": CRP_KR if market == "KR" else 0.0,
        "beta": beta,
        "size_premium": size_premium(market, mktcap),
        "mktcap": mktcap,
        "market": market,
    }
