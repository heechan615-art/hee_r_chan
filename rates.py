"""
FRED 10년물 국채 금리(DGS10) 로더 + 금리 보정 PER 회귀 모듈
=============================================================
목표주가 기능에서 사용:
  - 현재가치 할인: 할인율 = 현재 10년물 금리 + 리스크프리미엄
  - 금리 보정 밴드: 과거 5년 월별 평균 PER ~ 같은 시점 금리 선형 회귀
      PER = a + b × 금리  →  현재 금리를 넣어 '금리 보정 적정 PER'

키는 .env의 FRED_API_KEY에서 읽음 (fear_greed._load_env 재사용).
API 응답은 6시간 캐싱 — 금리는 하루 한 번 갱신되는 데이터라 충분.
"""
import os
import time
import requests
import pandas as pd

from fear_greed import _load_env

_load_env()

_CACHE = {}               # {series_id: (timestamp, pd.Series)}
_TTL = 6 * 3600           # 6시간


def fred_series(series_id="DGS10", years=6):
    """FRED 일별 시계열(pd.Series, index=날짜) 반환. 키 없음/실패 시 None."""
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return None
    now = time.time()
    hit = _CACHE.get(series_id)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    start = time.strftime("%Y-%m-%d", time.localtime(now - years * 365.25 * 86400))
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series_id, "api_key": key, "file_type": "json",
                    "observation_start": start},
            timeout=10)
        if r.status_code != 200:
            return None
        vals = {}
        for o in r.json().get("observations", []):
            if o.get("value") not in (".", "", None):   # "." = 휴장일 결측
                vals[pd.Timestamp(o["date"])] = float(o["value"])
        if not vals:
            return None
        s = pd.Series(vals).sort_index()
        _CACHE[series_id] = (now, s)
        return s
    except Exception:
        return None


def rate_block(per_daily=None, series=None, label="미 10년물"):
    """웹앱용 금리 블록 생성.
    반환: {"dgs10": 현재금리(%), "date": 기준일, "label": 표시명,
           "reg": {"a","b","r2","n","adj_per"} 또는 None}  /  실패 시 None
    per_daily: 일별 배수(PER/PBR) 시계열 — 주면 금리 보정 회귀까지 계산.
    series: 금리 시계열 직접 주입(한국 국고채 등). 없으면 FRED DGS10."""
    s = series if series is not None else fred_series("DGS10")
    if s is None or s.empty:
        return None
    cur = float(s.iloc[-1])
    out = {"dgs10": cur, "date": str(s.index[-1].date()), "label": label, "reg": None}

    # 월별 평균 PER ~ 월별 평균 금리 선형 회귀 (최소 24개월 필요)
    if per_daily is not None and len(per_daily) > 200:
        try:
            pm = per_daily.resample("M").mean().rename("per")
            rm = s.resample("M").mean().rename("rate")
            df = pd.concat([pm, rm], axis=1).dropna()
            if len(df) >= 24 and df["rate"].var() > 0:
                x, y = df["rate"], df["per"]
                b = float(x.cov(y) / x.var())
                a = float(y.mean() - b * x.mean())
                corr = x.corr(y)
                r2 = float(corr ** 2) if pd.notna(corr) else 0.0
                out["reg"] = {"a": a, "b": b, "r2": r2, "n": int(len(df)),
                              "adj_per": a + b * cur}
        except Exception:
            pass
    return out
