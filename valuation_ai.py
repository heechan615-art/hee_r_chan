"""🧠 AI 종합 해석 — 2단계: LLM 서술.

규칙 엔진(valuation_rules)의 facts만 LLM에 주고 문장만 쓰게 한다.
- ANTHROPIC_API_KEY가 있으면 Claude(기본 claude-sonnet-5-5, ANTHROPIC_MODEL로 변경), 없으면 기존 Gemini(deepdive)
- 응답 JSON이 깨지면 1회 재시도, 그래도 실패하면 valuation_rules.template_text(템플릿 문장)
- 입력에 없는 숫자가 들어간 문장은 지운다(숫자 검증)
퓨샷 예시는 prompts/valuation_examples.json (직접 고칠 수 있음).
"""
import os
import re
import json

import deepdive
import valuation_rules

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, "prompts", "valuation_examples.json")
CLAUDE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

SYSTEM = """너는 개인투자자에게 기업 밸류에이션 지표를 해석해 주는 금융 교육자 "히르찬"의 해설 도우미다.

[절대 규칙]
1. 입력 JSON에 있는 숫자만 사용한다. 새 숫자를 계산하거나 지어내지 않는다. 숫자를 인용할 땐 입력값 그대로(반올림 표기만 허용).
2. 회사의 구체적 사건(인수, 소송, 신제품, 매각 등)은 입력 플래그의 evidence에 근거가 있을 때만 언급한다. 근거가 없으면 "~일 가능성이 있어요, 현금흐름표/공시로 확인해 보세요"처럼 가능성으로만 말한다.
3. 판정(싸다/비싸다 등)은 입력의 verdict를 따른다. 뒤집지 않는다.
4. 매수·매도 권유, 목표주가 제시, 수익 보장 표현을 하지 않는다.
5. 해요체, 쉬운 말. 전문용어는 처음 나올 때 한 번 풀어 쓴다. 과장·감탄사 금지.
6. 숫자 사이의 모순과 착시를 찾는 것이 핵심이다. 숫자를 단순 나열하지 말고 "그래서 무슨 뜻인지"를 말한다.

[출력 형식: JSON]
{
  "one_line": "한 줄 결론 (40자 내외)",
  "cheap_reasons": ["싸다는 근거", ...],        // 최대 3개, 없으면 빈 배열
  "expensive_reasons": ["비싸다/조심할 근거", ...], // 최대 3개
  "illusions": [                                // 착시·주의점, 플래그 기반, 최대 3개
    {"title": "짧은 제목", "body": "2~3문장 설명"}
  ],
  "metric_advice": "이 기업은 어떤 지표로 봐야 하는지와 이유 (2~3문장)",
  "key_question": "결론을 가르는 핵심 질문 1개",
  "checklist": ["직접 확인해 볼 것", ...],       // 최대 3개, 구체적으로(어느 재무제표의 어느 항목)
  "lesson": "강의용 한 줄 교훈 (예: 좋은 회사 ≠ 좋은 가격)"
}"""

GUIDE = """[입력 facts 읽는 법]
- verdicts: valuation(밸류에이션 위치)·quality(이익의 질)·cash(현금 창출)·growth(매출 성장 방향). 이 네 판정을 넘어서는 결론을 내지 않는다.
- flags: 규칙 엔진이 찾은 진단. level alert > warn > info. evidence의 숫자와 hint를 근거로 쓴다.
- recommend: 이 기업에 맞는 1순위·보조 지표와 이유. metric_advice는 이것을 풀어 쓴다.
- metrics의 *_panel 값은 화면 위 카드(야후) 숫자, 나머지 마진은 최근 12개월 공시(SEC) 숫자다. 둘이 다르면 기준 차이를 설명할 수 있다.
- peg.matrix: PER × EPS 성장률 조합별 PEG. distorted=true는 왜곡(일회성 이익·기저효과) 조합이다.
- psr_bands: 전체·5년·3년 PSR 평균·σ 위치(z)·백분위(pctl)·평균 회귀 시 등락률(back_pct). rev_growth_phases의 '자료 첫 3년'은 공시 자료가 시작된 시기(적힌 기간)이지 '직전 3년'이 아니다.
- 금액은 입력에 적힌 통화 표기(예: $3.6B, 475,221억원)를 그대로 쓴다.
아래 예시처럼 facts를 읽고 출력 JSON 하나만 쓴다. 마크다운 코드블록 없이 JSON만."""


def compact(f):
    """LLM 입력용 facts(토큰 절약: PEG 매트릭스는 한 줄씩)."""
    pg = f.get("peg") or {}
    rows = []
    for m in pg.get("matrix") or []:
        rows.append(f'{m["basis_label"]} {m["per"]} ÷ {m["g_label"]} {m["g"]}% = '
                    + (f'{m["peg"]}' if m["peg"] is not None else "계산 안 함")
                    + (f' ({m["note"]})' if m.get("note") else "")
                    + (" [권장 짝]" if m.get("paired") else "") + (" [왜곡]" if m.get("distorted") else ""))
    rec = pg.get("recommended")
    return {
        "기업": f.get("name"), "티커": f.get("ticker"), "업종": f.get("sector"), "세부업종": f.get("industry"),
        "업종 유형": f.get("biz_type"), "기준일": f.get("asof"), "재무 출처": f.get("fin_source"),
        "metrics": f.get("metrics"),
        "peg": {"matrix": rows, "min": pg.get("min"), "max": pg.get("max"), "yahoo_5y": pg.get("yahoo_5y"),
                "recommended": (f'{rec["basis_label"]} ÷ {rec["g_label"]} = {rec["peg"]}' if rec else None),
                "normalized": pg.get("normalized")},
        "psr_bands": f.get("psr_bands"),
        "flags": [{k: x[k] for k in ("id", "level", "title", "evidence", "hint")} for x in f.get("flags") or []],
        "recommend": {k: (f.get("recommend") or {}).get(k) for k in ("primary", "secondary", "reason")},
        "verdicts": f.get("verdicts"),
    }


def _examples():
    try:
        with open(EXAMPLES, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return []


def build_prompt(facts):
    """(system, user) — system은 종목과 무관해 캐시된다."""
    ex = _examples()
    shots = "\n\n".join(f"### 예시 {i + 1}: {e.get('ticker', '')}\n[facts]\n{json.dumps(e['facts'], ensure_ascii=False)}\n"
                        f"[출력]\n{json.dumps(e['output'], ensure_ascii=False)}" for i, e in enumerate(ex))
    system = SYSTEM + "\n\n" + GUIDE + ("\n\n" + shots if shots else "")
    user = "[facts]\n" + json.dumps(compact(facts), ensure_ascii=False) + "\n\n[출력]"
    return system, user


# ───────── 숫자 검증: 입력에 없는 숫자가 든 문장은 지운다 ─────────
_NUM = re.compile(r"(?<![\w.])[-+−]?\d[\d,]*(?:\.\d+)?")


def _allowed(facts):
    s = json.dumps(compact(facts), ensure_ascii=False)
    ok = set()
    for t in _NUM.findall(s):
        try:
            v = abs(float(t.replace(",", "").replace("−", "-")))
        except ValueError:
            continue
        for d in (0, 1, 2):
            ok.add(round(v, d))
        ok.add(float(int(v)))
    return ok


def _bad_numbers(text, ok):
    bad = []
    for t in _NUM.findall(text):
        try:
            v = abs(float(t.replace(",", "").replace("−", "-")))
        except ValueError:
            continue
        if v <= 10 and float(v).is_integer():      # 1순위·2σ·3가지 같은 작은 정수
            continue
        if 1990 <= v <= 2100:                       # 연도
            continue
        if v in (40.0, 100.0):                      # Rule of 40, 백분율 기준
            continue
        if not any(abs(v - o) <= max(0.051, o * 0.006) for o in ok):
            bad.append(t)
    return bad


def _clean(out, facts):
    """형식 정리 + 숫자 검증. 반환 (out, 지운 문장 수)."""
    ok = _allowed(facts)
    removed = 0

    def fix_str(s):
        nonlocal removed
        s = str(s or "").strip()
        if not _bad_numbers(s, ok):
            return s
        parts = re.split(r"(?<=[.!?요다])\s+", s)
        keep = [p for p in parts if not _bad_numbers(p, ok)]
        removed += len(parts) - len(keep)
        return " ".join(keep)

    def fix_list(xs, n):
        nonlocal removed
        res = []
        for x in (xs or [])[:n]:
            if isinstance(x, str) and x.strip():
                if _bad_numbers(x, ok):
                    removed += 1
                else:
                    res.append(x.strip())
        return res
    res = {
        "one_line": fix_str(out.get("one_line")),
        "cheap_reasons": fix_list(out.get("cheap_reasons"), 3),
        "expensive_reasons": fix_list(out.get("expensive_reasons"), 3),
        "illusions": [], "metric_advice": fix_str(out.get("metric_advice")),
        "key_question": fix_str(out.get("key_question")),
        "checklist": fix_list(out.get("checklist"), 3), "lesson": fix_str(out.get("lesson")),
    }
    for it in (out.get("illusions") or [])[:3]:
        if isinstance(it, dict) and it.get("title"):
            b = fix_str(it.get("body"))
            if b:
                res["illusions"].append({"title": fix_str(it["title"]) or "주의", "body": b})
    return res, removed


def _valid(o):
    return isinstance(o, dict) and isinstance(o.get("one_line"), str) and o["one_line"].strip() \
        and isinstance(o.get("metric_advice"), str)


# ───────── 공급자 ─────────
# 100만 토큰당 달러 (claude-sonnet-5-5: 입력 2, 출력 10, 캐시 쓰기 1.25배, 캐시 읽기 0.1배)
PRICE = {"in": 2.0, "out": 10.0, "cache_write": 2.5, "cache_read": 0.2}
_LAST_USAGE = {}


def _claude(system, user):
    import anthropic
    client = anthropic.Anthropic()
    r = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=8000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium"})
    u = r.usage
    use = {"in": u.input_tokens or 0, "out": u.output_tokens or 0,
           "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
           "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0}
    cost = sum(use[k] * PRICE[k] for k in use) / 1e6
    _LAST_USAGE["usage"], _LAST_USAGE["cost"] = use, round(cost, 4)
    _LAST_USAGE["total"] = round(_LAST_USAGE.get("total", 0) + cost, 4)
    if r.stop_reason == "refusal":
        return None
    return deepdive._parse_json_loose("".join(b.text for b in r.content if b.type == "text"))


def _gemini(system, user):
    return deepdive._gemini_json(system + "\n\n" + user, max_tokens=4096, temp=0.3, tries=1)


def provider():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return CLAUDE_MODEL
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini:" + deepdive.MODEL
    return None


def narrate(facts):
    """반환 {text, provider, removed, fallback(bool)}."""
    prov = provider()
    system, user = build_prompt(facts)
    out = None
    _LAST_USAGE.clear()
    if prov:
        call = _claude if prov == CLAUDE_MODEL else _gemini
        for attempt in range(2):           # 파싱 실패·형식 불량이면 1회 재시도
            try:
                o = call(system, user)
            except Exception as e:
                print(f"[val_ai] {prov} 실패: {repr(e)[:200]}")
                o = None
            if _valid(o):
                out = o
                break
    cost = _LAST_USAGE.get("total")             # 재시도까지 합친 이번 생성 비용(Claude만)
    if out is None:
        return {"text": valuation_rules.template_text(facts), "provider": "template", "removed": 0, "fallback": True,
                "cost_usd": cost, "error_note": f"{prov or 'AI 키 없음'} 응답 실패 — 규칙 기반 기본 해석"}
    text, removed = _clean(out, facts)
    if not text["one_line"]:
        text["one_line"] = valuation_rules.template_text(facts)["one_line"]
    return {"text": text, "provider": prov, "removed": removed, "fallback": False,
            "usage": _LAST_USAGE.get("usage"), "cost_usd": cost}
