"""
S&P500 밸류에이션 대시보드 — 방법론 상수(config)
================================================
아래 값들은 '데이터'가 아니라 '방법론상의 가정'이라 자동 수급 대상이 아니다.
필요할 때 이 파일의 숫자만 바꾸면 계산 전체에 반영된다.
(SEP 전망치·S&P500 지수·PER·EPS·매크로는 전부 자동 수급 — snp.py 참조)
"""

# EPS 성장 프리미엄 (%p): 명목성장률 위에 얹는 기업이익 프리미엄
EPS_PREMIUM = 1.5

# 목표 PER 밴드 [베어, 베이스, 불]
PER_BANDS = [18, 20, 22]

# 2028 컨센서스가 없을 때 2027 대비 성장 가정 (참고용)
GROWTH_2028_ASSUMPTION = 0.08

# 참고 표시용: 최근 10년 평균 선행 PER
TEN_YEAR_AVG_FORWARD_PER = 19.0

# ── 캐시 TTL (초) — Render 무료 티어 대비: 요청 시 갱신 + TTL 캐시 ──
TTL_INDEX = 1 * 3600        # S&P500 지수 = 1시간
TTL_FACTSET = 24 * 3600     # FactSet 주간 리포트 = 24시간
TTL_SEP = 24 * 3600         # FRED SEP 전망 = 24시간
TTL_PER = 6 * 3600          # multpl PER = 6시간
TTL_SOFT = 6 * 3600         # 공포탐욕·VIX = 6시간

# EPS sanity 범위 (파싱 오류 판별) — S&P500 연간 EPS 상식 범위
EPS_SANITY_MIN = 250.0
EPS_SANITY_MAX = 450.0
