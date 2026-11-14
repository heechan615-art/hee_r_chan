"""✅ '직접 확인해 볼 것' 자동 확인 — 미국 종목 공시·실적발표 자료를 받아 항목별로 답한다.

출처 우선순위
  📄 공시 원문: 최신 10-Q/10-K, (최신이 10-Q면) 직전 10-K
  🎙️ 회사 발표: 최신 실적발표 8-K(Item 2.02)의 첨부(보도자료·CFO 코멘트·발표문 등 Exhibit 99.x)
  📰 기사: 구글 뉴스 제목(보조, 본문 없음)
문서 전체를 넣지 않고 항목별 키워드로 관련 문단만 골라 LLM(Claude)에 준다.
검증: 인용은 발췌에 글자 그대로 있어야(아니면 인용만 뺌), 답의 숫자는 발췌·facts에 있어야(아니면 그 문장 뺌).
"""
import re
import html
import json
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

import per_hist
import valuation_ai

SYSTEM = """너는 개인투자자에게 기업 공시를 읽어 주는 금융 교육자 "히르찬"의 해설 도우미다.
'확인 항목'마다 아래 '원문 발췌'만 근거로 답한다.

[절대 규칙]
1. 발췌에 없는 사실·숫자를 쓰지 않는다. 계산해서 새 숫자를 만들지 않는다. 금액은 원문 표기(예: $31.0 billion, $130-145 billion)를 쓰되, 표의 백만 달러 단위 숫자는 $116,316 million → $116.3B처럼 B 단위로 바꿔 써도 된다(자릿수만 이동, 반올림 소수 1자리).
   질문에 적힌 금액이 발췌의 다른 기간(예: 9개월 누계) 숫자와 다르면 기간 차이를 분명히 말한다.
2. 답을 못 찾으면 status를 "찾지 못함"으로 하고, 무엇이 없었는지와 어디서 더 볼 수 있는지(예: 실적발표 컨퍼런스콜)를 1문장으로 쓴다. 추측으로 채우지 않는다.
3. 발췌가 질문의 일부만 답하면 "일부 확인".
4. quote는 발췌에서 글자 그대로 복사한 영어 원문 한 문장(또는 그 앞부분), 25단어 이하. 긴 문장은 앞부분만 잘라 써도 된다. 마땅한 문장이 없으면 빈 문자열.
5. 📰 기사(N)는 제목뿐이라 그것만으로는 "확인됨"을 줄 수 없다(최대 "일부 확인").
6. 해요체, 쉬운 말, 항목당 2~3문장. 매수·매도 권유 금지. 회사 설명은 '회사는 ~라고 설명해요'처럼 회사의 주장으로 전한다.

[출력: JSON만, 코드블록 없이]
{"items":[{"n":1,"status":"확인됨|일부 확인|찾지 못함","answer":"...","source":"D1","quote":"..."}],
 "summary":"세 항목을 종합한 한 줄(40자 내외)"}"""

# 확인 항목(한국어)·플래그 → 영어 검색어
KW_TEXT = [
    (("설비투자", "유형자산", "capex", "데이터센터"), ("capital expenditures", "purchases of property and equipment",
                                              "property and equipment", "data center", "capex", "infrastructure")),
    (("세율", "법인세", "세금"), ("effective tax rate", "income tax", "tax benefit", "provision for income taxes", "tax expense")),
    (("매각", "처분", "리프랜차이즈", "보틀링"), ("divestiture", "refranchis", "proceeds from disposals", "disposals of businesses", "investing activities", "sale of", "bottling operations", "gain on sale", "gain on the sale")),
    (("인수",), ("acquisition", "acquired", "business combination", "purchase price", "acquisitions, net of cash acquired", "completed the acquisition")),
    (("영업외", "기타수익", "기타 수익", "투자 이익", "지분", "평가이익", "평가 이익"),
     ("other income", "gains on equity securities", "unrealized gain", "non-operating", "nonoperating", "equity method")),
    (("자사주",), ("repurchase", "buyback", "share repurchases")),
    (("배당",), ("dividend",)),
    (("영업현금흐름", "현금흐름", "fcf", "잉여현금"), ("cash provided by operating activities", "operating activities",
                                                "free cash flow", "working capital")),
    (("일회성", "지급"), ("payment", "one-time", "contingent consideration", "deposit", "settlement", "litigation")),
    (("매출총이익", "마진", "이익률"), ("gross margin", "operating margin", "margin")),
    (("주식보상",), ("stock-based compensation", "share-based compensation")),
    (("eps", "주당"), ("earnings per share", "diluted")),
    (("부문", "제품", "서비스", "세그먼트"), ("segment", "products", "services")),
    (("감가상각",), ("depreciation", "amortization")),
    (("매출",), ("net revenues", "revenue", "net sales")),
    (("비용",), ("costs and expenses", "operating expenses", "restructuring", "severance")),
    (("계획", "전망", "가이던스", "내년", "올해"), ("outlook", "expect", "anticipate", "guidance", "full year", "forecast")),
    (("구조조정",), ("restructuring", "severance", "impairment")),
    (("부채", "차입"), ("debt", "borrowings", "notes")),
]
KW_FLAG = {
    "heavy_capex": ("capital expenditures", "purchases of property and equipment", "data center"),
    "tax_anomaly": ("effective tax rate", "income tax", "tax benefit"),
    "one_off_gain": ("other income", "gains on equity securities", "unrealized gain"),
    "fcf_anomaly": ("operating activities", "free cash flow", "working capital"),
    "negative_fcf": ("free cash flow", "capital expenditures"),
    "revenue_down_eps_up": ("divestiture", "refranchising", "acquisitions and divestitures"),
    "margin_regime_change": ("gross margin", "operating margin"),
}
KIND = {"filing": "📄 공시 원문", "release": "🎙️ 회사 발표", "news": "📰 기사"}


def html_to_text(s):
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
    s = re.sub(r"<ix:header>.*?</ix:header>", "", s, flags=re.S | re.I)
    s = re.sub(r"</(p|div|tr|br|li|h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<td[^>]*>", " | ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"(\s*\|\s*)+", " | ", s)
    s = re.sub(r"\$ \| ", "$", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def _doc_url(cik, acc, name):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{name}"


def gather(sym):
    """문서 목록 [{id, kind, title, url, text}]. 미국 종목만."""
    cik = per_hist._cik(sym)
    if not cik:
        raise ValueError("SEC에서 이 종목을 찾지 못했어요(미국 상장 종목만 지원).")
    r = per_hist.sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()["filings"]["recent"]
    n = len(r["form"])
    docs = []

    # 📄 최신 정기보고서(10-Q/10-K) + 최신이 10-Q면 직전 10-K
    periodic = [i for i in range(n) if r["form"][i] in ("10-Q", "10-K")]
    pick = periodic[:1]
    if pick and r["form"][pick[0]] == "10-Q":
        k = next((i for i in periodic if r["form"][i] == "10-K"), None)
        if k is not None:
            pick.append(k)
    for i in pick:
        url = _doc_url(cik, r["accessionNumber"][i], r["primaryDocument"][i])
        try:
            t = html_to_text(per_hist.sec_get(url, timeout=40).text)
        except Exception:
            continue
        per = r.get("reportDate", [""] * n)[i]
        docs.append({"kind": "filing", "title": f"{r['form'][i]} ({per} 기준, 제출 {r['filingDate'][i]})",
                     "url": url, "text": t, "date": r["filingDate"][i]})

    # 🎙️ 최신 실적발표 8-K 첨부(Exhibit 99.x) — 보도자료·CFO 코멘트·발표문
    e8 = next((i for i in range(n) if r["form"][i] == "8-K" and "2.02" in (r.get("items", [""] * n)[i] or "")), None)
    if e8 is not None:
        acc = r["accessionNumber"][e8]
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
        try:
            items = per_hist.sec_get(base + "index.json").json()["directory"]["item"]
        except Exception:
            items = []
        prim = r["primaryDocument"][e8]
        names = [it["name"] for it in items if it["name"].lower().endswith((".htm", ".html"))
                 and it["name"] != prim and not re.fullmatch(r"R\d+\.htm", it["name"])
                 and "index" not in it["name"].lower()]
        names.sort(key=lambda x: (0 if re.search(r"ex[-_]?99|exhibit[-_]?99|99[-_]?\d|pr\.htm|press", x, re.I) else 1, x))
        for nm in names[:3]:
            try:
                t = html_to_text(per_hist.sec_get(base + nm).text)
            except Exception:
                continue
            if len(t) < 800:
                continue
            docs.append({"kind": "release", "title": f"실적발표 자료 {nm} (제출 {r['filingDate'][e8]})",
                         "url": base + nm, "text": t, "date": r["filingDate"][e8]})
    for k, d in enumerate(docs, 1):
        d["id"] = f"D{k}"
    return docs


def news(name, sym, n=6):
    """📰 최근 90일 실적·컨퍼런스콜 기사 제목(구글 뉴스 RSS)."""
    q = f'"{name}" OR {sym} earnings call when:90d'
    try:
        r = requests.get("https://news.google.com/rss/search", timeout=12, headers={"User-Agent": "Mozilla/5.0"},
                         params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        out = []
        for k, it in enumerate(list(ET.fromstring(r.content).iter("item"))[:n], 1):
            src = it.find("source")
            try:
                d = parsedate_to_datetime(it.findtext("pubDate")).strftime("%Y-%m-%d")
            except Exception:
                d = ""
            t = re.sub(r"\s+-\s+[^-]+$", "", it.findtext("title") or "").strip()
            out.append({"id": f"N{k}", "kind": "news", "title": f"{t} — {src.text if src is not None else ''} {d}".strip(),
                        "url": it.findtext("link") or "", "text": t, "date": d})
        return out
    except Exception:
        return []


def _chunks(text, size=900):
    out, cur = [], ""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(cur) + len(line) > size and cur:
            out.append(cur)
            cur = ""
        cur += line + "\n"
        while len(cur) > size * 2:          # 아주 긴 줄(줄바꿈 없는 본문)
            out.append(cur[:size])
            cur = cur[size:]
    if cur:
        out.append(cur)
    return out


APP_ITEM = ("카드에서", "밴드 카드", "화면에서", "패널에서")   # 앱 화면 안에서 보는 항목 → 공시 검색 안 함


def is_app_item(item):
    return any(k in item for k in APP_ITEM)


def keywords(item, flags):
    """항목 문장에서 검색어. 문장에서 못 뽑으면 그때만 경고 플래그 검색어."""
    low = item.lower()
    kws = []
    for ks, en in KW_TEXT:
        if any(k in low for k in ks):
            kws += en
    if not kws:
        for fid in flags:
            kws += KW_FLAG.get(fid, ())
    seen = []
    for k in kws:
        if k not in seen:
            seen.append(k)
    return seen


def select(docs, item, flags, per_item=8):
    """항목별 관련 문단 상위 per_item개 [(doc_id, chunk)]."""
    kws = keywords(item, flags)
    if not kws:
        return []
    scored = []
    for d in docs:
        if d["kind"] == "news":
            continue
        boost = 1.15 if d["kind"] == "release" else 1.0     # 회사 설명(보도자료)이 더 직접적일 때가 많음
        for c in _chunks(d["text"]):
            lc = c.lower()
            hit = [k for k in kws if k in lc]
            if not hit:
                continue
            # 서로 다른 검색어가 많이 나올수록(여러 단어 구문은 2배), 같은 단어 반복은 조금만
            s = sum(2 if " " in k else 1 for k in hit) + 0.2 * sum(min(lc.count(k), 3) for k in hit)
            if re.search(r"\d", c):
                s += 0.5
            if c.count("|") > 15:               # 숫자 표 위주 문단은 설명 문장보다 뒤로
                s *= 0.6
            scored.append((s * boost, d["id"], c))
    scored.sort(key=lambda x: -x[0])
    out, per_doc = [], {}
    for s, did, c in scored:
        if per_doc.get(did, 0) >= 4:            # 한 문서에 몰리지 않게
            continue
        out.append((did, c))
        per_doc[did] = per_doc.get(did, 0) + 1
        if len(out) >= per_item:
            break
    return out


def _norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-").replace("|", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def _allowed_nums(text):
    ok = set()
    for t in valuation_ai._NUM.findall(text):
        try:
            v = abs(float(t.replace(",", "").replace("−", "-")))
        except ValueError:
            continue
        for x in (v, v / 1000, v / 1e6, v * 1000):     # 백만$ ↔ 십억$ 표기 변환 허용
            for dgt in (0, 1, 2):
                ok.add(round(x, dgt))
    return ok


def check(sym, name, checklist, facts):
    """반환 {items:[{q,status,answer,source,quote,doc}], summary, docs:[{id,kind,title,url}], cost_usd, usage}."""
    docs = gather(sym)
    nw = news(name or sym, sym)
    flags = [f.get("id") for f in (facts or {}).get("flags", [])]
    blocks, ctx_text = [], ""
    for k, q in enumerate(checklist, 1):
        if is_app_item(q):
            blocks.append(f"### 확인 항목 {k}: (앱 화면에서 확인하는 항목 — 답하지 말고 status '찾지 못함')")
            continue
        sel = select(docs, q, flags)
        part = "\n".join(f"[{did}] {c.strip()}" for did, c in sel) or "(관련 문단 없음)"
        blocks.append(f"### 확인 항목 {k}: {q}\n{part}")
        ctx_text += part + "\n"
    head = "\n".join(f"{d['id']} = {KIND[d['kind']]} · {d['title']}" for d in docs)
    news_txt = "\n".join(f"{x['id']} = 📰 {x['title']}" for x in nw) or "(기사 없음)"
    ctx_text += news_txt
    user = (f"회사: {name} ({sym})\n\n[문서 목록]\n{head}\n\n[기사 제목]\n{news_txt}\n\n[원문 발췌]\n"
            + "\n\n".join(blocks) + "\n\n위 확인 항목마다 JSON으로 답해.")
    valuation_ai._LAST_USAGE.clear()
    out = None
    for _ in range(2):
        try:
            o = valuation_ai._claude(SYSTEM, user)
        except Exception as e:
            print(f"[filing_check] Claude 실패: {repr(e)[:200]}")
            o = None
        if isinstance(o, dict) and isinstance(o.get("items"), list):
            out = o
            break
    if out is None:
        raise RuntimeError("AI 응답을 받지 못했어요.")

    # 검증
    ok = _allowed_nums(ctx_text) | valuation_ai._allowed(facts or {})
    norm_ctx = _norm(ctx_text)
    by_id = {d["id"]: d for d in docs + nw}
    items, removed = [], 0
    for k, q in enumerate(checklist, 1):
        if is_app_item(q):
            items.append({"q": q, "status": "앱에서 확인", "answer": "이 항목은 위 카드(화면)에서 바로 볼 수 있어요.",
                          "quote": "", "source": None})
            continue
        it = next((x for x in out["items"] if isinstance(x, dict) and x.get("n") == k), None) \
            or (out["items"][k - 1] if k - 1 < len(out["items"]) and isinstance(out["items"][k - 1], dict) else {})
        st = it.get("status") if it.get("status") in ("확인됨", "일부 확인", "찾지 못함") else "찾지 못함"
        ans = str(it.get("answer") or "").strip()
        parts = re.split(r"(?<=[.!?요다])\s+", ans)
        keep = [p for p in parts if not valuation_ai._bad_numbers(p, ok)]
        removed += len(parts) - len(keep)
        ans = " ".join(keep)
        quote = str(it.get("quote") or "").strip().strip('"')
        if quote and (_norm(quote) not in norm_ctx or len(quote.split()) > 40):
            quote, removed = "", removed + 1
        src = str(it.get("source") or "").strip()
        doc = by_id.get(src)
        if doc and doc["kind"] == "news" and st == "확인됨":
            st = "일부 확인"
        if not ans:
            st, ans = "찾지 못함", "가져온 공시·발표 자료에서 근거 문장을 찾지 못했어요."
        items.append({"q": q, "status": st, "answer": ans, "quote": quote,
                      "source": ({"id": doc["id"], "kind": KIND[doc["kind"]], "title": doc["title"], "url": doc["url"]}
                                 if doc else None)})
    summary = str(out.get("summary") or "").strip()
    if valuation_ai._bad_numbers(summary, ok):
        summary = ""
    return {"items": items, "summary": summary, "removed": removed,
            "docs": [{"id": d["id"], "kind": KIND[d["kind"]], "title": d["title"], "url": d["url"]} for d in docs],
            "news_n": len(nw), "provider": valuation_ai.CLAUDE_MODEL,
            "usage": valuation_ai._LAST_USAGE.get("usage"), "cost_usd": valuation_ai._LAST_USAGE.get("total")}
