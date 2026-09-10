"""
국내 주식 데이터 로더 모듈
===========================
통합 로더 인터페이스의 국내(KR) 파트 — 상위 로직(밴드/지수 계산)은
국가 구분 없이 동작하고, 여기서는 국내 전용 데이터만 담당한다.

  1) resolve_query(q): 검색어 → 야후 티커 변환
     - 한글 회사명("삼성전자", "카카오") → 네이버 자동완성으로 6자리 코드 확인
     - KOSPI → .KS / KOSDAQ → .KQ 자동 판별 (코스닥 수동 .KQ 입력 불필요)
     - 영문 티커(NVDA)는 그대로 통과
  2) ecos_rate10y(): 한국은행 ECOS에서 국고채 10년물 일별 금리
     (통계코드 817Y002 / 아이템 010210000, 키는 .env의 ECOS_API_KEY)

참고: pykrx(KRX 공식)의 일별 PER/펀더멘털은 KRX 측 API 변경으로 현재
무료 조회가 차단된 상태(빈 값 반환) → 일별 PER 시계열은 valuate.py의
TTM 보간 방식을 유지한다. KRX가 다시 열리면 여기에 붙이면 됨.
"""
import os
import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup

from fear_greed import _load_env

_load_env()

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

_RESOLVE_CACHE = {}          # {검색어: (야후티커, 6자리코드, 종목명)}
_ECOS_CACHE = [0.0, None]    # [timestamp, pd.Series]
_ECOS_TTL = 6 * 3600         # 금리는 하루 한 번 갱신 → 6시간 캐시면 충분


def resolve_query(q):
    """검색어 → (야후 티커, 6자리 코드 or None, 종목명 or None).
    - 'NVDA' 같은 영문 티커 → 그대로 (미국)
    - '005930.KS' / '247540.KQ' → 그대로 존중
    - '삼성전자'·'005930' → 네이버 자동완성으로 코드/시장 확인
    - 못 찾으면 (None, None, None) → 상장폐지/거래정지/오타 안내용"""
    q = q.strip()
    if not q:
        return None, None, None
    m = re.fullmatch(r"(\d{6})\.(KS|KQ)", q.upper())  # 접미사 직접 입력
    if m:
        return q.upper(), m.group(1), None
    if q in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[q]

    # 영문 1~6자는 대개 미국 티커지만 'NAVER'·'KAKAO'처럼 영문 회사명인 국내 종목도 있음.
    # → 자동완성으로 국내 '정확 일치' 종목이 있으면 국내로, 없으면 미국 티커로.
    ticker_like = bool(re.fullmatch(r"[A-Za-z.\-]{1,6}", q))
    out = (None, None, None)
    try:
        r = requests.get("https://ac.stock.naver.com/ac",
                         params={"q": q, "target": "stock"}, headers=UA, timeout=6)
        items = r.json().get("items", []) if r.status_code == 200 else []
        cands = [it for it in items
                 if it.get("nationCode") == "KOR"
                 and re.fullmatch(r"\d{6}", it.get("code", ""))
                 and it.get("typeCode") in ("KOSPI", "KOSDAQ", "KONEX")]
        exact = [it for it in cands if (it.get("name") or "").upper() == q.upper()]
        # 영문 티커형 입력은 '정확 일치'일 때만 국내로 인정(NVDA 등 미국 티커 오인 방지)
        pick = exact[0] if exact else (None if ticker_like else (cands[0] if cands else None))
        if pick:
            code = pick["code"]
            suf = ".KQ" if pick["typeCode"] == "KOSDAQ" else ".KS"
            out = (code + suf, code, pick.get("name"))
    except Exception:
        pass
    if out[0] is None and ticker_like:
        out = (q.upper(), None, None)                # 국내 정확일치 없음 → 미국 티커
    elif out[0] is None and re.fullmatch(r"\d{6}", q):
        out = (q + ".KS", q, None)                   # 자동완성 실패해도 6자리 코드는 코스피로 시도
    _RESOLVE_CACHE[q] = out
    return out


_WISE_CACHE = {}          # {code: (timestamp, dict)}
_WISE_TTL = 3600          # 1시간 — 컨센서스는 자주 안 바뀜

_UA_FULL = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}


def wisefn_annual(code, freq="Y"):
    """WISEfn(네이버 종목분석 원천)에서 재무 요약. freq='Y' 연간(확정5+예상3),
    'Q' 분기(확정5+예상3). encparam 토큰을 받아 AJAX(cF1001) 호출.
    반환: {"years"/"quarters": [...], "eps","bps","per","pbr","roe","revenue",
           "opinc","netinc","debt","equity","ocf","fcf","debtratio","opmargin"} / 실패 시 None"""
    now = time.time()
    ck = (code, freq)
    hit = _WISE_CACHE.get(ck)
    if hit and now - hit[0] < _WISE_TTL:
        return hit[1]
    out = None
    # 연간=20xx/12, 분기=20xx/03,06,09,12
    yr_pat = r"(20\d{2})/12\s*(\(E\))?" if freq == "Y" else r"(20\d{2})/(0[36]|09|12)\s*(\(E\))?"
    try:
        s = requests.Session()
        page = f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}"
        r = s.get(page, headers=_UA_FULL, timeout=10)
        enc = re.search(r"encparam:\s*'([^']+)'", r.text)
        cid = re.search(r"\bid:\s*'([^']*)'", r.text)
        if enc:
            r2 = s.get("https://navercomp.wisereport.co.kr/v2/company/ajax/cF1001.aspx",
                       params={"cmp_cd": code, "fin_typ": "0", "freq_typ": freq,
                               "encparam": enc.group(1), "id": cid.group(1) if cid else ""},
                       headers={**_UA_FULL, "Referer": page,
                                "X-Requested-With": "XMLHttpRequest"},
                       timeout=10)
            soup = BeautifulSoup(r2.text, "lxml")
            # 응답에 차트용 더미 테이블이 섞여 있음 → 기간 헤더가 있는 테이블 선택
            table, years = None, []
            for t in soup.find_all("table"):
                thead = t.find("thead")
                if not thead:
                    continue
                ys = []
                for th in thead.find_all("th"):
                    m = re.search(yr_pat, th.get_text(" ", strip=True))
                    if m:
                        if freq == "Y":
                            ys.append(m.group(1) + ("E" if m.group(2) else ""))
                        else:
                            ys.append(f"{m.group(1)[2:]}Q{(int(m.group(2))+2)//3}"
                                      + ("E" if m.group(3) else ""))
                if len(ys) >= 4:
                    table, years = t, ys
                    break
            if table:
                # 정확 일치(재무 항목) + 접두 일치(배수) 두 방식
                want_exact = {"매출액": "revenue", "영업이익": "opinc",
                              "당기순이익": "netinc", "부채총계": "debt",
                              "자본총계": "equity", "영업활동현금흐름": "ocf",
                              "FCF": "fcf", "부채비율": "debtratio",
                              "영업이익률": "opmargin"}
                want_prefix = {"EPS": "eps", "BPS": "bps", "PER": "per",
                               "PBR": "pbr", "ROE": "roe"}
                data = {"years": years}
                for tr in table.find("tbody").find_all("tr"):
                    th = tr.find("th")
                    if not th:
                        continue
                    lbl = th.get_text(" ", strip=True)
                    key = want_exact.get(lbl)
                    if not key:
                        key = next((v for k, v in want_prefix.items()
                                    if lbl.startswith(k)), None)
                    if not key or key in data:
                        continue
                    vals = []
                    for td in tr.find_all("td")[:len(years)]:
                        # td 안에 보조 span이 섞여 있어 첫 숫자만 추출
                        m = re.search(r"-?[\d,]+(?:\.\d+)?", td.get_text(" ", strip=True))
                        vals.append(float(m.group().replace(",", "")) if m else None)
                    data[key] = vals
                if years and (data.get("eps") or data.get("revenue")):
                    if freq == "Q":
                        data["quarters"] = data.pop("years")
                    out = data
    except Exception:
        out = None
    _WISE_CACHE[ck] = (now, out)
    return out


_DETAIL_CACHE = {}   # {code: (ts, dict)}


def wisefn_income_detail(code):
    """WISEfn 상세 손익계산서(연결, 억원) — 요약표(wisefn_annual)에 없는
    매출원가·판매비와관리비·이자비용·법인세비용까지. cF3002.aspx JSON 파싱.
    반환: {"years":[...], "intexp":[...연도별 이자비용], "breakdown":{최신확정 손익구성}} / 실패 시 None.
    → 이자보상배율(이자비용) + 국내 손익 폭포차트용."""
    now = time.time()
    hit = _DETAIL_CACHE.get(code)
    if hit and now - hit[0] < _WISE_TTL:
        return hit[1]
    out = None
    try:
        s = requests.Session()
        page = f"https://navercomp.wisereport.co.kr/v2/company/c1030001.aspx?cmp_cd={code}"
        html = s.get(page, headers=_UA_FULL, timeout=10).text
        i = html.find("cF3002.aspx")
        encs = re.findall(r"encparam:\s*'([^']+)'", html[:i] if i > 0 else html)
        if encs:
            j = s.get("https://navercomp.wisereport.co.kr/v2/company/cF3002.aspx",
                      params={"cmp_cd": code, "fin_typ": "0", "frqTyp": "0", "cn": "",
                              "encparam": encs[-1], "frq": "0", "finGubun": "MAIN"},
                      headers={**_UA_FULL, "Referer": page, "X-Requested-With": "XMLHttpRequest"},
                      timeout=10).json()
            yymm = j.get("YYMM") or []
            # 실적/예상 연도만(전년대비 컬럼 제외) — 'YYYY/12 ... (E)'
            years, cols = [], []
            for idx, s2 in enumerate(yymm):
                m = re.search(r"(20\d{2})/\d{2}\s*(\(E\))?", str(s2))
                if m and "전년대비" not in str(s2):
                    years.append(m.group(1) + ("E" if m.group(2) else ""))
                    cols.append(idx + 1)              # DATA1..DATAn
            data = j.get("DATA") or []

            def clean(nm):
                return re.sub(r"<.*?>", "", str(nm)).strip().lstrip(".·*[ ]").strip()

            def pick(*names, need_val=True):
                """이름이 정확히 일치하는 행의 값 배열(연도 정렬). 값이 있는 행 우선."""
                cand = None
                for row in data:
                    if clean(row.get("ACC_NM")) in names:
                        vals = [row.get(f"DATA{c}") for c in cols]
                        if not need_val or any(v is not None for v in vals):
                            return vals
                        cand = cand or vals
                return cand

            intexp = pick("이자비용")                      # 금융원가 하위 실제 이자비용
            rev = pick("매출액(수익)", "매출액", "수익(매출액)")
            cogs = pick("매출원가")
            gross = pick("매출총이익")
            sga = pick("판매비와관리비")
            opinc = pick("영업이익")
            pretax = pick("법인세비용차감전계속사업이익", "세전계속사업이익")
            tax = pick("법인세비용")
            netinc = pick("당기순이익")

            def latest(arr):
                if not arr:
                    return None
                for k in range(len(years) - 1, -1, -1):
                    if not years[k].endswith("E") and arr[k] is not None:
                        return round(float(arr[k]), 1)
                return None

            breakdown = {"revenue": latest(rev), "cogs": latest(cogs),
                         "grossProfit": latest(gross), "sga": latest(sga),
                         "opinc": latest(opinc), "pretax": latest(pretax),
                         "tax": latest(tax), "netinc": latest(netinc), "unit": "억원"}
            out = {"years": years,
                   "intexp": [None if v is None else round(float(v), 1) for v in (intexp or [None] * len(years))],
                   "breakdown": breakdown}
    except Exception:
        out = None
    _DETAIL_CACHE[code] = (now, out)
    return out


_VKOSPI_CACHE = [0.0, None, 0.0]   # [성공시각, 시계열, 마지막 실패시각]


def load_vkospi():
    """VKOSPI(코스피200 변동성지수) 일별 시계열 — 인베스팅닷컴(KSVKOSPI, id 956761).
    한국판 VIX. curl_cffi로 브라우저 지문 위장(일반 요청은 403). 인베스팅이 큰
    pointscount에 500을 주므로 160(≈7.5개월)으로 요청 — 역백분위엔 충분.
    성공 6시간 캐시 / 실패 5분 캐시(레이트리밋 재호출 폭주 방지). 실패 시 None."""
    now = time.time()
    if _VKOSPI_CACHE[1] is not None and now - _VKOSPI_CACHE[0] < 6 * 3600:
        return _VKOSPI_CACHE[1]
    if now - _VKOSPI_CACHE[2] < 300:   # 최근 5분 내 실패 → 재시도 안 함
        return None
    try:
        from curl_cffi import requests as creq
        for attempt in range(3):
            r = creq.get("https://api.investing.com/api/financialdata/956761/historical/chart/",
                         params={"interval": "P1D", "pointscount": "160"},
                         headers={"domain-id": "www"}, impersonate="chrome", timeout=15)
            if r.status_code == 200:
                rows = r.json().get("data", [])
                s = pd.Series({pd.Timestamp(x[0], unit="ms"): float(x[4])
                               for x in rows if x[4] is not None}).sort_index()
                s = s[s > 0].dropna()
                if len(s) >= 60:
                    _VKOSPI_CACHE[0], _VKOSPI_CACHE[1] = now, s
                    return s
                break
            time.sleep(3)   # 일시적 500/레이트리밋 → 잠시 후 재시도
    except Exception:
        pass
    _VKOSPI_CACHE[2] = now   # 실패 기록
    return None


def ecos_rate10y(years=6):
    """한국 국고채 10년물 일별 금리 시계열(pd.Series).
    키 없음/호출 실패 시 None → 호출부에서 금리 기능만 비활성화."""
    key = os.environ.get("ECOS_API_KEY")
    if not key:
        return None
    now = time.time()
    if _ECOS_CACHE[1] is not None and now - _ECOS_CACHE[0] < _ECOS_TTL:
        return _ECOS_CACHE[1]
    start = time.strftime("%Y%m%d", time.localtime(now - years * 365.25 * 86400))
    end = time.strftime("%Y%m%d", time.localtime(now))
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10000/"
           f"817Y002/D/{start}/{end}/010210000")
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        rows = (r.json().get("StatisticSearch") or {}).get("row") or []
        vals = {}
        for x in rows:
            try:
                vals[pd.Timestamp(x["TIME"])] = float(x["DATA_VALUE"])
            except (ValueError, KeyError):
                continue
        if not vals:
            return None
        s = pd.Series(vals).sort_index()
        _ECOS_CACHE[0], _ECOS_CACHE[1] = now, s
        return s
    except Exception:
        return None
