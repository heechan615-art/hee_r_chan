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


def _us_index(tk, name):
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
            "kospi_up": _yahoo_screener("day_gainers", 6),       # 급등
            "kosdaq_up": [],
            "kospi_val": _yahoo_screener("most_actives", 6),     # 거래활발(주도주)
            "kospi_down": _yahoo_screener("day_losers", 4),      # 급락
        }
    return {
        "kospi_up": _naver_rank("up", "KOSPI", 6),
        "kosdaq_up": _naver_rank("up", "KOSDAQ", 6),
        "kospi_val": _naver_rank("marketValue", "KOSPI", 6),
        "kospi_down": _naver_rank("down", "KOSPI", 4),
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
    date_str = time.strftime("%Y-%m-%d %H:%M")
    up_lbl = "급등" if market == "US" else "코스피 급등"
    val_lbl = "거래 활발(주도주)" if market == "US" else "코스피 거래대금 상위"
    down_lbl = "급락" if market == "US" else "코스피 급락"
    lines = ["[지수]"]
    for i in indices:
        if i["price"] is not None:
            lines.append(f"  {i['name']}: {i['price']} ({i['chg']:+.2f}%)")
    lines.append(f"[{up_lbl}]")
    for s in movers["kospi_up"]:
        lines.append(f"  {s['name']} +{s['chg']}%")
    if movers["kosdaq_up"]:
        lines.append("[코스닥 급등]")
        for s in movers["kosdaq_up"]:
            lines.append(f"  {s['name']} +{s['chg']}%")
    lines.append(f"[{val_lbl}]")
    for s in movers["kospi_val"]:
        lines.append(f"  {s['name']} ({s['chg']:+}%)")
    lines.append(f"[{down_lbl}]")
    for s in movers["kospi_down"]:
        lines.append(f"  {s['name']} {s['chg']}%")
    m = macro
    if market == "US":
        lines.append(f"[매크로] VIX {m.get('vix')}, WTI유가 {m.get('wti')}달러, 환율 {m.get('usdkrw')}원")
    else:
        lines.append(f"[매크로] 환율 {m.get('usdkrw')}원, WTI유가 {m.get('wti')}달러, "
                     f"VIX {m.get('vix')}, VKOSPI {m.get('vkospi')}")
    ai = _gemini_brief("\n".join(lines), date_str, market)
    issues = _gemini_market_issues(get_market_issues(movers, market), indices, market)
    result = {"asof": date_str, "date": time.strftime("%Y-%m-%d"), "market": market,
              "indices": indices, "movers": movers,
              "macro": macro, "ai": ai, "bignews": issues}
    _CACHE[market] = (now, result)
    _save_briefing(result, market)
    return result
