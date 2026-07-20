"""VIX 추가 전/후 공탐지수 신뢰도 비교 (미국 종목)."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from fear_greed import timeline_from_hist

US = {"S&P500": "^GSPC", "나스닥": "^IXIC", "애플": "AAPL",
      "엔비디아": "NVDA", "테슬라": "TSLA", "MS": "MSFT"}

# VIX → 공탐 점수 (VIX 높으면 공포=낮은 점수). 롤링 1년 역백분위.
vix = yf.Ticker("^VIX").history(period="5y")["Close"]
vix.index = vix.index.tz_localize(None)
vixw = vix.resample("W-FRI").last()
vix_score = (1 - vixw.rolling(52, min_periods=20).apply(
    lambda w: (w < w.iloc[-1]).mean())) * 100   # 역백분위 ×100

def metrics(fg, px):
    fg = fg.reindex(px.index).dropna(); px = px.reindex(fg.index)
    fut4 = (px.shift(-4)/px - 1) * 100
    fut12 = px.shift(-12)/px - 1
    d = pd.concat([fg, fut12], axis=1).dropna()
    pred12 = d.iloc[:,0].corr(d.iloc[:,1]) if len(d)>20 else np.nan
    fear = fut4[fg<30].mean(); greed = fut4[fg>70].mean()
    spread = (fear - greed) if (pd.notna(fear) and pd.notna(greed)) else np.nan
    return pred12, fear, greed, spread, int((fg<30).sum()), int((fg>70).sum())

print(f"{'종목':<9}{'':>6}{'예측12주':>9}{'공포후':>8}{'탐욕후':>8}{'스프레드':>9}{'극단표본':>10}")
print("-"*64)
for name, tk in US.items():
    h = yf.Ticker(tk).history(period="4y")["Close"]
    if h.empty: continue
    h.index = h.index.tz_localize(None)
    hd = yf.Ticker(tk).history(period="4y"); hd.index = hd.index.tz_localize(None)
    tl = timeline_from_hist(hd.iloc[-800:], weeks=200)
    if not tl: print(f"{name} 부족"); continue
    fg0 = pd.Series({pd.Timestamp(p["d"]): p["v"] for p in tl})
    px = h.resample("W-FRI").last().reindex(fg0.index).dropna()
    # VIX 결합: 기존 지수와 VIX 점수를 가중평균 (기술 70% + VIX 30%)
    vs = vix_score.reindex(fg0.index).ffill()
    for label, wt in (("기존", 0), ("+VIX15%", 0.15), ("+VIX30%", 0.30)):
        fg = (fg0*(1-wt) + vs*wt).dropna() if wt else fg0
        p12, fe, gr, sp, nf, ng = metrics(fg, px)
        print(f"{name if label=='기존' else '':<9}{label:>7}{p12:>+9.2f}"
              f"{fe:>+7.1f}%{gr:>+7.1f}%{sp:>+8.1f}%p{('공'+str(nf)+'/탐'+str(ng)):>11}")
    print()
print("-"*64)
print("스프레드(공포후−탐욕후)↑, 예측12주 음수↑ = 역발상 신뢰도 높음")
