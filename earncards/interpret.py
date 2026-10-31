"""실적 해석 — 숫자에서 규칙으로 쓰는 해석 글 (AI 호출 없음, 지어낸 문장 없음).

build(data) → {"headline", "sections": [{"icon", "title", "tone", "text"}], "watch": [...], "note"}
- data 는 metrics.enrich() 를 거친 것. 마지막 분기가 해석 대상
- 말투: 해요체, 단정·매수/매도 표현 없음 (히르찬 브랜드 규칙)
"""
from __future__ import annotations

from render import money, pct

COSTS = [("cost_of_revenue", "매출원가"), ("rnd", "연구개발비"), ("sales_marketing", "판매·마케팅비"),
         ("general_admin", "일반관리비"), ("sga", "판관비"), ("operating_expenses", "영업비용")]


# 받침 있는 끝 글자(숫자 읽기 포함): 0 영·1 일·3 삼·6 육·7 칠·8 팔 → 받침 있음, ㄹ 받침은 1·7·8
_DIGIT_BATCHIM = {"0": "ㅇ", "1": "ㄹ", "3": "ㅁ", "6": "ㄱ", "7": "ㄹ", "8": "ㄹ"}


def _batchim(word: str):
    """끝 글자 받침: None(없음) / 'ㄹ' / 'o'(그 밖의 받침)"""
    w = word.rstrip(" )")
    if not w:
        return None
    c = w[-1]
    if "가" <= c <= "힣":
        jong = (ord(c) - 0xAC00) % 28
        return None if jong == 0 else ("ㄹ" if jong == 8 else "o")
    if c.isdigit():
        b = _DIGIT_BATCHIM.get(c)
        return None if b is None else ("ㄹ" if b == "ㄹ" else "o")
    return None  # %, B, $ 등은 받침 없이 읽음


def eyo(word: str) -> str:
    return word + ("이에요" if _batchim(word) else "예요")


def ro(word: str) -> str:
    return word + ("으로" if _batchim(word) == "o" else "로")


def ga(word: str) -> str:
    return word + ("이" if _batchim(word) else "가")


def _updown(v, up="늘었어요", down="줄었어요"):
    return up if v >= 0 else down


def _consec(vals) -> int:
    k = 0
    for a, b in zip(vals[-2::-1], vals[::-1]):
        if a is None or b is None or b <= a:
            break
        k += 1
    return k


def build(data: dict) -> dict:
    qs = data["quarters"]
    last = qs[-1]
    v, m, cur = last["values"], last.get("m", {}), data["currency"]
    prev_m = qs[-2].get("m", {}) if len(qs) > 1 else {}
    secs, watch = [], []
    head = []

    # ① 매출
    ry, py = m.get("revenue_yoy"), prev_m.get("revenue_yoy")
    if v.get("revenue") is not None and ry is not None:
        t = f"매출은 {ro(money(v['revenue'], cur))} 1년 전보다 {pct(abs(ry), False)} {_updown(ry)}."
        tone = "pos" if ry > 0 else "neg"
        if py is not None:
            if ry > py + 1:
                t += f" 직전 분기 성장률({pct(py)})보다 빨라졌어요."
                k = _consec([q.get("m", {}).get("revenue_yoy") for q in qs[-6:]])
                if k >= 3:
                    t += f" {k}분기 연속 성장 속도가 붙고 있어요."
                head.append("매출 성장 가속")
            elif ry < py - 1:
                t += f" 다만 직전 분기({pct(py)})보다 성장 속도는 느려졌어요."
                tone = "neg" if ry < 5 else "mid"
                head.append("매출 성장 둔화" if ry > 0 else "매출 감소")
                watch.append("다음 분기에 매출 성장률이 다시 오르는지")
            else:
                t += f" 직전 분기({pct(py)})와 비슷한 속도예요."
                head.append("매출 증가" if ry > 0 else "매출 감소")
        secs.append({"icon": "📈", "title": "매출", "tone": tone, "text": t})

    # ② 수익성
    op, oy = v.get("operating_income"), m.get("operating_income_yoy")
    opm, dpp = m.get("opm"), m.get("opm_yoy_pp")
    if op is not None:
        if op < 0:
            t, tone = f"영업적자 {money(-op, cur)}{'을' if _batchim(money(-op, cur)) else '를'} 냈어요.", "neg"
            head.append("영업적자")
        else:
            t = f"영업이익은 {money(op, cur)}"
            t = (ro(t) + f" 1년 전보다 {pct(abs(oy), False)} {_updown(oy)}.") if oy is not None else eyo(t) + "."
            tone = "mid"
            if oy is not None and ry is not None and oy > ry + 3:
                t += f" 매출보다 이익이 더 빨리 늘어 영업이익률이 {opm:.1f}%" + (f"({dpp:+.1f}%p)로 올라갔어요." if dpp is not None else "예요.")
                tone = "pos"
                head.append("이익률 개선")
            elif oy is not None and ry is not None and oy < ry - 3:
                t += f" 매출만큼 이익이 늘지 못해 영업이익률이 {opm:.1f}%" + (f"({dpp:+.1f}%p)예요." if dpp is not None else "예요.")
                tone = "neg"
                head.append("이익률 하락")
                watch.append("비용 증가가 일시적인지, 이익률이 회복되는지")
            elif opm is not None:
                t += f" 영업이익률은 {opm:.1f}%" + (f"({dpp:+.1f}%p)예요." if dpp is not None else "예요.")
            g, gpp = m.get("gpm"), m.get("gpm_yoy_pp")
            if g is not None and gpp is not None and abs(gpp) >= 1:
                t += f" 매출총이익률(원가를 빼고 남는 비율)은 {g:.1f}%로 {abs(gpp):.1f}%p {'올랐어요' if gpp > 0 else '내려갔어요'}."
        secs.append({"icon": "💰", "title": "수익성", "tone": tone, "text": t})

    # ③ 비용
    if ry is not None:
        rows = [(m[f"{k}_yoy"], name, m.get(f"{k}_share"), m.get(f"{k}_share_yoy_pp"))
                for k, name in COSTS if m.get(f"{k}_yoy") is not None]
        if rows:
            g, name, share, spp = max(rows)
            if g > ry + 5:
                t = (f"가장 빨리 늘어난 비용은 {name}({pct(g)})로 매출 성장({pct(ry)})보다 빨라요."
                     + (f" 매출에서 차지하는 비중이 {share:.1f}%({spp:+.1f}%p)가 됐어요." if share is not None and spp is not None else ""))
                secs.append({"icon": "🧾", "title": "비용", "tone": "neg", "text": t})
            elif all(r[0] <= ry for r in rows):
                secs.append({"icon": "🧾", "title": "비용", "tone": "pos",
                             "text": f"주요 비용이 모두 매출({pct(ry)})보다 천천히 늘어 이익률을 받쳐 줬어요."})

    # ④ 순이익 (영업 외 손익)
    ni = v.get("net_income")
    if ni is not None and op and op > 0:
        r = ni / op
        ny = m.get("net_income_yoy")
        base = eyo(f"순이익은 {money(ni, cur)}" + (f"(1년 전보다 {pct(ny)})" if ny is not None else "")) + "."
        if r > 1.05:
            secs.append({"icon": "🔎", "title": "순이익", "tone": "mid", "text": base +
                         " 순이익이 영업이익보다 많아요. 보유 주식 평가이익·이자 수익 같은 영업 외 이익이 컸다는 뜻이라,"
                         " 본업 실력은 영업이익으로 보는 게 좋아요."})
            watch.append("영업 외 이익을 뺀 본업(영업이익) 흐름")
        elif r < 0.55:
            secs.append({"icon": "🔎", "title": "순이익", "tone": "neg", "text": base +
                         f" 영업이익의 {r * 100:.0f}% 수준이에요. 영업 외 손실(투자 평가손실·이자 비용 등)이나 세금 영향이 컸어요."})
            watch.append("영업 외 손실이 일회성인지")

    # ⑤ 현금흐름
    fcf, ocf, capex = v.get("fcf"), v.get("operating_cash_flow"), v.get("capex")
    if fcf is not None and ocf is not None and capex is not None:
        ratio, cy = m.get("capex_to_ocf"), m.get("capex_yoy")
        if fcf < 0:
            t, tone = (f"설비투자({money(capex, cur)})가 영업으로 번 현금({money(ocf, cur)})보다 많아"
                       f" 잉여현금흐름이 {ro(money(fcf, cur))} 마이너스예요."), "neg"
            head.append("현금은 투자로 마이너스")
        else:
            t = (f"영업으로 번 현금 {money(ocf, cur)} 중 설비투자 {money(capex, cur)}{'을' if _batchim(money(capex, cur)) else '를'} 빼고 "
                 f"{ga(money(fcf, cur))} 남았어요.")
            tone = "neg" if ratio and ratio >= 70 else "pos"
            if ratio:
                t += f" 번 현금의 {ratio:.0f}%를 다시 투자했어요."
        if cy is not None and cy >= 30:
            t += f" 설비투자는 1년 새 {pct(cy)} 늘었어요."
            watch.append("늘어난 투자가 매출 성장으로 이어지는지")
        secs.append({"icon": "💵", "title": "현금흐름", "tone": tone, "text": t})
    elif any(q["values"].get("fcf") is not None for q in qs[:-1]):
        secs.append({"icon": "💵", "title": "현금흐름", "tone": "mid",
                     "text": "이번 분기 현금흐름은 아직 공시 전이에요 (정기보고서가 나오면 반영돼요)."})

    # ⑥ 부문
    segs = [s for s in last.get("segments", []) if s.get("yoy") is not None and not s.get("hide_growth")]
    gy = data.get("series_yoy", {})
    for name in data.get("growth_in_panel", []):
        h = gy.get(name, {})
        if last["calendar_quarter"] in h:
            segs.append({"name": name, "yoy": h[last["calendar_quarter"]],
                         "prev_yoy": h.get(qs[-2]["calendar_quarter"]) if len(qs) > 1 else None})
    if segs:
        top = max(segs, key=lambda s: s["yoy"])
        low = min(segs, key=lambda s: s["yoy"])
        t = f"가장 빠르게 성장한 곳은 {eyo(top['name'] + '(' + pct(top['yoy']) + ')')}."
        if top.get("prev_yoy") is not None and top["yoy"] > top["prev_yoy"] + 1:
            t += f" 직전 분기({pct(top['prev_yoy'])})보다 더 빨라졌어요."
        if low is not top:
            t += f" 가장 약한 곳은 {low['name']}({pct(low['yoy'])})"
            if low.get("prev_yoy") is not None and low["yoy"] < low["prev_yoy"] - 1:
                t += f"로, 직전 분기({pct(low['prev_yoy'])})보다 더 나빠졌어요."
                watch.append(f"{low['name']} 부진이 이어지는지")
            else:
                t += "예요."
        neg = [s for s in last.get("segments", []) if s.get("op") is not None and s["op"] < 0]
        for s in neg:
            t += f" {s['name']}{'은' if _batchim(s['name']) else '는'} 영업적자 {eyo(money(-s['op'], cur))}."
        secs.append({"icon": "🧩", "title": "부문", "tone": "mid", "text": t})

    if not watch:
        watch.append("다음 분기에도 지금의 성장 속도와 이익률이 유지되는지")
    headline = ", ".join(dict.fromkeys(head)) or "이번 분기 실적 요약"
    return {"headline": headline, "sections": secs, "watch": list(dict.fromkeys(watch))[:3],
            "note": "공개된 숫자를 정해진 규칙으로 정리한 해석이에요. 투자 권유가 아닌 정보 제공 목적입니다."}
