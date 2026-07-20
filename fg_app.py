"""
개별 종목 공포탐욕지수 웹앱 (Streamlit)
========================================
실행:
    ./venv/bin/streamlit run fg_app.py
그다음 브라우저에서 http://localhost:8501 접속.

지표 계산 로직은 fear_greed.py 에 모듈화되어 있음 —
새 지표(PER 밴드, 뉴스 센티먼트 등)는 그쪽 INDICATORS에만 추가하면 됨.
"""
import streamlit as st
import plotly.graph_objects as go

from fear_greed import compute_index, level_of, LEVELS

st.set_page_config(page_title="종목 공포탐욕지수", page_icon="🌡️", layout="centered")

# ----------------------------- 상단: 검색 -----------------------------
st.title("🌡️ 종목 공포탐욕지수")
st.caption("모멘텀·RSI·52주 위치·거래량·변동성 5개 지표로 심리 과열/침체를 0~100으로 측정")

col1, col2 = st.columns([4, 1])
with col1:
    ticker = st.text_input("티커 입력", value="NVDA",
                           placeholder="예: NVDA, AAPL, TSLA (국내는 005930처럼 6자리)",
                           label_visibility="collapsed")
with col2:
    go_btn = st.button("분석", type="primary", use_container_width=True)

# 자주 찾는 종목 바로가기 칩
chips = st.columns(6)
for i, t in enumerate(["NVDA", "AAPL", "TSLA", "MSFT", "PLTR", "005930"]):
    if chips[i].button(t, use_container_width=True):
        ticker = t
        go_btn = True

if not (ticker and (go_btn or True)):   # 첫 로드에도 기본 티커로 표시
    st.stop()

# ----------------------------- 지수 계산 -----------------------------
try:
    with st.spinner(f"{ticker.upper()} 데이터 수집·계산 중…"):
        r = compute_index(ticker)
except Exception as e:
    st.error(f"⚠️ {e}")
    st.stop()

st.subheader(f"{r['name']} ({r['ticker']})  ·  {r['price']:,.2f} {r['currency']}")

# ----------------------------- 중앙: 반원 게이지 -----------------------------
# 구간: 0~25 극공포(빨강) / 25~45 공포 / 45~55 중립 / 55~75 탐욕 / 75~100 극탐욕(초록)
steps = []
prev = 0
for hi, label, color in LEVELS:
    steps.append({"range": [prev, hi], "color": color})
    prev = hi

gauge = go.Figure(go.Indicator(
    mode="gauge+number",
    value=round(r["total"]),
    number={"suffix": f"점 · {r['level']}", "font": {"size": 44}},
    gauge={
        "axis": {"range": [0, 100], "tickvals": [0, 25, 45, 55, 75, 100]},
        "bar": {"color": "rgba(20,20,20,.75)", "thickness": 0.35},  # 현재 값 바늘 역할
        "steps": steps,
        "threshold": {"line": {"color": "black", "width": 4},
                      "thickness": 0.9, "value": r["total"]},
    },
))
gauge.update_layout(height=320, margin=dict(t=40, b=10, l=30, r=30))
st.plotly_chart(gauge, use_container_width=True)

# 구간 범례
legend_cols = st.columns(len(LEVELS))
prev = 0
for col, (hi, label, color) in zip(legend_cols, LEVELS):
    col.markdown(
        f"<div style='text-align:center;font-size:13px'>"
        f"<span style='color:{color};font-size:18px'>●</span><br>{label}<br>"
        f"<span style='color:gray'>{prev}~{hi}</span></div>",
        unsafe_allow_html=True)
    prev = hi

st.divider()

# ----------------------------- 하단: 지표별 막대 -----------------------------
st.markdown("#### 지표별 점수")

valid = [s for s in r["scores"] if s["score"] is not None]
skipped = [s for s in r["scores"] if s["score"] is None]

# 가로 막대: 점수에 따라 구간 색상 적용, 호버에 초보자용 설명(tip) 표시
bar = go.Figure(go.Bar(
    x=[s["score"] for s in valid],
    y=[s["name"] for s in valid],
    orientation="h",
    marker_color=[level_of(s["score"])[1] for s in valid],
    text=[f"{s['score']:.0f}점 · {s['detail']}" for s in valid],
    textposition="auto",
    hovertext=[f"<b>{s['name']}</b><br>{s['tip']}<br><br>{s['detail']}" for s in valid],
    hoverinfo="text",
))
bar.update_layout(
    height=90 + 52 * len(valid),
    xaxis=dict(range=[0, 100], tickvals=[0, 25, 45, 55, 75, 100], title="0 = 극공포 · 100 = 극탐욕"),
    yaxis=dict(autorange="reversed"),
    margin=dict(t=10, b=40, l=10, r=10),
)
# 중립(50점) 기준선
bar.add_vline(x=50, line_dash="dash", line_color="gray", opacity=0.5)
st.plotly_chart(bar, use_container_width=True)

# 지표 설명 (툴팁 겸용 — 호버가 안 되는 모바일 대비 펼침 목록도 제공)
with st.expander("💡 각 지표가 뭘 보는 건가요? (초보자용 설명)"):
    for s in r["scores"]:
        st.markdown(f"- **{s['name']}** — {s['tip']}")

if skipped:
    st.caption("계산 제외: " + ", ".join(f"{s['name']}({s['detail']})" for s in skipped))

# ----------------------------- 주의 문구 -----------------------------
st.info("⚠️ 이 지수는 **심리적 과열/침체 참고용**이며, 실적에 따른 정당한 상승/하락과 "
        "구분해야 합니다. 좋은 실적으로 오르는 주식도 '탐욕'으로, 실적 악화로 빠지는 "
        "주식도 '공포'로 표시될 수 있습니다. 투자판단의 보조 지표로만 활용하세요.")
