"""이슈·어닝콜 카드 문구 자동 작성 — 사이트 방문자가 버튼으로 만들 때 (밸류AI).

흐름: 원문(미국은 8-K 보도자료) + 공시 숫자 '사실 목록' → AI(JSON) → **검증** → 통과한 문장만 사용
      AI가 없거나 실패하면 숫자 규칙으로 만든 기본판(rule_based)

검증 규칙 (히르찬이 직접 쓸 때와 같은 기준)
- 인용(quote): 원문에 글자 그대로 있어야 함 (따옴표 모양·띄어쓰기·대소문자 무시), 15단어 이하. 아니면 인용만 뺌
- 숫자: 글에 나온 숫자는 사실 목록이나 원문에 있는 숫자여야 함 (반올림 허용). 아니면 그 문장을 뺌
- 금지 표현: 단정·추천·자극 표현이 들어간 문장은 뺌 (인용 안은 예외)
- 부문 매출(미국): AI가 표에서 옮긴 숫자가 원문에 그대로 있고, 합계가 전사 매출과 2% 안일 때만 사용
llm_json(prompt) -> dict | None 은 밖에서 넣어 준다 (밸류AI: deepdive._gemini_json)
"""
from __future__ import annotations

import re

from render import money, pct

BANNED = ["최고", "무조건", "안전한", "확실", "사세요", "파세요", "매수", "매도", "폭락", "폭등",
          "대박", "쇼크", "추천", "강력", "반드시", "보장", "역대급", "어디까지", "날개", "미쳤", "폭증", "급등", "급락", "껑충", "떡상", "떡락"]
NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _norm(s: str) -> str:
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def _nums(text: str) -> list[float]:
    out = []
    for t in NUM.findall(text or ""):
        try:
            out.append(float(t.replace(",", "")))
        except ValueError:
            pass
    return out


class Checker:
    def __init__(self, facts_text: str, source_text: str):
        self.allowed = set(_nums(facts_text)) | set(_nums(source_text))
        self.src = _norm(source_text)

    def number_ok(self, t: float, text: str) -> bool:
        if t <= 12 and float(t).is_integer():   # '2분기 연속', '3가지', '1년' 같은 작은 정수
            return True
        if 2000 <= t <= 2100:                    # 연도
            return True
        for a in self.allowed:
            if abs(a - t) < 1e-9:
                return True
            if float(t).is_integer() and abs(a - t) < 0.5:          # 24.7 → 25
                return True
            if not float(t).is_integer() and abs(a - t) < 0.051:  # 24.66 → 24.7
                return True
            if a >= 1000 and abs(a / 100 - t) < 0.5:               # 백만 달러 30,709 → 307억$
                return True
        return False

    def text_ok(self, text: str) -> bool:
        if not text or not isinstance(text, str):
            return False
        if any(w in text for w in BANNED):
            return False
        return all(self.number_ok(t, text) for t in _nums(text))

    def quote_ok(self, q: str) -> bool:
        return bool(q) and len(q.split()) <= 15 and bool(self.src) and _norm(q) in self.src


# ---------- 사실 목록 ----------

def facts(data: dict) -> list[str]:
    qs, cur = data["quarters"], data["currency"]
    last = qs[-1]
    v, m = last["values"], last.get("m", {})
    out = []
    def add(s):  # noqa: E306
        out.append(s)
    if v.get("revenue") is not None:
        add(f"매출 {money(v['revenue'], cur)}" + (f", 전년 대비 {pct(m['revenue_yoy'])}" if m.get("revenue_yoy") is not None else ""))
    seq = [q.get("m", {}).get("revenue_yoy") for q in qs[-5:]]
    if all(x is not None for x in seq):
        add("매출 성장률(전년 대비) 최근 5분기: " + " → ".join(f"{x:.1f}%" for x in seq))
    if v.get("operating_income") is not None:
        add(f"영업이익 {money(v['operating_income'], cur)}" + (f", 전년 대비 {pct(m['operating_income_yoy'])}" if m.get("operating_income_yoy") is not None else ""))
    if m.get("opm") is not None:
        add(f"영업이익률 {m['opm']:.1f}%" + (f" (전년보다 {m['opm_yoy_pp']:+.1f}%p)" if m.get("opm_yoy_pp") is not None else ""))
    if m.get("gpm") is not None:
        add(f"매출총이익률 {m['gpm']:.1f}%" + (f" (전년보다 {m['gpm_yoy_pp']:+.1f}%p)" if m.get("gpm_yoy_pp") is not None else ""))
    if v.get("net_income") is not None:
        add(f"순이익 {money(v['net_income'], cur)}" + (f", 전년 대비 {pct(m['net_income_yoy'])}" if m.get("net_income_yoy") is not None else ""))
    if v.get("eps") is not None:
        add(f"희석 EPS {v['eps']:.2f}달러")
    for k, name in (("rnd", "연구개발비"), ("sales_marketing", "판매·마케팅비"), ("general_admin", "일반관리비"), ("sga", "판관비")):
        if v.get(k) is not None:
            add(f"{name} {money(v[k], cur)}" + (f", 전년 대비 {pct(m[k + '_yoy'])}" if m.get(k + "_yoy") is not None else ""))
    if v.get("operating_cash_flow") is not None:
        add(f"영업현금흐름 {money(v['operating_cash_flow'], cur)}")
    if v.get("capex") is not None:
        t = f"설비투자 {money(v['capex'], cur)}"
        if m.get("capex_yoy") is not None:
            t += f", 전년 대비 {pct(m['capex_yoy'])} ({1 + m['capex_yoy'] / 100:.1f}배)"
        add(t)
    if v.get("fcf") is not None:
        t = f"잉여현금흐름 {money(v['fcf'], cur)}"
        if len(qs) > 1 and qs[-2]["values"].get("fcf") is not None:
            t += f" (직전 분기 {money(qs[-2]['values']['fcf'], cur)})"
        add(t)
    for s in last.get("segments", []):
        t = f"부문 {s['name']}: 매출 {money(s.get('revenue'), cur)}"
        if s.get("yoy") is not None:
            t += f", 전년 대비 {pct(s['yoy'])}"
        if s.get("op") is not None:
            t += f", 영업이익 {money(s['op'], cur)}"
        add(t)
    pr = data.get("price_reaction")
    if pr and pr.get("close") and pr.get("after"):
        mv = (pr["after"] / pr["close"] - 1) * 100
        add(f"실적 발표 후 주가 {mv:+.1f}% ({pr['when']}: {pr['close']:,.2f} → {pr['after']:,.2f})")
    return out


# ---------- 기본판 (AI 없이) ----------

def _short(s: str, n: int) -> str:
    s = s.split(". ")[0].rstrip(".")
    return s if len(s) <= n else s[: n - 1] + "…"


def rule_based(data: dict, interp: dict) -> tuple[dict, dict]:
    qs, cur = data["quarters"], data["currency"]
    last = qs[-1]
    v, m = last["values"], last.get("m", {})
    name = data.get("name_display") or data.get("name_ko") or data.get("ticker")
    summary = []
    if m.get("revenue_yoy") is not None:
        summary.append({"tone": "positive" if m["revenue_yoy"] > 0 else "negative",
                        "text": f"매출 **{pct(m['revenue_yoy'])}**, {money(v['revenue'], cur)}"})
    if m.get("operating_income_yoy") is not None:
        summary.append({"tone": "positive" if m["operating_income_yoy"] > 0 else "negative",
                        "text": f"영업이익 **{pct(m['operating_income_yoy'])}**"})
    if m.get("opm") is not None:
        d = m.get("opm_yoy_pp")
        summary.append({"tone": "positive" if (d or 0) >= 0 else "caution",
                        "text": f"영업이익률 **{m['opm']:.1f}%**" + (f" ({d:+.1f}%p)" if d is not None else "")})
    if v.get("fcf") is not None:
        summary.append({"tone": "positive" if v["fcf"] >= 0 else "negative",
                        "text": f"잉여현금흐름 **{money(v['fcf'], cur)}**"})
    if m.get("capex_yoy") is not None and m["capex_yoy"] >= 30:
        summary.append({"tone": "caution", "text": f"설비투자 **{pct(m['capex_yoy'])}**"})
    pr = data.get("price_reaction")
    mv = (pr["after"] / pr["close"] - 1) * 100 if pr and pr.get("close") and pr.get("after") else None
    head = interp.get("headline") or "이번 분기 실적"
    title = head.split(",")[0].strip()
    sec_tone = {"pos": "positive", "neg": "negative", "mid": "neutral"}
    pick = [s for s in interp.get("sections", []) if mv is None or (s["tone"] == ("pos" if mv >= 0 else "neg"))]
    pick = (pick or interp.get("sections", []))[:3]
    story = {
        "title_accent": name, "title": title + ("인데 주가는?" if mv is not None and ((mv < 0) == ("증가" in title or "가속" in title or "개선" in title)) else ""),
        "subtitle": f"{name} {last['label']} 실적 · {head}",
        "summary": summary[:5], "sticker": _short(head, 20),
        "reaction": {"title": "그런데 주가는?" if mv is not None else "숫자로 본 이번 분기",
                     "reasons_title": ("숫자로 본 " + ("긍정" if mv >= 0 else "부담") + " 요인") if mv is not None else "눈여겨볼 3가지",
                     "reasons": [{"emoji": s["icon"], "title": s["title"],
                                  "lines": [_short(x, 30) for x in s["text"].split(". ")[:2] if x]} for s in pick]},
    }
    key = {"매출": ("매출", pct(m.get("revenue_yoy")) if m.get("revenue_yoy") is not None else None),
           "수익성": ("영업이익률", f"{m['opm']:.1f}%" if m.get("opm") is not None else None),
           "비용": ("비용", None),
           "순이익": ("순이익", money(v.get("net_income"), cur) if v.get("net_income") is not None else None),
           "현금흐름": ("잉여현금흐름", money(v.get("fcf"), cur) if v.get("fcf") is not None else None),
           "부문": ("부문", None)}
    points = []
    for s in interp.get("sections", []):
        if len(points) == 4:
            break
        label, num = key.get(s["title"], (s["title"], None))
        if s["title"] == "비용":
            g = NUM.findall(s["text"].split(")")[0])
            num = ("+" + g[-1] + "%") if g else None
        if s["title"] == "부문":
            mm = re.search(r"곳은 (.+?)\(([+\-][\d.,]+%)\)", s["text"])
            label, num = (mm.group(1), mm.group(2)) if mm else ("부문", None)
        points.append({"title": label, "number": num,
                       "tone": sec_tone.get(s["tone"], "neutral"), "detail": _short(s["text"], 60)})
    call = {"points": points, "one_liner": _short(head, 26), "source_kind": "공시 숫자 정리"}
    return story, call


# ---------- AI ----------

PROMPT = """너는 한국 재테크 크리에이터 '히르찬'의 실적 카드 작가야. 아래 [사실 목록]과 [원문]만 근거로 써.

규칙
- 말투: 친근하고 예의 바른 '~해요'체. 짧게. 어려운 용어는 쉬운 말로.
- 숫자는 [사실 목록]이나 [원문]에 있는 숫자만. 새로 계산하거나 지어내지 마.
- 단정·추천 표현 금지: 최고, 무조건, 확실, 안전한, 사세요/파세요, 매수/매도, 쇼크, 폭락 등.
- 좋은 점과 부담(나쁜 점)을 모두 담아.
- quote는 [원문]에 있는 영어 문장 일부를 **글자 그대로** 15단어 이내로. 없으면 빈 문자열. quote_ko는 그 번역.
- 원문에 경영진 발언이 없으면 quote는 모두 빈 문자열.
- summary와 reasons의 lines에는 **숫자를 꼭 하나 이상** 넣어. "성장세가 이어져요"처럼 숫자 없는 문장은 쓰지 마.
- 좋은 예 (알파벳 3분기): 제목 "클라우드 2배인데 주가는 왜?" / summary "매출 **+24.7%**, 5분기 연속 가속", "광고 성장 15.5→14.4→**10.6%**",
  "잉여현금흐름 **−91억$**" / reasons {{"title": "투자비 급증", "lines": ["분기 설비투자 514억$ (1년 전의 2.1배)", "잉여현금흐름 2분기 연속 마이너스"]}}
  / call point {{"title": "클라우드 매출 +103%", "number": "+103%", "detail": "부문 영업이익도 36억$ → 111억$, 3.1배로 늘었어요"}}
- 부담 요인이 정말 없으면 그 포인트는 tone "neutral"로 '다음에 지켜볼 점'을 써.
{price_rule}

JSON만 출력:
{{
 "story": {{
   "title": "카드 제목 14자 이내, 궁금증을 만드는 한 줄 (기업 이름 빼고)",
   "subtitle": "부제 30자 이내",
   "summary": [{{"tone": "positive|caution|negative", "text": "24자 이내, 핵심 숫자는 **굵게**"}}],   (5개)
   "sticker": "18자 이내 한 줄 요약",
   "reasons_title": "{reasons_title}",
   "reasons": [{{"emoji": "이모지 1개", "title": "8자 이내", "lines": ["28자 이내", "28자 이내"]}}]   (3개)
 }},
 "call": {{
   "points": [{{"title": "16자 이내", "tone": "positive|negative|neutral", "number": "큰 숫자 8자 이내",
               "detail": "45자 이내, number를 되풀이하지 말고 새 정보", "quote": "", "quote_ko": "", "speaker": "발언자 직함(한국어)"}}],   (4개)
   "one_liner": "20자 이내 한 줄 요약"
 }},
 "segments": [{{"name": "부문 한국어 이름", "current": 이번 분기 매출(원문 표 숫자 그대로), "prior": 전년 같은 분기 매출(원문 표 숫자 그대로)}}]
     (원문에 부문별 매출 표가 있을 때만. 없으면 빈 배열. 합계·헤지·소계 줄은 빼.)
}}

[기업] {name} · {label}
[사실 목록]
{facts}

[원문]
{source}
"""


def _clip(s, n):
    return isinstance(s, str) and 0 < len(s.replace("**", "")) <= n


def write(data: dict, interp: dict, source_text: str, llm_json) -> dict:
    """→ {"story": {...}, "call": {...}, "segments": [...], "ai": bool, "dropped": [...]}"""
    base_story, base_call = rule_based(data, interp)
    fl = facts(data)
    pr = data.get("price_reaction")
    mv = (pr["after"] / pr["close"] - 1) * 100 if pr and pr.get("close") and pr.get("after") else None
    out = {"story": base_story, "call": base_call, "segments": [], "ai": False, "dropped": []}
    if not llm_json:
        return out
    name = data.get("name_display") or data.get("name_ko") or data.get("ticker")
    prompt = PROMPT.format(
        name=name, label=data["quarters"][-1]["label"], facts="\n".join("- " + f for f in fl),
        source=(source_text or "(원문 없음 — 사실 목록만 사용)")[:16000],
        price_rule=(f"- 실적 발표 후 주가는 {mv:+.1f}% 움직였어. 실적과 주가가 반대 방향일 때만 '~인데 주가는 왜?' 질문형 제목을 써."
                    " 같은 방향이면(실적도 주가도 약함/강함) '왜?'라고 묻지 말고 이유를 짚는 제목을 써."
                    if mv is not None else "- 주가 반응 정보가 없으니 주가 이야기는 하지 마."),
        reasons_title=("숫자로 본 " + ("긍정" if (mv or 0) >= 0 else "부담") + " 요인 3가지") if mv is not None else "눈여겨볼 3가지")
    try:
        res = llm_json(prompt)
    except Exception:
        res = None
    if not isinstance(res, dict):
        return out
    ck = Checker("\n".join(fl), source_text or "")
    def nb(x):  # 굵게(**)는 이슈 카드 요약에서만 씀 → 나머지 칸에서는 지움  # noqa: E306
        if isinstance(x, str):
            return x.replace("**", "")
        if isinstance(x, list):
            return [nb(i) for i in x]
        if isinstance(x, dict):
            return {k: (v if k == "summary" else nb(v)) for k, v in x.items()}
        return x
    res = nb(res)
    drop = out["dropped"]

    st = res.get("story") or {}
    story = dict(base_story)
    if _clip(st.get("title"), 18) and ck.text_ok(st["title"]):
        story["title"] = st["title"]
    if _clip(st.get("subtitle"), 40) and ck.text_ok(st["subtitle"]):
        story["subtitle"] = st["subtitle"]
    for x in st.get("summary") or []:
        if isinstance(x, dict) and x.get("tone") == "neutral":
            x["tone"] = "caution"
    summ = [x for x in (st.get("summary") or []) if isinstance(x, dict)
            and x.get("tone") in ("positive", "caution", "negative") and _clip(x.get("text"), 30) and ck.text_ok(x["text"])
            and _nums(x["text"])]
    drop += [("요약", x.get("text")) for x in (st.get("summary") or []) if isinstance(x, dict) and x not in summ]
    if len(summ) >= 3:
        story["summary"] = summ[:5]
    if _clip(st.get("sticker"), 22) and ck.text_ok(st["sticker"]):
        story["sticker"] = st["sticker"]
    reasons = []
    for r in st.get("reasons") or []:
        lines = [ln for ln in (r.get("lines") or []) if _clip(ln, 32) and ck.text_ok(ln) and _nums(ln)]
        if _clip(r.get("title"), 10) and ck.text_ok(r["title"]) and lines:
            reasons.append({"emoji": (r.get("emoji") or "•")[:2], "title": r["title"], "lines": lines[:2]})
        else:
            drop.append(("이유", r.get("title")))
    if len(reasons) >= 2:
        story["reaction"] = dict(story["reaction"], reasons=reasons[:3],
                                 reasons_title=_clip(st.get("reasons_title"), 20) and ck.text_ok(st["reasons_title"])
                                 and st["reasons_title"] or story["reaction"]["reasons_title"])

    cl = res.get("call") or {}
    pts = []
    for p in cl.get("points") or []:
        if not (isinstance(p, dict) and p.get("tone") in ("positive", "negative", "neutral")
                and _clip(p.get("title"), 18) and ck.text_ok(p["title"])
                and _clip(p.get("detail"), 60) and ck.text_ok(p["detail"])):
            drop.append(("어닝콜", p.get("title") if isinstance(p, dict) else p))
            continue
        q = {"title": p["title"], "tone": p["tone"], "detail": p["detail"]}
        if _clip(p.get("number"), 10) and ck.text_ok(p["number"]):
            q["number"] = p["number"]
        if p.get("quote") and ck.quote_ok(p["quote"]):
            q["quote"] = p["quote"].strip()
            qk = p.get("quote_ko") or ""
            if qk and all(any(abs(a - t) < 0.5 for a in _nums(p["quote"])) for t in _nums(qk)) and not any(w in qk for w in BANNED[4:]):
                q["quote_ko"] = qk
            q["speaker"] = (p.get("speaker") or "경영진")[:20]
        elif p.get("quote"):
            drop.append(("인용(원문에 없음)", p["quote"][:40]))
        pts.append(q)
    # 숫자로 분명한 부담(매출·영업이익 감소, 현금 마이너스, 이익률 하락)이 있는데 AI가 뺐으면 규칙 포인트로 채움
    need_neg = [p for p in base_call["points"] if p["tone"] == "negative"]
    if pts and need_neg and not any(p["tone"] == "negative" for p in pts):
        pts = pts[:3] + [need_neg[0]]
        drop.append(("어닝콜", "부담 요인이 빠져 숫자 규칙 포인트로 채움"))
    tones = {p["tone"] for p in pts}
    if 3 <= len(pts) and "positive" in tones and ({"negative", "neutral"} & tones):
        out["call"] = {"points": pts[:4], "source_kind": "보도자료 발언" if any(p.get("quote") for p in pts) else "공시 숫자 정리",
                       "one_liner": cl["one_liner"] if _clip(cl.get("one_liner"), 26) and ck.text_ok(cl["one_liner"]) else base_call["one_liner"]}

    # 부문 매출 (원문 표 숫자 그대로 + 합계 확인)
    rev = data["quarters"][-1]["values"].get("revenue")
    segs = []
    for sgm in res.get("segments") or []:
        try:
            cur, pri = float(sgm["current"]), float(sgm["prior"])
        except (KeyError, TypeError, ValueError):
            continue
        fmt = lambda x: f"{x:,.0f}"  # noqa: E731
        if fmt(cur) in (source_text or "") and fmt(pri) in (source_text or "") and isinstance(sgm.get("name"), str) and ck.text_ok(sgm["name"]):
            segs.append({"name": sgm["name"][:12], "revenue": cur * 1e6, "prev": pri * 1e6})
    if segs and rev and abs(sum(s["revenue"] for s in segs) - rev) / rev <= 0.02:
        out["segments"] = segs
    elif segs:
        drop.append(("부문", "합계가 전사 매출과 맞지 않아 뺌"))
    out["story"], out["ai"] = story, True
    return out
