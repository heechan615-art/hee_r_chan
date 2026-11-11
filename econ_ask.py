"""경제지표 해석 탭 💬 질문하기
해석 글(static/econ/bundle.json) + 구글 뉴스 최근 기사 제목 → Gemini가 답(마크다운).
Gemini 구글 검색 연결(grounding)은 이 키의 무료 한도가 0이라, 검색어만 Gemini가 뽑고 기사는 구글 뉴스 RSS에서 직접 모은다.
"""
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

import requests

import deepdive

BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "econ", "bundle.json")
_B = {"mt": 0, "data": None}


def _report(rid):
    mt = os.path.getmtime(BUNDLE)
    if _B["mt"] != mt:
        with open(BUNDLE, encoding="utf-8") as f:
            _B["data"], _B["mt"] = json.load(f), mt
    return next((r for r in _B["data"].get("reports", []) if r["meta"].get("id") == rid), None)


def _plain(md, n):
    """그래프·브리핑 블록을 빼고 글자 수 제한"""
    md = re.sub(r"```(chart|briefing)[\s\S]*?```", "", md or "")
    md = re.sub(r"<!--[\s\S]*?-->", "", md)
    return md.strip()[:n]


def _news(q, lang):
    hl, gl = ("ko", "KR") if lang == "ko" else ("en-US", "US")
    try:
        r = requests.get("https://news.google.com/rss/search", timeout=15, headers={"User-Agent": "Mozilla/5.0"},
                         params={"q": q + " when:30d", "hl": hl, "gl": gl, "ceid": f"{gl}:{hl.split('-')[0]}"})
        out = []
        for it in list(ET.fromstring(r.content).iter("item"))[:6]:
            src = it.find("source")
            try:
                d = parsedate_to_datetime(it.findtext("pubDate")).strftime("%Y-%m-%d")
            except Exception:
                d = ""
            t = re.sub(r"\s+-\s+[^-]+$", "", it.findtext("title") or "").strip()   # 끝의 ' - 언론사' 떼기
            out.append({"d": d, "t": t, "src": src.text if src is not None else "", "url": it.findtext("link") or ""})
        return out
    except Exception:
        return []


def _gemini_text(prompt, max_tokens=4096):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    for attempt in range(2):
        try:
            r = requests.post(deepdive._URL, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json={"contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.35 + attempt * 0.05,
                                                         "thinkingConfig": {"thinkingLevel": "low"}}}, timeout=90)
            if r.status_code == 200:
                t = "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"].get("parts") or []).strip()
                if t:
                    return t
        except Exception:
            pass
    return None


def ask(rid, q, history=None):
    r = _report(rid)
    if not r:
        return {"error": "해석 글을 찾지 못했어요."}
    m = r["meta"]
    hist = [h for h in (history or []) if isinstance(h, dict) and h.get("q") and h.get("a")][-3:]
    htxt = "\n".join(f"- 앞선 질문: {str(h['q'])[:500]}\n  앞선 답: {str(h['a'])[:1200]}" for h in hist)
    today = time.strftime("%Y-%m-%d")
    # 1) 검색어 뽑기
    qs = deepdive._gemini_json(
        f"오늘은 {today}. 경제지표 해석 글 '{m.get('title', '')}'(기준 {m.get('period', '')})을 읽은 사람이 이렇게 물었어.\n질문: {q}\n"
        + (f"앞선 대화:\n{htxt}\n" if htxt else "")
        + "이 질문에 답하려면 확인해야 할 최근 뉴스 검색어를 뽑아 줘. 질문 속 사건(유가, 관세, 정책, 선거, 연준 등)과 그 지표 항목의 최근 흐름 위주. "
          '영어 검색어 2~3개(미국 뉴스용, 3~5단어 짧은 키워드, 연도·CPI 같은 군더더기 없이 사건 위주. 예: oil prices fall, China tariff truce extended)와 한국어 검색어 1~2개. JSON으로만: {"queries":[{"q":"검색어","lang":"en|ko"}]} '
          "최근 뉴스가 전혀 필요 없는 질문(용어 뜻, 글 안의 숫자 확인 등)이면 {\"queries\":[]}.",
        max_tokens=400, temp=0.2, tries=2) or {}
    queries = [x for x in (qs.get("queries") or []) if isinstance(x, dict) and x.get("q")][:4]
    news, seen = [], set()
    with ThreadPoolExecutor(4) as ex:
        for got in ex.map(lambda x: _news(str(x["q"])[:80], x.get("lang")), queries):
            for n in got:
                k = n["t"].lower()[:60]
                if k not in seen:
                    seen.add(k)
                    news.append(n)
    news = news[:20]
    ntxt = "\n".join(f"[{i + 1}] {n['d']} {n['src']}: {n['t']}" for i, n in enumerate(news)) or "(찾은 뉴스 없음)"
    # 2) 답 쓰기
    prompt = f"""너는 경제를 쉽게 풀어 주는 재테크 강사야. 오늘은 {today}.
아래 경제지표 해석 글을 읽은 사람이 질문했어. 해석 글 + 최근 뉴스 제목 목록 + 일반 경제 원리(가격 전가 경로, 시차, 기저효과 등)로 답해.
최근 사건·숫자는 해석 글과 뉴스 목록에 있는 것만 쓰고, 경제 원리로 설명하는 부분은 '일반적으로'처럼 원리라는 걸 알 수 있게 써.

질문: {q}
{('앞선 대화(이어지는 질문이면 참고):' + chr(10) + htxt) if htxt else ''}

[해석 글] {m.get('title', '')} / 기준 {m.get('period', '')} / 발표 {m.get('release', '')} / 다음 발표 {m.get('next', '')}
한 줄 결론: {m.get('conclusion', '')}
{_plain(r.get('body'), 24000)}
{('[추가 자료로 본 추가 해석]' + chr(10) + _plain(r.get('extra'), 8000)) if r.get('extra') else ''}

[최근 뉴스 제목] (번호로 인용)
{ntxt}

답 형식(마크다운만 출력):
**짧은 답** — 2~3문장으로 질문에 바로 답.
### 해석 글에서 보이는 근거
- 해석 글 속 숫자와 함께 2~4줄
### 최근 뉴스로 확인한 것
- 질문과 관련된 뉴스를 골라 사실마다 끝에 [번호]. 목록에 관련 뉴스가 정말 하나도 없을 때만 '관련 최근 뉴스를 찾지 못했어요'라고 써
### 그래서 어떻게 볼까
- 가능성 · 그렇게 되려면 필요한 조건 · 반대로 갈 위험, 시차가 있으면 대략 얼마나 걸리는지
### 다음에 확인할 지표
- 1~3개

규칙: 질문의 전제(예: '유가가 내리고 있다', '관세를 연장했다')가 뉴스로 확인되면 확인됐다고, 확인 안 되면 확인 못 했다고 솔직히 써. 숫자는 해석 글 그대로, 계산·추정은 '(계산)', '(추정)' 표시, 지어내지 마.
친근한 존댓말(~해요), 짧은 문장, 어려운 용어는 괄호로 풀이. '무조건·확실·반드시' 같은 단정과 매수·매도 권유 금지."""
    ans = _gemini_text(prompt)
    if not ans:
        return {"error": "답을 만들지 못했어요. 잠시 뒤 다시 물어봐 주세요."}
    ans = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", ans.strip())
    cite = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")   # [3] 또는 [2, 4, 13] → 번호마다 기사 링크
    ok = lambda k: 0 < k <= len(news)  # noqa: E731
    used = sorted({int(k) for g in cite.findall(ans) for k in g.split(",") if ok(int(k))})
    ans = cite.sub(lambda mm: "".join(f"[[{k}]]({news[k - 1]['url']})" for k in map(int, mm.group(1).split(",")) if ok(k))
                   or mm.group(0), ans)
    return {"answer": ans, "q": q, "at": time.strftime("%Y-%m-%d %H:%M"),
            "sources": [dict(news[i - 1], n=i) for i in used], "queries": [x["q"] for x in queries]}
