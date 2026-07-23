"""
일일 증시 브리핑 모듈 (간이 버전)
==================================
데이터 수집(네이버·yfinance) → Gemini가 일일 보고서 형식으로 서술.
- 지수: 코스피·코스닥(네이버) + S&P500·나스닥(yfinance)
- 급등·거래대금 상위: 네이버 순위 API
- 매크로: VKOSPI·VIX·환율·유가
- AI: Gemini로 오프닝·테마·리스크·클로징 서술 (참고용, 단정 회피)
"""
import os
import json
import time
import glob
import requests

import yfsess
import kr_data
from fear_greed import _load_vix

_load_env_done = False
try:
    from fear_greed import _load_env
    _load_env()
except Exception:
    pass

UA_M = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
        "Referer": "https://m.stock.naver.com/"}

_CACHE = {}   # {market: (ts, result)}
_TTL = 600    # 10분 (장중 갱신 감안)

# 과거 브리핑 저장 폴더 (날짜별 JSON, 3개월 보관)
_ARCHIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "briefings")
_KEEP_DAYS = 92


def _save_briefing(result, market="KR"):
    """브리핑을 시장·날짜별 파일로 저장 + 3개월 지난 파일 정리."""
    try:
        os.makedirs(_ARCHIVE, exist_ok=True)
        day = time.strftime("%Y-%m-%d")
        with open(os.path.join(_ARCHIVE, f"{market}_{day}.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        cutoff = time.time() - _KEEP_DAYS * 86400
        for p in glob.glob(os.path.join(_ARCHIVE, "*.json")):
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
    except Exception:
        pass


def list_briefings(market="KR"):
    """저장된 브리핑 날짜 목록 (최신순)."""
    try:
        days = [os.path.basename(p)[len(market) + 1:-5]
                for p in glob.glob(os.path.join(_ARCHIVE, f"{market}_*.json"))]
        return sorted(days, reverse=True)
    except Exception:
        return []


def load_briefing(day, market="KR"):
    """특정 날짜 브리핑 불러오기."""
    try:
        p = os.path.join(_ARCHIVE, f"{market}_{day}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _naver_index(code, name):
    try:
        r = requests.get(f"https://m.stock.naver.com/api/index/{code}/basic",
                         headers=UA_M, timeout=8)
        d = r.json()
        return {"name": name, "price": float(str(d.get("closePrice")).replace(",", "")),
                "chg": float(str(d.get("fluctuationsRatio")).replace(",", ""))}
    except Exception:
        return {"name": name, "price": None, "chg": None}


def _yahoo_chart(sym):
    """야후 차트 API(curl_cffi) — 지수 최근 종가·등락률. 클라우드에서 .history보다 안정적."""
    try:
        from curl_cffi import requests as creq
        r = creq.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                     params={"range": "5d", "interval": "1d"}, impersonate="chrome", timeout=10)
        if r.status_code != 200:
            return None
        res = r.json()["chart"]["result"][0]
        cl = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        if len(cl) >= 2:
            return round(float(cl[-1]), 2), round((cl[-1] / cl[-2] - 1) * 100, 2)
    except Exception:
        pass
    return None


def _us_index(tk, name):
    # 1차: 야후 차트 API(curl_cffi) — Render 등 클라우드 IP에서 안정적
    ch = _yahoo_chart(tk)
    if ch:
        return {"name": name, "price": ch[0], "chg": ch[1]}
    # 폴백: yfinance .history
    try:
        h = yfsess.ticker(tk).history(period="5d")["Close"].dropna()
        if len(h) >= 2:
            return {"name": name, "price": round(float(h.iloc[-1]), 2),
                    "chg": round(float(h.iloc[-1] / h.iloc[-2] - 1) * 100, 2)}
    except Exception:
        pass
    return {"name": name, "price": None, "chg": None}


def get_indices(market="KR"):
    if market == "US":
        return [_us_index("^GSPC", "S&P500"), _us_index("^IXIC", "나스닥"),
                _us_index("^DJI", "다우존스"), _us_index("^SOX", "필라델피아반도체")]
    return [_naver_index("KOSPI", "코스피"), _naver_index("KOSDAQ", "코스닥"),
            _us_index("^GSPC", "S&P500"), _us_index("^IXIC", "나스닥")]


def _yahoo_screener(scr, n):
    """야후 스크리너 — day_gainers/most_actives/day_losers. curl_cffi로 클라우드 우회."""
    try:
        from curl_cffi import requests as creq
        r = creq.get("https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved",
                     params={"scrIds": scr, "count": n}, impersonate="chrome", timeout=10)
        if r.status_code != 200:
            return []
        quotes = r.json()["finance"]["result"][0]["quotes"]
        out = []
        for q in quotes[:n]:
            out.append({"name": q.get("shortName") or q.get("symbol"),
                        "code": q.get("symbol"),
                        "chg": round(q.get("regularMarketChangePercent", 0) or 0, 2)})
        return out
    except Exception:
        return []


def _naver_rank(kind, market, n):
    """kind: 'up'(급등)|'down'(급락)|'marketValue'(거래대금)."""
    try:
        r = requests.get(f"https://m.stock.naver.com/api/stocks/{kind}/{market}",
                         params={"page": 1, "pageSize": n}, headers=UA_M, timeout=8)
        out = []
        for s in (r.json().get("stocks") or [])[:n]:
            out.append({"name": s.get("stockName"), "code": s.get("itemCode") or s.get("reutersCode"),
                        "price": s.get("closePrice"),
                        "chg": float(str(s.get("fluctuationsRatio") or 0).replace(",", ""))})
        return out
    except Exception:
        return []


def get_movers(market="KR"):
    if market == "US":
        return {
            "kospi_up": _yahoo_screener("day_gainers", 10),      # 급등
            "kosdaq_up": [],
            "kospi_val": _yahoo_screener("most_actives", 10),    # 거래활발(주도주)
            "kospi_down": _yahoo_screener("day_losers", 5),      # 급락
        }
    return {
        "kospi_up": _naver_rank("up", "KOSPI", 10),
        "kosdaq_up": _naver_rank("up", "KOSDAQ", 8),
        "kospi_val": _naver_rank("marketValue", "KOSPI", 10),
        "kospi_down": _naver_rank("down", "KOSPI", 5),
    }


def _stock_news(code, n=5):
    """종목 뉴스 헤드라인 (네이버 모바일)."""
    import re as _re
    import html as _html
    try:
        r = requests.get(f"https://m.stock.naver.com/api/news/stock/{code}",
                         params={"pageSize": n, "page": 1}, headers=UA_M, timeout=8)
        items = []
        for grp in (r.json() if isinstance(r.json(), list) else []):
            items += grp.get("items", [])
        heads = []
        for it in items[:n]:
            t = _re.sub(r"<[^>]+>", "", _html.unescape(it.get("title", ""))).strip()
            if t:
                heads.append(t)
        return heads
    except Exception:
        return []


_ETF_KW = ("TIGER", "KODEX", "KBSTAR", "ARIRANG", "ACE", "SOL", "PLUS", "ETF",
           "레버리지", "인버스", "선물", "채권", "리츠", "TR")


def _us_stock_news(sym, n=4):
    """미국 종목 뉴스 헤드라인 (Finnhub company-news, 영문)."""
    key = os.environ.get("FINNHUB_API_KEY")
    if not key or not sym:
        return []
    try:
        to = time.strftime("%Y-%m-%d")
        frm = time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))
        r = requests.get("https://finnhub.io/api/v1/company-news",
                         params={"symbol": sym.upper(), "from": frm, "to": to, "token": key},
                         timeout=8)
        if r.status_code != 200:
            return []
        return [it.get("headline", "").strip() for it in (r.json() or [])[:n]
                if it.get("headline")]
    except Exception:
        return []


def get_market_issues(movers, market="KR"):
    """오늘 시장을 움직인 주요 이슈 재료 — 주도주 뉴스 헤드라인 모음."""
    heads, seen = [], set()
    picks = (movers["kospi_val"][:5] + movers["kospi_up"][:3]
             + movers["kosdaq_up"][:2] + movers["kospi_down"][:2])
    for s in picks:
        nm = s.get("name") or ""
        if any(k in nm.upper() for k in _ETF_KW) or not s.get("code"):
            continue
        hs = _us_stock_news(s["code"], 4) if market == "US" else _stock_news(s["code"], 4)
        for h in hs:
            if h and h not in seen:
                seen.add(h)
                heads.append(h)
    return heads[:26]


def _gemini_market_issues(heads, indices, market="KR"):
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not heads:
        return None
    idx = " · ".join(f"{i['name']} {i['chg']:+.2f}%" for i in indices if i.get("price") is not None)
    hs = "\n".join(f"  - {h}" for h in heads)
    mkt_kw = "미국 증시(S&P500·나스닥·다우)" if market == "US" else "한국 증시(코스피·코스닥)"
    stk_ex = ("NVDA, AAPL, MSFT, AVGO, AMD (미국 종목은 반드시 티커로)" if market == "US"
              else "삼성전자, SK하이닉스, 한미반도체, 이오테크닉스, 리노공업")
    en_note = ("헤드라인이 영문이면 한국어로 해석해서 정리. " if market == "US" else "")
    prompt = (
        f"오늘 {mkt_kw} 지수: {idx}\n"
        f"오늘 시장 주도주 관련 뉴스 헤드라인:\n{hs}\n\n"
        f"{en_note}"
        "이 뉴스들을 바탕으로, 개별 종목이 아니라 '오늘 시장 전체를 움직인 주요 이슈' "
        "정확히 3개를 뽑아 정리해줘. 한국어 존댓말, 형식:\n"
        "🔴 이슈 제목 (예: 반도체 반등 — 외국인 수급 개선)\n"
        "[핵심 배경] 무슨 일이 있었나 (뉴스 근거)\n"
        "[시장 영향] 어떤 섹터·대형주가 어떻게 움직였나\n"
        "[인사이트] 관전 포인트 (추정임을 전제)\n"
        f"[관련 종목] 이 이슈에 직간접 수혜가 예상되는 "
        f"{'미국 상장 종목 5개를 티커로' if market == 'US' else '한국 상장 종목 5개를'} "
        f"쉼표로 나열 (예: {stk_ex})\n\n"
        "규칙: 시장 전체 흐름을 만든 이슈 중심(반도체 수급·매크로·수출·정책 등). "
        "헤드라인에 없는 사실 지어내기 금지. 단정 금지. 매수·매도 권유 금지. "
        f"[관련 종목]은 참고용 예시이며 실재하는 {'미국' if market == 'US' else '한국'} 상장사만. "
        "각 이슈 3~4문장 내로 간결하게.")
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.4,
                                       "thinkingConfig": {"thinkingLevel": "low"}}},
            timeout=40)
        if r.status_code != 200:
            return None
        parts = (r.json()["candidates"][0]["content"].get("parts") or [])
        return "".join(p.get("text", "") for p in parts).strip() or None
    except Exception:
        return None


def get_macro(market="KR"):
    out = {}
    # 환율
    try:
        h = yfsess.ticker("KRW=X").history(period="5d")["Close"].dropna()
        out["usdkrw"] = round(float(h.iloc[-1]), 1) if len(h) else None
    except Exception:
        out["usdkrw"] = None
    # 유가 (WTI)
    try:
        h = yfsess.ticker("CL=F").history(period="5d")["Close"].dropna()
        if len(h) >= 2:
            out["wti"] = round(float(h.iloc[-1]), 1)
            out["wti_chg"] = round(float(h.iloc[-1] / h.iloc[-2] - 1) * 100, 1)
    except Exception:
        out["wti"] = None
    # VIX
    try:
        v = _load_vix()
        out["vix"] = round(float(v.iloc[-1]), 1) if v is not None and len(v) else None
    except Exception:
        out["vix"] = None
    # VKOSPI
    try:
        vk = kr_data.load_vkospi()
        out["vkospi"] = round(float(vk.iloc[-1]), 1) if vk is not None and len(vk) else None
    except Exception:
        out["vkospi"] = None
    return out


_SUPPLY_CACHE = {}   # {sosok: (ts, dict)}


def _kr_supply_one(sosok):
    """네이버 금융 투자자별 매매동향 — 시장(코스피01/코스닥02) 순매수(억원). 최근 영업일 자동 탐색."""
    import re as _re
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    kst = _tz(_td(hours=9))
    now = time.time()
    c = _SUPPLY_CACHE.get(sosok)
    if c and now - c[0] < 1800:      # 30분 캐시
        return c[1]
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "Referer": "https://finance.naver.com/"}
    out = None
    for back in range(0, 7):
        day = (_dt.now(kst) - _td(days=back)).strftime("%Y%m%d")
        try:
            r = requests.get("https://finance.naver.com/sise/investorDealTrendDay.naver",
                             params={"bizdate": day, "sosok": sosok}, headers=hdr, timeout=8)
            r.encoding = "euc-kr"
            plain = _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", r.text))
            i = plain.find("연기금등")
            if i < 0:
                continue
            m = _re.search(r"(\d\d\.\d\d\.\d\d)\s+(-?[\d,]+)\s+(-?[\d,]+)\s+(-?[\d,]+)", plain[i:i + 200])
            if m:
                to_i = lambda s: int(s.replace(",", ""))
                out = {"date": m.group(1), "individual": to_i(m.group(2)),
                       "foreign": to_i(m.group(3)), "institution": to_i(m.group(4))}
                break
        except Exception:
            continue
    _SUPPLY_CACHE[sosok] = (now, out)
    return out


def get_supply(market="KR"):
    """투자자별 순매수(억원). 미국은 해당 개념이 없어 None."""
    if market == "US":
        return None
    return {"kospi": _kr_supply_one("01"), "kosdaq": _kr_supply_one("02")}


def _gemini_json(prompt, max_tokens=4096, temp=0.6):
    """Gemini에 JSON 응답 강제 요청. 실패 시 None."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temp,
                                       "responseMimeType": "application/json",
                                       "thinkingConfig": {"thinkingLevel": "low"}}},
            timeout=60)
        if r.status_code != 200:
            return None
        parts = (r.json()["candidates"][0]["content"].get("parts") or [])
        txt = "".join(p.get("text", "") for p in parts).strip()
        return json.loads(txt) if txt else None
    except Exception:
        return None


def _report_data_block(indices, supply, movers, macro, news, market):
    """AI에 넘길 데이터 요약 텍스트."""
    L = []
    L.append("[지수]")
    for i in indices:
        if i["price"] is not None:
            L.append(f"  {i['name']}: {i['price']} ({i['chg']:+.2f}%)")
    if market != "US" and supply:
        for key, nm in (("kospi", "코스피"), ("kosdaq", "코스닥")):
            s = supply.get(key)
            if s:
                L.append(f"[{nm} 수급(억원)] 개인 {s['individual']:+,} · 외국인 {s['foreign']:+,} · 기관 {s['institution']:+,}")
    up_lbl = "급등 상위" if market == "US" else "코스피 급등"
    L.append(f"[{up_lbl}]")
    for s in movers["kospi_up"]:
        L.append(f"  {s['name']} ({s.get('code','')}) {s['chg']:+}%")
    if movers.get("kosdaq_up"):
        L.append("[코스닥 급등]")
        for s in movers["kosdaq_up"]:
            L.append(f"  {s['name']} ({s.get('code','')}) {s['chg']:+}%")
    L.append("[거래대금 상위(주도주)]")
    for s in movers["kospi_val"]:
        L.append(f"  {s['name']} ({s.get('code','')}) {s['chg']:+}%")
    if movers.get("kospi_down"):
        L.append("[급락]")
        for s in movers["kospi_down"]:
            L.append(f"  {s['name']} {s['chg']}%")
    m = macro or {}
    if market == "US":
        L.append(f"[매크로] VIX {m.get('vix')}, WTI {m.get('wti')}달러, 환율 {m.get('usdkrw')}원")
    else:
        L.append(f"[매크로] 환율 {m.get('usdkrw')}원, WTI {m.get('wti')}달러, VIX {m.get('vix')}, VKOSPI {m.get('vkospi')}")
    if news:
        L.append("[오늘 주도주 관련 뉴스 헤드라인]")
        for h in news[:24]:
            L.append(f"  - {h}")
    return "\n".join(L)


def _gemini_narrative(data, date_str, mkt, tick):
    """헤드라인·수급해설·빅뉴스 3건(상세)·총평."""
    prompt = (
        f"너는 증권사 리서치센터 수석 애널리스트야. 오늘({date_str}) {mkt} 마감 데이터를 근거로 "
        "'프리미엄 일일 증시 보고서'의 서술 파트를 작성해. 데이터에 없는 수치는 지어내지 마.\n\n"
        f"=== 오늘의 데이터 ===\n{data}\n\n"
        "아래 JSON 스키마로만 답해(설명·마크다운 없이 순수 JSON):\n"
        "{\n"
        '  "headline": {"title": "신문 헤드라인 스타일 제목(수치 포함, 25자 내외)", "hook": "오늘 장을 한 문장으로 요약"},\n'
        '  "supply_comment": "수급(개인/외국인/기관) 흐름 해설 2~3문장. 미국이면 지수·주도섹터 해설",\n'
        '  "bignews": [\n'
        '     {"rank":1, "title":"오늘의 빅뉴스 제목(구체적으로)",\n'
        '      "background":"핵심 배경 — 무슨 일이 있었는지 뉴스·데이터 근거로 4~6문장 상세히. 수치·회사명·인과를 구체적으로.",\n'
        '      "impact":"시장 영향 — 어떤 섹터·종목이 어떻게 움직였는지 3~4문장. 수급·지수 연결.",\n'
        '      "insight":"인사이트 — 이 이슈를 어떻게 해석해야 하는지, 관전 포인트는 무엇인지 3~4문장(추정 전제)."}\n'
        "  ],\n"
        '  "closing": "오늘 장 총평 5~7문장. 수급·주도섹터·리스크·다음 관전포인트를 종합한 심층 코멘트. 수석 애널리스트 톤."\n'
        "}\n\n"
        "작성 규칙:\n"
        "- bignews는 오늘 시장을 움직인 가장 중요한 이슈 **정확히 3개**. 각 이슈의 background/impact/insight를 "
        "실제 애널리스트 리포트처럼 **길고 자세하게** 써(간략 금지). 뉴스 헤드라인과 데이터를 최대한 활용.\n"
        f"- {tick}데이터에 있는 실제 수치만 사용. 없는 사실은 지어내지 마.\n"
        "- 모든 인과·해석은 '추정' 전제(단정 금지). 매수·매도 권유 금지. 존댓말. 반드시 유효한 JSON.")
    return _gemini_json(prompt, max_tokens=8192, temp=0.5)


def _gemini_themes(data, date_str, mkt, tick, deriv_ex):
    """핵심 테마 3개 × 메인종목 3개 × 관련주 3~5개."""
    prompt = (
        f"너는 증권사 리서치센터 애널리스트야. 오늘({date_str}) {mkt} 급등·거래대금 데이터를 근거로 "
        "'오늘을 주도한 핵심 테마'를 정리해. 데이터에 없는 종목·수치는 지어내지 마.\n\n"
        f"=== 오늘의 데이터 ===\n{data}\n\n"
        "아래 JSON 스키마로만 답해(설명·마크다운 없이 순수 JSON):\n"
        "{\n"
        '  "themes": [\n'
        '    {"name":"테마명", "range":"대표 등락 범위(예: +18~30%)", "summary":"이 테마가 오늘 강한 이유 2~3문장",\n'
        '     "stocks":[\n'
        '        {"name":"메인 종목명", "chg":숫자(%), "sector":"한줄 사업설명",\n'
        '         "reason":"이 종목이 오늘 왜 이슈였는지 3~4문장 상세 코멘트(뉴스·데이터 근거, 추정 전제)",\n'
        '         "related":[ {"name":"관련주명", "note":"왜 같이 수혜/연관인지 한 줄"} ] }\n'
        "     ] }\n"
        "  ]\n"
        "}\n\n"
        "작성 규칙:\n"
        "- 테마는 급등·거래대금 데이터를 묶어 **정확히 3개**. 각 테마의 메인 종목은 **3개**(총 9종목).\n"
        "- 메인 종목은 반드시 데이터에 등장한 실제 종목, chg는 데이터의 실제 등락률.\n"
        "- 각 메인 종목마다 related(관련주)를 **3~5개** 제시. 밸류체인/동일테마 수혜주를 추정으로 "
        f"({deriv_ex}). 실재하는 상장사만.\n"
        f"- {tick}각 종목의 reason은 **길고 구체적으로**(왜 올랐는지, 무슨 재료인지).\n"
        "- 모든 인과·테마·관련주는 '추정' 전제(단정 금지). 매수·매도 권유 금지. 존댓말. 반드시 유효한 JSON.")
    return _gemini_json(prompt, max_tokens=8192, temp=0.55)


def _gemini_report(indices, supply, movers, macro, news, date_str, market="KR"):
    """일일 보고서(구조화 JSON) 생성 — 서술(헤드라인·빅뉴스3·총평) + 테마(3×3×관련주)를 두 번 호출로."""
    mkt = "미국 증시(S&P500·나스닥·다우·필라델피아반도체)" if market == "US" else "한국 증시(코스피·코스닥)"
    data = _report_data_block(indices, supply, movers, macro, news, market)
    tick = ("종목명은 반드시 영문 티커(예: NVDA)로 쓰고 한국어 설명을 덧붙여. "
            if market == "US" else "종목명은 한국어 정식 명칭(예: 삼성전자)으로 써. ")
    deriv_ex = ("예: NVDA의 관련주로 AVGO·AMD" if market == "US"
                else "예: SK하이닉스의 관련주로 한미반도체·이오테크닉스")
    nar = _gemini_narrative(data, date_str, mkt, tick)
    thm = _gemini_themes(data, date_str, mkt, tick, deriv_ex)
    rep = {}
    if isinstance(nar, dict):
        rep.update(nar)
    if isinstance(thm, dict):
        rep["themes"] = thm.get("themes") or []
    if not rep:
        return None
    # 종목 chip 연결용: 이름→코드 매핑
    code_by_name = {}
    for grp in movers.values():
        for s in grp:
            if s.get("name"):
                code_by_name[s["name"]] = s.get("code")
    for th in rep.get("themes") or []:
        for st in th.get("stocks") or []:
            st["code"] = code_by_name.get(st.get("name"))
    return rep


def _gemini_brief(data_str, date_str, market="KR"):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    mkt = "미국(S&P500·나스닥·다우)" if market == "US" else "한국(코스피·코스닥)"
    prompt = (
        f"오늘({date_str}) {mkt} 증시 데이터야:\n{data_str}\n\n"
        "이 데이터만 근거로 '일일 증시 브리핑'을 한국어 존댓말로 작성해줘. 형식:\n"
        "【오늘 한 줄 요약】 한 문장\n"
        "【지수·시장】 지수 흐름 2~3문장\n"
        "【주도 테마】 급등 종목들을 2~3개 테마로 묶고, 각 테마가 왜 강한지 추정 (종목명 포함)\n"
        "【리스크 점검】 2~3개 (변동성·낙폭·매크로 등)\n"
        "【클로징】 오늘의 핵심 행동지침 한 줄\n\n"
        "규칙: 주어진 데이터 외 지어내지 말 것. 영문 종목/뉴스는 한국어로. "
        "테마·인과는 '추정' 전제(단정 금지). 각 섹션 간결하게. 종목 추천·매수매도 권유 금지.")
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.5,
                                       "thinkingConfig": {"thinkingLevel": "low"}}},
            timeout=40)
        if r.status_code != 200:
            return None
        parts = (r.json()["candidates"][0]["content"].get("parts") or [])
        return "".join(p.get("text", "") for p in parts).strip() or None
    except Exception:
        return None


def daily_briefing(market="KR"):
    """일일 브리핑 생성 (KR/US). 10분 캐시(시장별)."""
    now = time.time()
    c = _CACHE.get(market)
    if c and now - c[0] < _TTL:
        return c[1]
    indices = get_indices(market)
    movers = get_movers(market)
    macro = get_macro(market)
    supply = get_supply(market)
    news = get_market_issues(movers, market)
    date_str = time.strftime("%Y-%m-%d %H:%M")

    # 프리미엄 보고서(구조화 JSON) — 헤드라인·빅뉴스·테마·종목상세·총평
    report = _gemini_report(indices, supply, movers, macro, news, date_str, market)

    result = {"asof": date_str, "date": time.strftime("%Y-%m-%d"), "market": market,
              "indices": indices, "movers": movers, "macro": macro, "supply": supply,
              "report": report}
    _CACHE[market] = (now, result)
    _save_briefing(result, market)
    return result
