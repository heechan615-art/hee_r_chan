"""VIX 가중치 스윕 — 종목 유형별 최적점 탐색 (예측12주 상관 기준)."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from fear_greed import timeline_from_hist

GROUPS = {
    "지수":       ["^GSPC", "^IXIC"],
    "대형안정":   ["AAPL", "MSFT", "GOOGL"],
    "고변동개별": ["NVDA", "TSLA", "AMD"],
}
WEIGHTS = [0, 0.10, 0.15, 0.20, 0.30]

vix = yf.Ticker("^VIX").history(period="5y")["Close"]; vix.index = vix.index.tz_localize(None)
vixw = vix.resample("W-FRI").last()
vix_score = (1 - vixw.rolling(52, min_periods=20).apply(lambda w:(w<w.iloc[-1]).mean()))*100

def series_for(tk):
    hd = yf.Ticker(tk).history(period="4y")
    if hd.empty or len(hd) < 400: return None
    hd.index = hd.index.tz_localize(None)
    tl = timeline_from_hist(hd.iloc[-800:], weeks=200)
    if not tl: return None
    fg0 = pd.Series({pd.Timestamp(p["d"]):p["v"] for p in tl})
    px = hd["Close"].resample("W-FRI").last().reindex(fg0.index).dropna()
    return fg0.reindex(px.index).dropna(), px

def pred12(fg, px):
    fut = px.shift(-12)/px - 1
    d = pd.concat([fg, fut], axis=1).dropna()
    return d.iloc[:,0].corr(d.iloc[:,1]) if len(d)>20 else np.nan

# 종목별 시계열 캐시
data = {}
for tks in GROUPS.values():
    for tk in tks:
        try:
            r = series_for(tk)
            if r: data[tk] = r
        except Exception: pass

print(f"{'유형':<11}" + "".join(f"{'VIX '+str(int(w*100))+'%':>9}" for w in WEIGHTS))
print("-"*(11+9*len(WEIGHTS)))
best_overall = {w: [] for w in WEIGHTS}
for grp, tks in GROUPS.items():
    row = []
    for w in WEIGHTS:
        vals = []
        for tk in tks:
            if tk not in data: continue
            fg0, px = data[tk]
            vs = vix_score.reindex(fg0.index).ffill()
            fg = (fg0*(1-w)+vs*w).dropna() if w else fg0
            c = pred12(fg, px)
            if pd.notna(c): vals.append(c); best_overall[w].append(c)
        row.append(np.mean(vals) if vals else np.nan)
    print(f"{grp:<12}" + "".join(f"{v:>+9.2f}" for v in row))
print("-"*(11+9*len(WEIGHTS)))
print(f"{'전체평균':<12}" + "".join(f"{np.mean(best_overall[w]):>+9.2f}" for w in WEIGHTS))
print("\n예측12주 상관이 더 음수(-)일수록 역발상 예측력↑ = 신뢰도 높음")
