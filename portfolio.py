"""
내 계좌 비중 탭 — 서버 쪽 재료.
====================================
계좌·종목·매매 기록은 방문자 브라우저(localStorage)에만 저장한다(로그인 시스템이 멈춰 있어 서버에 개인 자산을 두지 않음).
서버는 종목 찾기·현재가·배당/실적 일정·이슈만 준다.

1) resolve(q)          검색어 → {sym(야후 표기), code, name(한글 우선), market, currency, price}
2) quotes(syms)        현재가: 국내 네이버 실시간(polling), 미국 야후 차트 + 원/달러 환율
3) info(sym)           배당(배당락일·지급일·연 배당금, 지난 패턴으로 다음 날짜 예상), 다음 실적발표일,
                       지난 실적 해석(실적 카드 모듈 webcards), 국내 IR 개최 공시 일정
4) issues(sym, name)   최근 뉴스(미국 Finnhub 30일, 국내 네이버 뉴스 + DART 공시) → AI가 지난 이슈·다가올 일정을
                       호재/악재/중립으로 정리. 출처(기사 번호)가 없거나 숫자가 원문에 없으면 뺌.
                       (구글 검색 붙인 Gemini는 이 키로 막혀 있어(429) 뉴스·공시에 나온 것만 다룸)
"""
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import requests

import kr_data

UA = {"User-Agent": "Mozilla/5.0"}
UA_M = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}
KST = timezone(timedelta(hours=9))
EARNCARDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "earncards")
BANNED = ["최고", "무조건", "안전한", "확실", "사세요", "파세요", "매수 추천", "매도 추천", "폭락", "폭등",
          "대박", "쇼크", "추천", "강력", "반드시", "보장", "역대급", "폭증", "급등", "급락", "껑충", "떡상", "떡락"]
_Q = {}          # 현재가 캐시 {sym: (시각, dict)}


def _ec():
    if EARNCARDS not in sys.path:
        sys.path.insert(0, EARNCARDS)


def _is_kr(sym):
    return bool(re.fullmatch(r"\d{6}\.(KS|KQ)", sym or ""))


def _naver_ac(q):
    try:
        return requests.get("https://ac.stock.naver.com/ac", params={"q": q, "target": "stock"},
                            headers=UA, timeout=6).json().get("items", [])
    except Exception:
        return []


# ---------------- 1) 종목 찾기 ----------------
def resolve(q):
    yf, code6, name = kr_data.resolve_query(q)
    if not yf:
        return None
    if code6:
        out = {"sym": yf, "code": code6, "name": name or code6, "market": "KR", "currency": "KRW"}
    else:
        tk = yf.upper()
        ko = None
        for it in _naver_ac(q if not re.fullmatch(r"[A-Za-z.\-]{1,6}", q) else tk):
            if it.get("nationCode") == "USA" and re.sub(r"[ .]", "-", it.get("code") or "") == tk:
                ko = re.sub(r"\s*(Class [A-Z]|보통주)$", "", it.get("name") or "")
                break
        out = {"sym": tk, "code": tk, "name": ko or tk, "market": "US", "currency": "USD"}
    q_ = quotes([out["sym"]])["quotes"].get(out["sym"])
    if not q_ or not q_.get("price"):
        return None
    out["price"] = q_["price"]
    if out["market"] == "US" and out["name"] == out["sym"] and q_.get("name"):
        out["name"] = q_["name"]
    if out["market"] == "KR" and q_.get("name"):
        out["name"] = q_["name"]
    return out


# ---------------- 2) 현재가 ----------------
def _kr_quotes(codes):
    out = {}
    for i in range(0, len(codes), 20):
        part = codes[i:i + 20]
        try:
            r = requests.get("https://polling.finance.naver.com/api/realtime/domestic/stock/" + ",".join(part),
                             headers=UA, timeout=8).json()
        except Exception:
            continue
        for d in r.get("datas", []):
            try:
                p = float(str(d.get("closePrice")).replace(",", ""))
                ch = float(str(d.get("compareToPreviousClosePrice")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            out[d["itemCode"]] = {"price": p, "prev": p - ch, "chg_pct": float(d.get("fluctuationsRatio") or 0),
                                  "open": d.get("marketStatus") == "OPEN", "name": d.get("stockName"),
                                  "at": d.get("localTradedAt")}
    return out


def _yahoo_quote(sym):
    from curl_cffi import requests as cr
    try:
        j = cr.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                   params={"range": "1d", "interval": "5m"}, impersonate="chrome", timeout=10).json()
        m = j["chart"]["result"][0]["meta"]
    except Exception:
        return None
    p, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
    if not p:
        return None
    t = m.get("regularMarketTime")
    per = (m.get("currentTradingPeriod") or {}).get("regular") or {}
    return {"price": p, "prev": prev, "chg_pct": (p / prev - 1) * 100 if prev else 0,
            "open": bool(per and per.get("start", 0) <= time.time() <= per.get("end", 0)),
            "name": m.get("longName") or m.get("shortName"),
            "at": datetime.fromtimestamp(t, KST).isoformat() if t else None}


def quotes(syms):
    """{quotes: {sym: {price, prev, chg_pct, open, at}}, fx: 원/달러}. 같은 종목 20초 캐시."""
    now = time.time()
    syms = [s for s in dict.fromkeys(s.strip() for s in syms) if s][:80]
    need = [s for s in syms + ["KRW=X"] if not (s in _Q and now - _Q[s][0] < 20)]
    kr = [s for s in need if _is_kr(s)]
    us = [s for s in need if not _is_kr(s)]
    if kr:
        got = _kr_quotes([s[:6] for s in kr])
        for s in kr:
            if s[:6] in got:
                _Q[s] = (now, got[s[:6]])
    if us:
        with ThreadPoolExecutor(8) as ex:
            for s, q in zip(us, ex.map(_yahoo_quote, us)):
                if q:
                    _Q[s] = (now, q)
    fx = (_Q.get("KRW=X") or (0, {}))[1].get("price")
    return {"quotes": {s: _Q[s][1] for s in syms if s in _Q}, "fx": fx, "time": datetime.now(KST).isoformat()}


_FX = {}


def fx_on(d):
    """그날(없으면 직전 거래일) 원/달러 종가. 오늘이면 실시간 환율."""
    if d >= date.today().isoformat():
        return quotes([])["fx"]
    if d in _FX:
        return _FX[d]
    from curl_cffi import requests as cr
    t = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
    try:
        j = cr.get("https://query1.finance.yahoo.com/v8/finance/chart/KRW=X",
                   params={"period1": int((t - timedelta(days=10)).timestamp()), "period2": int((t + timedelta(days=1)).timestamp()),
                           "interval": "1d"}, impersonate="chrome", timeout=10).json()
        r = j["chart"]["result"][0]
        rows = [(datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), c)
                for ts, c in zip(r.get("timestamp") or [], r["indicators"]["quote"][0].get("close") or []) if c]
        rows = [x for x in rows if x[0] <= d]
        v = round(rows[-1][1], 2) if rows else None
    except Exception:
        v = None
    if v:
        _FX[d] = v
    return v


# ---------------- 3) 배당·실적 일정 ----------------
def _d(ts):
    try:
        return datetime.fromtimestamp(int(ts), KST).date() if ts else None
    except Exception:
        return None


def _dividend(tk, info, is_kr):
    """연 배당금·배당락일·지급일. 확정 날짜가 지났으면 지난 지급 간격으로 다음 날짜를 '예상'."""
    try:
        hist = tk.dividends
        hist = [(i.date(), float(v)) for i, v in hist.items()] if hist is not None else []
    except Exception:
        hist = []
    today = date.today()
    last_year = [x for x in hist if x[0] > today - timedelta(days=370)]
    # 최근 1년 합계와 야후 연 배당금 중 큰 값 (국내는 야후 기록이 한 번씩 늦게 들어와 합계가 모자람)
    annual = max(sum(v for _, v in last_year), info.get("dividendRate") or 0)
    if not annual and not hist:
        return None
    freq = len(last_year) or None
    ex = _d(info.get("exDividendDate"))
    if hist and (not ex or hist[-1][0] > ex):
        ex = hist[-1][0]
    pay = _d(info.get("dividendDate"))
    est = False
    if ex and ex < today and freq:
        # 작년 같은 시기 배당락일 + 1년 (야후 기록이 한두 번 늦게 들어오는 국내 종목도 맞게)
        cand = [d.replace(year=d.year + 1) for d, _ in hist
                if d.month != 2 or d.day != 29]
        cand = [d for d in cand if d >= today]
        if cand:
            nxt = min(cand)
        else:
            step = timedelta(days=round(365 / freq))
            nxt = ex
            while nxt < today:
                nxt += step
        ex, est = nxt, True
        pay = None if not pay or pay < today else pay
    per = hist[-1][1] if hist else (info.get("lastDividendValue") or None)
    return {"annual": round(annual, 4), "per": per, "freq": freq,
            "yield": info.get("dividendYield"), "next_ex": ex.isoformat() if ex else None,
            "next_ex_est": est, "pay": pay.isoformat() if pay and pay >= today else None,
            "stale": bool(hist and hist[-1][0] < today - timedelta(days=400))}


def _kr_ir(code6):
    """국내: 앞으로 열릴 기업설명회(IR) 공시 → [{date, title, url}]"""
    _ec()
    try:
        from collectors import dart
        import ecal
        corp, _ = dart.stock_to_corp(code6)
        bgn = date.today() - timedelta(days=45)
        data = dart._get("list.json", corp_code=corp, bgn_de=bgn.strftime("%Y%m%d"),
                         end_de=date.today().strftime("%Y%m%d"), page_count="100").json()
    except Exception:
        return []
    out = []
    for r in data.get("list", []) if data.get("status") == "000" else []:
        if "기업설명회" not in r.get("report_nm", ""):
            continue
        doc = ecal._ir_doc(r["rcept_no"])
        if doc and doc.get("date") and doc["date"] >= date.today().isoformat():
            tx = doc.get("text") or ""
            out.append({"date": doc["date"], "kind": "IR",
                        "title": ("실적발표 IR" if "실적" in tx else "기업설명회(IR)") + (f" {doc['time']}" if doc.get("time") else ""),
                        "detail": tx[:80], "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}"})
    return out


def _last_earnings(code):
    """실적 카드 모듈의 해석 → {label, headline, lines, banner}. ETF 등 실적이 없으면 None."""
    _ec()
    try:
        import webcards
        b = webcards.build(code)
    except Exception:
        return None
    v = (b.get("views") or [None])[0]
    if not v:
        return None
    it = v.get("interpretation") or {}
    return {"label": v.get("label"), "quarter": v.get("quarter"), "headline": it.get("headline"),
            "lines": [f"{s['title']}: {s['text']}" for s in (it.get("sections") or [])[:3]],
            "banner": (b.get("banner") or {}).get("title"), "source": v.get("source")}


def info(sym):
    import yfsess
    is_kr = _is_kr(sym)
    tk = yfsess.ticker(sym)
    try:
        inf = tk.info or {}
    except Exception:
        inf = {}
    etf = (inf.get("quoteType") == "ETF") or bool(re.search(r"KODEX|TIGER|ACE|SOL|RISE|KBSTAR|HANARO|PLUS|ARIRANG|ETF",
                                                           inf.get("longName") or inf.get("shortName") or ""))
    today = date.today()
    # 다음 실적발표일: 미국은 야후(확정/예상 표시), 국내는 야후 예상치(공시 전엔 늘 '예상')
    nxt = None
    if not etf:
        for k in ("earningsTimestampStart", "earningsTimestamp", "earningsCallTimestampStart"):
            d = _d(inf.get(k))
            if d and d >= today:
                nxt = d
                break
    earn = {"next": nxt.isoformat() if nxt else None,
            "est": bool(is_kr or inf.get("isEarningsDateEstimate", True))} if nxt else None
    with ThreadPoolExecutor(2) as ex:
        f_last = ex.submit(_last_earnings, sym[:6] if is_kr else sym) if not etf else None
        f_ir = ex.submit(_kr_ir, sym[:6]) if is_kr and not etf else None
        last = f_last.result() if f_last else None
        irs = f_ir.result() if f_ir else []
    div = _dividend(tk, inf, is_kr)
    events = []
    if earn:
        events.append({"date": earn["next"], "kind": "실적", "title": "실적 발표" + (" (예상일)" if earn["est"] else ""),
                       "tone": "변수"})
    for e in irs:
        if earn and e["date"] == earn["next"]:   # 실적발표 IR 공시가 나오면 예상일 → 확정
            events[0].update(title=e["title"], url=e["url"])
            earn["est"] = False
        else:
            events.append(dict(e, tone="변수"))
    if div and div.get("next_ex"):
        events.append({"date": div["next_ex"], "kind": "배당", "title": "배당락일" + (" (예상)" if div["next_ex_est"] else ""),
                       "tone": "일정"})
    if div and div.get("pay"):
        events.append({"date": div["pay"], "kind": "배당", "title": "배당금 지급일", "tone": "일정"})
    events.sort(key=lambda e: e["date"])
    return {"sym": sym, "etf": etf, "dividend": div, "earnings": earn, "last": last, "events": events,
            "sector": inf.get("sector"), "time": datetime.now(KST).isoformat()}


# ---------------- 4) 이슈 (AI) ----------------
def _news_us(sym):
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return []
    try:
        r = requests.get("https://finnhub.io/api/v1/company-news",
                         params={"symbol": sym, "from": (date.today() - timedelta(days=30)).isoformat(),
                                 "to": date.today().isoformat(), "token": key}, timeout=10).json()
    except Exception:
        return []
    out, seen = [], set()
    for it in r if isinstance(r, list) else []:
        h = (it.get("headline") or "").strip()
        if not h or h.lower() in seen:
            continue
        seen.add(h.lower())
        out.append({"date": _d(it.get("datetime")).isoformat() if it.get("datetime") else None, "title": h,
                    "body": (it.get("summary") or "")[:300], "src": it.get("source"), "url": it.get("url")})
    return out[:40]


def _news_kr(code6):
    import html as _html
    out = []
    try:
        r = requests.get(f"https://m.stock.naver.com/api/news/stock/{code6}",
                         params={"pageSize": 30, "page": 1}, headers=UA_M, timeout=8).json()
        for grp in r if isinstance(r, list) else []:
            for it in grp.get("items", []):
                t = re.sub(r"<[^>]+>", "", _html.unescape(it.get("titleFull") or it.get("title") or "")).strip()
                dt = it.get("datetime") or ""
                out.append({"date": f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}" if len(dt) >= 8 else None, "title": t,
                            "body": re.sub(r"<[^>]+>", "", _html.unescape(it.get("body") or ""))[:300],
                            "src": it.get("officeName"), "url": it.get("mobileNewsUrl")})
    except Exception:
        pass
    # DART 주요 공시(공급계약·증자·소송 등)도 이슈 재료로
    _ec()
    try:
        from collectors import dart
        corp, _ = dart.stock_to_corp(code6)
        d = dart._get("list.json", corp_code=corp, bgn_de=(date.today() - timedelta(days=45)).strftime("%Y%m%d"),
                      end_de=date.today().strftime("%Y%m%d"), page_count="40").json()
        for x in d.get("list", []) if d.get("status") == "000" else []:
            nm = x.get("report_nm", "").strip()
            if re.search(r"임원|소유상황|대량보유|주식등의|기업설명회|자기주식취득결과|증권발행실적|일괄신고", nm):
                continue
            out.append({"date": f"{x['rcept_dt'][:4]}-{x['rcept_dt'][4:6]}-{x['rcept_dt'][6:]}", "title": "[공시] " + nm,
                        "body": "", "src": "DART", "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x['rcept_no']}"})
    except Exception:
        pass
    return out[:45]


def _nums(s):
    return [n.replace(",", "") for n in re.findall(r"\d+(?:[.,]\d+)*", s or "") if len(n.replace(",", "").replace(".", "")) >= 2]


def issues(sym, name, llm_json=None):
    """{recent: [...], upcoming: [...], news: [...], ai: bool}. AI가 없거나 실패하면 기사 목록만."""
    is_kr = _is_kr(sym)
    news = _news_kr(sym[:6]) if is_kr else _news_us(sym)
    news = [n for n in news if n.get("title")]
    news.sort(key=lambda n: n.get("date") or "", reverse=True)
    out = {"recent": [], "upcoming": [], "news": news[:12], "ai": False, "dropped": 0}
    if not news or not llm_json:
        return out
    today = date.today().isoformat()
    lines = "\n".join(f"[{i}] {n['date']} | {n['src']} | {n['title']}" + (f" — {n['body'][:220]}" if n.get("body") else "")
                      for i, n in enumerate(news))
    prompt = (
        f"오늘은 {today}. 너는 개인 투자자에게 보유 종목 소식을 쉽게 알려주는 도우미야. 종목: {name} ({sym}).\n"
        f"아래는 최근 기사·공시 목록이야 (번호가 출처):\n{lines}\n\n"
        "이 목록만 근거로 아래 JSON을 만들어. 마크다운 금지.\n"
        "{\n"
        '  "recent": [ {"title":"18자 이내 핵심", "detail":"무슨 일이고 왜 중요한지 쉬운 말 70자 이내, 해요체", '
        '"tone":"호재|악재|중립", "ids":[출처 번호]} ],\n'
        '  "upcoming": [ {"date":"YYYY-MM-DD 또는 YYYY-MM", "title":"18자 이내", "detail":"70자 이내, 해요체", '
        '"tone":"호재|악재|중립|변수", "ids":[출처 번호]} ]\n'
        "}\n"
        "규칙:\n"
        f"- recent: 이 회사에 직접 관련된 지난 일 3~6개. 같은 사건 기사는 하나로 묶어. 다른 회사 이야기·일반 시장 뉴스·기념일·인사말·사회공헌 같은 홍보성 기사는 빼.\n"
        f"- upcoming: 기사에 '앞으로 있을 일정'이 날짜와 함께 나온 것만({today} 이후). 예: 투자자의 날, 신제품 발표, 공장 가동, 규제 결정, 소송 판결. "
        "날짜가 기사에 없으면 넣지 마. 없으면 빈 배열.\n"
        "- 실적발표일·배당락일은 따로 챙기니 upcoming에 넣지 마.\n"
        "- tone: 회사 실적·주가에 도움이 될 일은 호재, 부담이 될 일은 악재, 애매하면 중립. 결과를 모르는 행사는 변수.\n"
        "- 숫자는 기사에 나온 것만. 지어내지 마. 영어 기사도 한국어로.\n"
        "- 매수·매도 권유, '확실', '무조건', '폭등', '폭락' 같은 단정·과장 표현 금지.")
    rep = llm_json(prompt, max_tokens=3072, temp=0.3, tries=2) if llm_json else None
    if not isinstance(rep, dict):
        return out
    dropped = 0

    def ok(x, upcoming):
        nonlocal dropped
        ids = [i for i in (x.get("ids") or []) if isinstance(i, int) and 0 <= i < len(news)]
        t, dt = (x.get("title") or "").strip(), (x.get("detail") or "").strip()
        tone = x.get("tone")
        src = " ".join(news[i]["title"] + " " + (news[i].get("body") or "") for i in ids).replace(",", "")
        bad = (not ids or not t or len(t) > 30 or len(dt) > 120
               or tone not in ("호재", "악재", "중립", "변수")
               or any(w in t + dt for w in BANNED)
               or any(n not in src for n in _nums(t + " " + dt) if not (upcoming and n in (x.get("date") or ""))))
        if upcoming and not bad:
            d = str(x.get("date") or "")
            bad = not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", d) or d < today[:len(d)]
        if bad:
            dropped += 1
            return None
        item = {"title": t, "detail": dt, "tone": tone if (upcoming or tone != "변수") else "중립",
                "src": [{"title": news[i]["title"], "url": news[i].get("url"), "date": news[i].get("date"),
                         "by": news[i].get("src")} for i in ids[:3]],
                "date": x.get("date") if upcoming else max((news[i].get("date") or "") for i in ids)}
        return item

    out["recent"] = [y for y in (ok(x, False) for x in (rep.get("recent") or [])[:7] if isinstance(x, dict)) if y]
    out["upcoming"] = [y for y in (ok(x, True) for x in (rep.get("upcoming") or [])[:6] if isinstance(x, dict)) if y]
    out["recent"].sort(key=lambda z: z["date"] or "", reverse=True)
    out["upcoming"].sort(key=lambda z: z["date"])
    out["ai"], out["dropped"] = True, dropped
    return out
