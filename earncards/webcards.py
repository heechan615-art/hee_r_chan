"""밸류AI(웹)용 — 검색한 기업의 실적 카드 HTML + 해석을 바로 만든다.

PNG는 서버에서 만들지 않는다(크롬 엔진이 무거움). 카드 HTML을 브라우저 iframe에 그리고,
품질 점검·자동 보정(qc.QC_JS)도 브라우저에서 돌린다. 다운로드는 브라우저에서 PNG로 바꿈.

webcards.build("GOOGL") → {name, ticker, market, target, banner, views: [최근 분기, 그 전 분기]}
- target: 오늘 기준 '나왔어야 할' 분기(직전 달력 분기). 공시가 없으면 banner 로 '미발표' 안내
- inputs/{티커}_{분기}.yaml 이 있으면 반영(부문·발표 자료 숫자)
- 폰트 주소는 '__FONT_BASE__' 자리표시 → 브라우저가 자기 주소로 바꿔 넣는다
"""
from __future__ import annotations

import calendar
import re
from datetime import date

import aiwrite
import flow
import interpret
import metrics
import qc
import render
from collectors import dart, manual, sec

FONT_TOKEN = "__FONT_BASE__"


def expected_quarter(today: date | None = None) -> str:
    t = today or date.today()
    done = (t.month - 1) // 3
    return f"{t.year}Q{done}" if done else f"{t.year - 1}Q4"


def _qend(q: str) -> date:
    y, n = int(q[:4]), int(q[-1])
    return date(y, n * 3, calendar.monthrange(y, n * 3)[1])


def _qname(data, q: str) -> str:
    if data["market"] == "US" and data.get("fiscal_year_end_month", 12) != 12:
        return sec.quarter_label(_qend(q), data["fiscal_year_end_month"])
    return f"{q[:4]}년 {q[-1]}분기"


def _web_html(html: str) -> str:
    js = ("<script>" + qc.QC_JS + ";document.fonts.ready.then(()=>{try{__qc.fix()}catch(e){}"
          "document.body.dataset.ready='1';parent.postMessage({type:'ec-ready'},'*')})</script>")
    return html.replace("</body>", js + "</body>")


def build(code: str, today: date | None = None) -> dict:
    is_kr = bool(re.fullmatch(r"\d{6}", code))
    target = expected_quarter(today)
    data = (dart if is_kr else sec).collect(code, target, n=12)
    man = manual.load(data["ticker"], target)
    if man:
        manual.merge(data, man, target)
    data["quarters"] = [q for q in data["quarters"] if q["calendar_quarter"] <= target]
    metrics.enrich(data)
    qs = data["quarters"]
    latest = qs[-1]["calendar_quarter"]

    banner = None
    if latest != target:
        shown = " · ".join(render.qtitle(q) for q in qs[-2:][::-1])
        banner = {"kind": "pending", "title": f"{_qname(data, target)} 실적 미발표",
                  "text": f"아직 {_qname(data, target)} 실적이 공시되지 않아 가장 최근 {shown} 실적으로 보여 드려요."}
        k8 = data.get("latest_8k")
        if k8 and k8["filed"] > _qend(target).isoformat():
            banner = {"kind": "released", "title": f"{_qname(data, target)} 실적 발표됨 · 정기보고서 반영 전",
                      "text": (f"{k8['filed']}에 실적을 발표했지만 아직 정기보고서(10-Q)에 숫자가 반영되지 않았어요."
                               f" 반영 전까지는 {shown} 실적으로 보여 드려요."),
                      "link": k8["url"], "link_text": "발표 공시(8-K) 보기"}
        prov = data.get("provisional") or []
        if prov:
            p = prov[0]
            d = f"{p['date'][:4]}-{p['date'][4:6]}-{p['date'][6:]}"
            banner = {"kind": "released", "title": f"{_qname(data, target)} 잠정실적 발표됨 · 분기보고서 반영 전",
                      "text": (f"{d}에 잠정실적을 공시했지만 아직 분기보고서에 반영되지 않았어요."
                               f" 반영 전까지는 {shown} 실적으로 보여 드려요."),
                      "link": p["url"], "link_text": "잠정실적 공시 보기"}

    render.FONT_URL = FONT_TOKEN
    try:
        views = []
        for k in range(2):  # 최근 분기, 그 전 분기
            sub = qs[: len(qs) - k]
            if len(sub) < 2:
                break
            d2 = dict(data, quarters=sub, requested_quarter=sub[-1]["calendar_quarter"])
            views.append({
                "quarter": sub[-1]["calendar_quarter"], "label": render.qtitle(sub[-1]),
                "status": sub[-1].get("status"),
                "cards": [
                    {"kind": "metrics", "title": "핵심지표", "w": 1080, "h": 1080,
                     "html": _web_html(render.build_metrics_html(d2, "1080x1080"))},
                    {"kind": "flow", "title": "돈의 흐름", "w": 1080, "h": 1080,
                     "html": _web_html(flow.build_html(d2, "1080x1080"))},
                ],
                "interpretation": interpret.build(d2),
                "source": render.source_text(d2),
            })
    finally:
        render.FONT_URL = None

    name, color = render.brand(data)
    return {"name": name, "color": color, "ticker": data["ticker"], "market": data["market"],
            "target": target, "target_label": _qname(data, target), "banner": banner, "views": views}


# ---------- 방문자가 버튼으로 만드는 이슈·어닝콜 카드 ----------

def price_reaction(symbol: str, event: str, after_close: bool = True) -> dict | None:
    """실적 발표 전후 종가. 미국(장 마감 뒤 발표): 발표일 종가 → 다음 거래일 종가.
    한국(장중·장 전 공시): 전 거래일 종가 → 발표일 종가. 야후가 막히면 None."""
    import time as _t
    try:
        try:
            from curl_cffi import requests as rq
            get = lambda u: rq.get(u, impersonate="chrome", timeout=15)  # noqa: E731
        except ImportError:
            import requests as rq
            get = lambda u: rq.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)  # noqa: E731
        r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1y")
        res = r.json()["chart"]["result"][0]
        rows = [(_t.strftime("%Y-%m-%d", _t.gmtime(t + res["meta"].get("gmtoffset", 0))), c)
                for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c]
    except Exception:
        return None
    if after_close:
        before = [r for r in rows if r[0] <= event]
        after = [r for r in rows if r[0] > event]
    else:
        before = [r for r in rows if r[0] < event]
        after = [r for r in rows if r[0] >= event]
    if not before or not after:
        return None
    b, a = before[-1], after[0]
    return {"close": round(b[1], 2), "after": round(a[1], 2),
            "when": f"{b[0][5:].replace('-', '/')} 종가 → {a[0][5:].replace('-', '/')} 종가",
            "source": "Yahoo Finance 일별 종가"}


def build_extra(code: str, quarter: str, symbol: str | None, llm_json=None) -> dict:
    """이슈·어닝콜 카드 HTML + 정리 문구. quarter 는 화면에서 보고 있는 분기."""
    import call as callmod
    import story as storymod
    from collectors import release
    is_kr = bool(re.fullmatch(r"\d{6}", code))
    data = (dart if is_kr else sec).collect(code, quarter, n=12)
    man = manual.load(data["ticker"], quarter)
    if man:
        manual.merge(data, man, quarter)
    data["quarters"] = [q for q in data["quarters"] if q["calendar_quarter"] <= quarter]
    if data["quarters"][-1]["calendar_quarter"] != quarter:
        raise ValueError(f"{quarter} 숫자가 아직 없어요.")
    metrics.enrich(data)
    name, color = render.brand(data)
    data["name_display"] = name

    # 원문 (미국: 그 분기 실적 발표 보도자료)
    src_text, src_name, event = "", None, None
    if not is_kr:
        try:
            p = release.fetch(data["ticker"], quarter, period_end=data["quarters"][-1].get("end"))
            raw = p.read_text()
            m = re.search(r"# 제출일: (\d{4}-\d{2}-\d{2})", raw)
            event = m.group(1) if m else None
            src_text = raw
            src_name = f"{name} 실적 발표 보도자료(SEC 8-K{', ' + event if event else ''})"
        except Exception:
            pass
    else:
        lim = (_qend(quarter).toordinal() + 75)
        prov = [f for f in dart.provisional_filings(data["corp_code"], _qend(quarter))
                if date(int(f["date"][:4]), int(f["date"][4:6]), int(f["date"][6:])).toordinal() <= lim]
        if prov:
            d = min(f["date"] for f in prov)
            event = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    if not data.get("price_reaction") and symbol and event:
        pr = price_reaction(symbol, event, after_close=not is_kr)
        if pr:
            data["price_reaction"] = pr

    interp = interpret.build(data)
    out = aiwrite.write(data, interp, src_text, llm_json)
    last = data["quarters"][-1]
    if out["segments"] and not last.get("segments"):
        last["segments"] = out["segments"]
        metrics.enrich(data)
    # 이슈 카드 추세 차트: 매출 성장률 vs 영업이익 성장률 (부문 이력이 없어도 그릴 수 있게)
    sy = data.setdefault("series_yoy", {})
    for key, nm in (("revenue_yoy", "매출 성장률"), ("operating_income_yoy", "영업이익 성장률")):
        sy[nm] = {q["calendar_quarter"]: q["m"][key] for q in data["quarters"] if q.get("m", {}).get(key) is not None}
    st = dict(out["story"])
    st["trend"] = {"title": "매출 vs 영업이익 성장률", "quarters": 5,
                   "series": [{"name": "매출 성장률", "label": "매출", "color": color},
                              {"name": "영업이익 성장률", "label": "영업이익", "color": "#9AA0A6"}]}
    srcs = " · ".join(x for x in [src_name, "SEC EDGAR" if not is_kr else "OpenDART",
                                  (data.get("price_reaction") or {}).get("source")] if x)
    st["sources"] = srcs + (" · 문구: AI 작성 후 숫자·인용 자동 검증" if out["ai"] else " · 문구: 공시 숫자 규칙 정리")

    # 어닝콜 카드의 원문 대조용 파일 (call.originals 가 calls/ 에서 찾음)
    if src_text:
        (callmod.ROOT / "calls").mkdir(exist_ok=True)
    render.FONT_URL = FONT_TOKEN
    try:
        cards = [{"kind": "story", "title": "이슈", "w": 1080, "h": 1080,
                  "html": _web_html(storymod.build_html(data, st, "1080x1080"))},
                 {"kind": "call", "title": "어닝콜" if out["call"]["source_kind"] == "보도자료 발언" else "핵심 정리",
                  "w": 1080, "h": 1080, "html": _web_html(callmod.build_html(data, out["call"], "1080x1080"))}]
    finally:
        render.FONT_URL = None
    curated = {"call": out["call"]["points"], "call_kind": out["call"]["source_kind"],
               "reasons": st["reaction"]["reasons"], "reaction_title": st["reaction"]["reasons_title"],
               "summary": [s["text"].replace("**", "") for s in st["summary"]]}
    return {"quarter": quarter, "cards": cards, "curated": curated, "headline": f"{name} {st['title']}",
            "one_liner": out["call"].get("one_liner"), "ai": out["ai"], "dropped": out["dropped"],
            "price_reaction": data.get("price_reaction")}
