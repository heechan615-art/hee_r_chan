"""공포탐욕지수 신뢰도 백테스트 — 지수/개별종목의 공탐지수 vs 실제 주가."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from fear_greed import timeline_from_hist

TICKERS = {"S&P500": "^GSPC", "나스닥": "^IXIC", "애플": "AAPL",
           "엔비디아": "NVDA", "테슬라": "TSLA", "삼성전자": "005930.KS"}

def analyze(name, tk):
    h = yf.Ticker(tk).history(period="4y", interval="1d")
    if h.empty or len(h) < 400: return None
    h.index = h.index.tz_localize(None)
    tl = timeline_from_hist(h.iloc[-800:], weeks=200)   # 주간 공탐지수
    if not tl: return None
    fg = pd.Series({pd.Timestamp(p["d"]): p["v"] for p in tl})
    px = h["Close"].resample("W-FRI").last().reindex(fg.index).dropna()
    fg = fg.reindex(px.index).dropna(); px = px.reindex(fg.index)
    if len(fg) < 50: return None

    # ① 동행성: 공탐지수 vs 주가수준(정규화) 동시점 상관
    coincident = fg.corr(px)
    # ② 예측력: 공탐지수 vs 향후 N주 수익률 (역발상이면 음의 상관)
    def fwd_corr(w):
        fut = px.shift(-w) / px - 1
        d = pd.concat([fg, fut], axis=1).dropna()
        return d.iloc[:, 0].corr(d.iloc[:, 1]) if len(d) > 20 else np.nan
    # ③ 극단 구간 이후 4주 수익률
    fut4 = (px.shift(-4) / px - 1) * 100
    fear = fut4[fg < 30].mean()      # 공포(<30) 이후
    greed = fut4[fg > 70].mean()     # 탐욕(>70) 이후
    mid = fut4[(fg >= 30) & (fg <= 70)].mean()
    return {"n": len(fg), "coincident": coincident,
            "pred4": fwd_corr(4), "pred12": fwd_corr(12),
            "fear_next": fear, "greed_next": greed, "mid_next": mid,
            "fear_n": int((fg < 30).sum()), "greed_n": int((fg > 70).sum())}

print(f"{'종목':<10}{'표본':>5}{'동행성':>8}{'예측4주':>8}{'예측12주':>9}"
      f"{'공포후4주':>10}{'중립후':>8}{'탐욕후4주':>10}")
print("-" * 78)
for name, tk in TICKERS.items():
    try:
        r = analyze(name, tk)
        if not r: print(f"{name:<10} 데이터 부족"); continue
        print(f"{name:<11}{r['n']:>4}{r['coincident']:>+8.2f}{r['pred4']:>+8.2f}"
              f"{r['pred12']:>+9.2f}{r['fear_next']:>+9.1f}%{r['mid_next']:>+7.1f}%{r['greed_next']:>+9.1f}%")
    except Exception as e:
        print(f"{name:<10} 오류: {repr(e)[:50]}")
print("-" * 78)
print("해석: 동행성↑=공탐과 주가가 같이 움직임 | 예측 음수=역발상 유효(공포 뒤 반등)")
print("      공포후4주 > 탐욕후4주 이면 역발상 신호가 실제로 작동한 것")
