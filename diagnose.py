"""재무제표 자동 진단 + 해석 — 순수 함수 (데이터 소스/UI와 분리, 테스트 가능).

입력: 기존 valuate.build_financials 구조의 financials(병렬 배열) + 메타.
    fin = {
      "ticker", "companyName", "sector",
      "isCyclical": bool|None,   # None이면 sector로 자동 분류
      "isFinancial": bool|None,
      "financials": {
        "years":     ["2021","2022","2023","2024", "2025E"(예상, 진단서 제외)],
        "revenue":   [...], "opinc": [...], "netinc": [...],
        "ocf":       [...], "roe": [...], "debtratio": [...], "opmargin": [...],
        "intexp":    [...] | None,   # 이자비용(양수). 없으면 이자보상배율=데이터없음
        "unit": "억원"|"M$", "cur": "KRW"|"USD",
      },
    }
출력: FinancialDiagnosis(dict) — 요청 스펙 그대로 + summary/interpretation.

원칙: 매수·매도 추천 없음. 결측은 추정하지 않고 na 처리 후 분모에서 제외.
"""
from __future__ import annotations

# ── 업종 분류 ─────────────────────────────────────────────
# 사이클(경기민감) 업종: 이익이 크게 출렁여 '고점 PER 착시'가 잘 생기는 곳.
CYCLICAL_KW = {
    "반도체": "반도체", "semiconductor": "반도체", "메모리": "반도체",
    "조선": "조선", "shipbuild": "조선",
    "화학": "화학", "chemical": "화학",
    "해운": "해운", "shipping": "해운", "marine": "해운",
    "철강": "철강", "steel": "철강",
    "정유": "정유", "refin": "정유", "oil & gas refin": "정유",
}
# 금융업: 부채비율 기준(200%)을 적용하지 않음(사업 구조상 부채가 본질).
FINANCIAL_KW = {
    "은행": "은행", "bank": "은행",
    "보험": "보험", "insurance": "보험",
    "증권": "증권", "broker": "증권", "securities": "증권", "capital markets": "증권",
    "금융": "금융", "financial": "금융",
}


def classify_sector(sector):
    """sector 문자열 → (isCyclical, isFinancial, cyclical_label).
    cyclical_label은 해석 문구에 쓸 한국어 업종명(예: '반도체')."""
    s = (sector or "").lower()
    cyc_label = None
    for kw, label in CYCLICAL_KW.items():
        if kw.lower() in s:
            cyc_label = label
            break
    is_fin = any(kw.lower() in s for kw in FINANCIAL_KW)
    return (cyc_label is not None), is_fin, cyc_label


# ── 소도구 ───────────────────────────────────────────────
def _num(x):
    try:
        if x is None:
            return None
        f = float(x)
        return None if (f != f) else f          # NaN 제외
    except (TypeError, ValueError):
        return None


def _fmt(x, d=1):
    """숫자 → 사람이 읽는 문자열. 소수 d자리, 정수면 정수로."""
    if x is None:
        return "—"
    r = round(float(x), d)
    return str(int(r)) if r == int(r) else f"{r:.{d}f}"


def _josa(word, kind):
    """받침에 맞는 조사 선택. kind: '은는'|'이가'|'을를'.
    영문/숫자 끝(ROE 등)은 관용적으로 받침 없는 형태(는/가/를)."""
    a, b = {"은는": ("은", "는"), "이가": ("이", "가"), "을를": ("을", "를")}[kind]
    if not word:
        return b
    code = ord(word[-1])
    if 0xAC00 <= code <= 0xD7A3:               # 한글 음절
        return a if (code - 0xAC00) % 28 else b   # 받침 있으면 앞형태
    return b


def _actual(fin_arrays):
    """예상연도('E' 접미사)를 제외한 실적 연도만 정렬해 병렬배열로 반환."""
    years_all = fin_arrays.get("years") or []
    idx = [i for i, y in enumerate(years_all) if not str(y).strip().upper().endswith("E")]

    def col(name):
        arr = fin_arrays.get(name) or []
        return [_num(arr[i]) if i < len(arr) else None for i in idx]

    out = {"years": [str(years_all[i]) for i in idx]}
    for k in ("revenue", "opinc", "netinc", "ocf", "roe", "debtratio", "opmargin", "intexp", "equity"):
        out[k] = col(k)
    return out


def _last(arr):
    """뒤에서부터 첫 유효값과 그 인덱스."""
    for i in range(len(arr) - 1, -1, -1):
        if arr[i] is not None:
            return arr[i], i
    return None, -1


# ── 개별 항목 판정 ───────────────────────────────────────
def _chk_op_growth(op, unit):
    v, i = _last(op)
    w = [x for x in op[-3:] if x is not None]
    if v is None or len(w) < 2:
        return dict(value=v, unit=unit, status="na")
    a, c = w[0], w[-1]
    increasing = all(w[k] < w[k + 1] for k in range(len(w) - 1))
    if c <= a:
        st = "fail"
    elif increasing or c >= w[-2]:
        st = "pass"
    else:
        st = "warn"           # 3년 전보단 높지만 최근 한 해 꺾임
    return dict(value=round(c, 1), unit=unit, status=st)


def _chk_op_margin(om):
    v, i = _last(om)
    w = [x for x in om[-3:] if x is not None]
    if v is None or len(w) < 2:
        return dict(value=v, unit="%", status="na")
    avg = sum(w) / len(w)
    ratio = (v / avg) if avg else None
    if ratio is None:
        st = "na"
    elif ratio >= 1.0:
        st = "pass"
    elif ratio >= 0.9:
        st = "warn"
    else:
        st = "fail"
    return dict(value=round(v, 1), unit="%", status=st, _avg=round(avg, 1))


def _chk_cash_vs_profit(ocf, netinc):
    o, io = _last(ocf)
    # 현금흐름과 같은 해의 순이익으로 비교
    n = netinc[io] if 0 <= io < len(netinc) else None
    if o is None or n is None:
        return dict(value=None, unit="배", status="na")
    if n <= 0:
        # 이익 자체가 적자/0 → 비율 무의미. 현금 유입 여부만 보조 판단.
        return dict(value=None, unit="배", status=("warn" if o > 0 else "fail"), _ni_nonpos=True)
    r = o / n
    st = "pass" if r >= 1.0 else ("warn" if r >= 0.8 else "fail")
    return dict(value=round(r, 2), unit="배", status=st)


def _chk_debt(debtratio, is_financial):
    if is_financial:
        return dict(value=None, unit="%", status="na", _financial=True)
    v, i = _last(debtratio)
    if v is None:
        return dict(value=None, unit="%", status="na")
    if v < 0:
        st = "fail"           # 자본잠식(자본<0)
    elif v <= 200:
        st = "pass"
    elif v <= 300:
        st = "warn"
    else:
        st = "fail"
    return dict(value=round(v, 1), unit="%", status=st)


def _chk_interest_cov(opinc, intexp):
    o, io = _last(opinc)
    ie = intexp[io] if (intexp and 0 <= io < len(intexp)) else None
    if ie is None:
        return dict(value=None, unit="배", status="na")     # 이자비용 데이터 없음
    if ie == 0:
        return dict(value=None, unit="배", status="pass", _nodebt=True)  # 이자부담 없음
    if o is None:
        return dict(value=None, unit="배", status="na")
    r = o / ie
    st = "pass" if r >= 1.5 else ("warn" if r >= 1.0 else "fail")
    return dict(value=round(r, 1), unit="배", status=st)


def _chk_roe(roe):
    v, i = _last(roe)
    if v is None:
        return dict(value=None, unit="%", status="na")
    st = "pass" if v >= 10 else ("warn" if v >= 5 else "fail")
    return dict(value=round(v, 1), unit="%", status=st)


_CHECK_META = {
    1: ("영업이익 증가", "3년 연속 증가 또는 최근 > 3년 전",
        "영업이익이 꾸준히 늘어야 사업이 성장하고 있다고 볼 수 있습니다."),
    2: ("영업이익률 유지", "3년 평균 대비 하락 아님",
        "이익률이 유지돼야 가격·비용 경쟁력이 지켜지고 있다는 뜻입니다."),
    3: ("현금이 이익보다 큼", "영업현금흐름 ÷ 순이익 ≥ 1.0배",
        "1배 미만이면 장부상 이익만큼 실제 현금이 들어오지 않은 것입니다."),
    4: ("부채비율", "부채 ÷ 자본 ≤ 200%",
        "부채가 자본의 2배(200%)를 넘으면 재무 부담이 커집니다."),
    5: ("이자보상배율", "영업이익 ÷ 이자비용 ≥ 1.5배",
        "1배 미만이면 영업이익으로 이자도 다 못 냅니다."),
    6: ("ROE", "순이익 ÷ 자본 ≥ 10%",
        "자본을 얼마나 효율적으로 굴려 이익을 냈는지 봅니다. 10% 이상이면 양호합니다."),
}


# ── 메인: 진단 ───────────────────────────────────────────
def diagnose(fin):
    meta_sector = fin.get("sector") or ""
    auto_cyc, auto_fin, cyc_label = classify_sector(meta_sector)
    is_cyclical = fin["isCyclical"] if fin.get("isCyclical") is not None else auto_cyc
    is_financial = fin["isFinancial"] if fin.get("isFinancial") is not None else auto_fin

    fa = fin.get("financials") or {}
    a = _actual(fa)
    unit = fa.get("unit") or ""

    raw = {
        1: _chk_op_growth(a["opinc"], unit),
        2: _chk_op_margin(a["opmargin"]),
        3: _chk_cash_vs_profit(a["ocf"], a["netinc"]),
        4: _chk_debt(a["debtratio"], is_financial),
        5: _chk_interest_cov(a["opinc"], a["intexp"]),
        6: _chk_roe(a["roe"]),
    }

    checks = []
    for cid in (1, 2, 3, 4, 5, 6):
        label, threshold, reason = _CHECK_META[cid]
        r = raw[cid]
        if cid == 4 and r.get("_financial"):
            reason = "금융업은 부채비율로 판단하지 않습니다."
            threshold = "해당 없음(금융업)"
        checks.append({
            "id": cid, "label": label,
            "value": r.get("value"), "unit": r.get("unit", ""),
            "threshold": threshold, "status": r["status"], "reason": reason,
        })

    pass_count = sum(1 for c in checks if c["status"] == "pass")
    evaluated = sum(1 for c in checks if c["status"] != "na")
    ratio = (pass_count / evaluated) if evaluated else 0

    if ratio >= 0.8:
        level, text = "green", "재무적으로 튼튼한 회사입니다"
    elif ratio >= 0.4:
        level, text = "yellow", "나쁘지 않지만 확인할 곳이 있습니다"
    else:
        level, text = "red", "재무 지표에 경고 신호가 있습니다"

    history = []
    for k, y in enumerate(a["years"]):
        history.append({
            "year": y,
            "revenue": a["revenue"][k], "operatingProfit": a["opinc"][k],
            "netIncome": a["netinc"][k], "operatingCashFlow": a["ocf"][k],
            "roe": a["roe"][k], "debtRatio": a["debtratio"][k],
        })

    out = {
        "ticker": fin.get("ticker"), "companyName": fin.get("companyName") or fin.get("ticker"),
        "sector": meta_sector, "isCyclical": is_cyclical, "isFinancial": is_financial,
        "unit": unit,
        "checks": checks,
        "passCount": pass_count, "evaluatedCount": evaluated,
        "summary": {"level": level, "text": text},
    }
    out["interpretation"] = interpret(out, a, cyc_label or meta_sector, raw)
    return out


# ── 해석 생성기 (순수 함수) ──────────────────────────────
def interpret(diag, a, sector_label, raw=None):
    """조건 분기 템플릿으로 3단락 해석 생성. diag=진단결과, a=실적 병렬배열."""
    name = diag["companyName"]
    roe = a["roe"]
    om = a["opmargin"]
    ocf = a["ocf"]
    ni = a["netinc"]
    dr = a["debtratio"]

    roe_v, _ = _last(roe)
    om_v, _ = _last(om)

    # ── 1단락: 사실 ──
    parts_f = []
    if om_v is not None and roe_v is not None:
        parts_f.append(f"{name}의 최근 영업이익률은 {_fmt(om_v)}%이고, ROE는 {_fmt(roe_v)}%입니다.")
    elif roe_v is not None:
        parts_f.append(f"{name}의 최근 ROE는 {_fmt(roe_v)}%입니다.")
    elif om_v is not None:
        parts_f.append(f"{name}의 최근 영업이익률은 {_fmt(om_v)}%입니다.")
    else:
        parts_f.append(f"{name}의 최근 수익성 지표를 불러왔습니다.")
    parts_f.append(f"평가 가능한 {diag['evaluatedCount']}개 항목 중 "
                   f"{diag['passCount']}개가 기준을 충족했습니다.")
    facts = " ".join(parts_f)

    # ── 2단락: 맥락(조건 분기) ──
    ctx = []
    roe_act = [x for x in roe if x is not None]
    roe_avg5 = (sum(roe_act[-5:]) / len(roe_act[-5:])) if roe_act else None
    roe_hot = (roe_v is not None and roe_avg5 is not None and roe_avg5 > 0
               and roe_v >= 1.5 * roe_avg5)
    if roe_hot:
        mult = roe_v / roe_avg5
        yrs_lbl = "5년" if len(roe_act) >= 5 else f"{len(roe_act)}년"
        ctx.append(f"다만 현재 ROE {_fmt(roe_v)}%는 최근 {yrs_lbl} 평균 {_fmt(roe_avg5)}%의 "
                   f"{_fmt(mult)}배 수준입니다. 지금 이익이 평소보다 크게 높다는 뜻입니다.")

    om_act = [x for x in om if x is not None]
    if om_v is not None and len(om_act) >= 3 and om_v >= max(om_act[-5:]):
        span = "최근 5년" if len(om_act) >= 5 else "최근 몇 해"
        ctx.append(f"영업이익률도 {span} 중 가장 높습니다.")

    # 영업현금흐름 ÷ 순이익 < 1 이 2년 이상 연속
    cash_low_streak = 0
    for o, n in zip(ocf, ni):
        if o is not None and n is not None and n > 0 and (o / n) < 1.0:
            cash_low_streak += 1
        else:
            cash_low_streak = 0
        if cash_low_streak >= 2:
            break
    if cash_low_streak >= 2:
        ctx.append("장부상 이익에 비해 실제 들어온 현금이 적은 해가 이어지고 있습니다. "
                   "매출채권이나 재고가 늘고 있는지 확인이 필요합니다.")

    # 부채비율 3년 연속 상승
    dr_act = [x for x in dr if x is not None]
    debt_rising = (len(dr_act) >= 4 and dr_act[-3] < dr_act[-2] < dr_act[-1])
    if debt_rising:
        ctx.append("부채비율이 3년째 오르고 있습니다.")

    if not ctx:
        ctx.append("특별히 두드러진 과열 신호나 이상 징후는 확인되지 않습니다.")
    context = " ".join(ctx)

    # ── 3단락: 판단 재료(단정 금지) ──
    if diag["isCyclical"] and roe_hot:
        judgment = (
            f"{sector_label}{_josa(sector_label, '은는')} 이익이 크게 출렁이는 사이클 업종입니다. "
            "이런 업종은 이익이 가장 좋을 때 PER이 가장 낮게 나오고, "
            "그 시점이 오히려 고점인 경우가 많습니다. "
            "지금 숫자가 좋다는 것만으로 판단하지 마시고, "
            "이 이익이 몇 년 더 갈지를 먼저 따져보십시오."
        )
    else:
        weak = [c for c in diag["checks"] if c["status"] in ("fail", "warn")]
        strong = [c for c in diag["checks"] if c["status"] == "pass"]
        js = []
        if weak:
            names = ", ".join(c["label"] for c in weak)
            js.append(f"기준에 못 미치거나 아슬아슬한 항목은 {names}입니다.")
            tips = {1: "영업이익이 왜 줄었는지",
                    2: "이익률이 떨어진 원인(단가·원가)이 무엇인지",
                    3: "장부 이익과 실제 현금의 차이가 어디서 나는지",
                    4: "부채가 늘어난 이유와 상환 부담이 감당 가능한지",
                    5: "영업이익으로 이자를 감당할 수 있는지",
                    6: "자본 대비 이익이 낮은 이유가 무엇인지"}
            pts = [tips[c["id"]] for c in weak if c["id"] in tips][:3]
            if pts:
                js.append("특히 " + ", ".join(pts) + f"{_josa(pts[-1], '을를')} 확인해 보십시오.")
            if strong:
                s_names = ", ".join(c["label"] for c in strong)
                js.append(f"반대로 {s_names}{_josa(strong[-1]['label'], '은는')} 기준을 넘긴 상태입니다.")
        else:
            js.append("평가한 항목이 모두 기준을 충족했습니다. "
                      "현재 드러난 재무 지표만 놓고 보면 특별히 확인이 시급한 약점은 보이지 않는 상태입니다. "
                      "다만 재무제표는 과거 기록이므로, 이 흐름이 앞으로도 이어질지는 별도로 살펴보십시오.")
        judgment = " ".join(js)

    # ── 종합 해석 (매끄러운 서술 · 한 단락) ──
    w2 = [c for c in diag["checks"] if c["status"] in ("fail", "warn")]
    o = []
    if om_v is not None and roe_v is not None:
        prof = "탄탄한 수익성" if roe_v >= 10 else ("보통 수준의 수익성" if roe_v >= 5 else "다소 부진한 수익성")
        o.append(f"{name}{_josa(name, '은는')} 최근 영업이익률 {_fmt(om_v)}%, ROE {_fmt(roe_v)}%로 {prof}을 보이며, "
                 f"재무 6개 점검 항목 중 {diag['passCount']}개({diag['evaluatedCount']}개 평가 대상)를 통과했습니다.")
    else:
        o.append(f"{name}의 재무 6개 점검 항목 중 {diag['passCount']}개"
                 f"({diag['evaluatedCount']}개 평가 대상)가 기준을 충족했습니다.")
    if w2:
        o.append(f"특히 {', '.join(c['label'] for c in w2)} 항목이 기준에 미치지 못해 이 부분을 눈여겨볼 필요가 있습니다.")
    else:
        o.append("핵심 지표 대부분이 기준을 충족해 재무 기반은 비교적 견조한 편입니다.")
    notes = []
    if roe_hot and roe_avg5:
        notes.append(f"현재 ROE가 최근 평균의 {_fmt(roe_v / roe_avg5)}배로 이익이 평소보다 크게 높은 국면인 점")
    if cash_low_streak >= 2:
        notes.append("장부 이익에 비해 실제 현금 유입이 약한 흐름이 이어지는 점")
    if debt_rising:
        notes.append("부채비율이 몇 년째 오르고 있는 점")
    if notes:
        o.append("다만 " + ", ".join(notes) + f"{_josa(notes[-1], '은는')} 함께 살펴볼 대목입니다.")
    if diag["isCyclical"] and roe_hot:
        o.append(f"무엇보다 {sector_label}{_josa(sector_label, '은는')} 이익이 크게 출렁이는 사이클 업종이라, "
                 "지금처럼 실적이 좋을 때가 오히려 정점인 경우가 많으므로 이 이익이 얼마나 이어질지를 먼저 따져볼 필요가 있습니다.")
    else:
        o.append("재무제표는 결국 과거 실적인 만큼, 이 흐름이 앞으로도 이어질지는 향후 실적과 증권사 전망을 함께 확인하는 것이 좋습니다.")
    overall = " ".join(o)
    return {"facts": facts, "context": context, "judgment": judgment, "overall": overall}


DISCLAIMER = (
    "재무제표는 과거 기록입니다. 앞으로도 같을 것이라는 보장은 없습니다.\n"
    "이 페이지는 투자 판단을 돕는 참고 자료이며 투자 권유가 아닙니다."
)
