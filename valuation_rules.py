"""🧠 AI 종합 해석 — 1단계: 규칙 엔진(결정론적).

가치평가 결과(analyze_data) + 과거 PSR(per_hist.psr_history) + 재무 항목(edgar_facts)으로
지표·진단 플래그·추천 지표·4가지 판정을 계산해 facts(dict)로 돌려준다.
LLM은 이 facts만 보고 문장을 쓴다(숫자 계산·판정은 전부 여기서).
임계값은 아래 CONFIG에서 조정한다.
"""
import math
import datetime as dt

CONFIG = {
    # A. 이익의 질
    "one_off_net_minus_op_pp": 5.0,      # 순이익률 − 영업이익률 ≥ 5%p → 일회성 이익 의심
    "one_off_nonop_share": 0.15,         # 영업외손익 ÷ 순이익 ≥ 15%
    "tax_gap_pp": 10.0,                  # 실효세율이 5년 평균과 10%p 이상 차이
    # B. 현금 창출
    "heavy_capex_gap_pp": 15.0,          # 영업이익률 − FCF 마진 ≥ 15%p
    "heavy_capex_vs_avg": 1.5,           # capex/매출이 본인 5년 평균의 1.5배 이상
    "heavy_capex_to_da": 2.0,            # 또는 capex ÷ 감가상각 ≥ 2배
    "fcf_anomaly_pp": 10.0,              # FCF 마진이 5년 평균보다 10%p 이상 낮음
    "fcf_anomaly_capex_normal": 1.3,     # 그때 capex/매출이 평균의 1.3배 미만이면 '평소 수준'
    "big_acquisition_share": 0.03,       # 인수 지출 ≥ 매출의 3%면 근거로 제시
    # C. 매출·이익 방향
    "margin_regime_pp": 8.0,             # 영업이익률이 5년 사이 8%p 이상 변화
    "share_shrink_pct": 2.0,             # 희석 주식수 5년 감소율이 이 이상이면 '자사주 효과 확인됨'
    # D. PEG
    "peg_min_growth_pct": 1.0,           # 성장률 1% 미만은 PEG '의미 없음'
    "peg_cheap": 1.0, "peg_expensive": 2.0,
    "peg_base_effect_pct": 50.0,         # 성장률 50% 초과(적자 탈출·급반등)는 PEG 과소 → 판정에서 제외
    # E. PSR 밴드
    "early_inflation_mean_ratio": 1.3,   # 전체 평균 ≥ 5년 평균 × 1.3
    "early_growth_gap_pp": 10.0,         # 상장 초기 3년 매출 성장률이 최근 3년보다 10%p 이상 높음
    "extreme_sigma": 2.0,
    "data_gap_ratio": 0.9,               # 실제 주 수 < 기대 × 0.9 → 데이터 누락
    "break_share": 0.5,                  # 최근 52주 중 이 비율 이상이 직전 3년 박스 밖
    # F. 지표 추천
    "high_growth_pct": 20.0, "mature_growth_pct": 10.0, "thin_margin_pct": 5.0,
    "rule40_min_growth_pct": 15.0,
    # H. 판정
    "psr_z_cheap": -1.0, "psr_z_exp": 1.0,
    "cash_strong_fcf_pct": 10.0,
    "growth_accel_pp": 3.0, "growth_slow_pp": -5.0,
}


def _n(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _r(x, d=1):
    return None if x is None else round(x, d)


def _pct(a, b):
    """a/b × 100 (b>0)"""
    a, b = _n(a), _n(b)
    return a / b * 100 if (a is not None and b) else None


def _flag(fid, level, title, evidence, hint):
    return {"id": fid, "level": level, "title": title,
            "evidence": {k: v for k, v in evidence.items() if v is not None}, "hint": hint}


# ───────────────────────── 업종 판정 (G) ─────────────────────────
def biz_type(sector, industry, gross_margin):
    s, i = (sector or "").lower(), (industry or "").lower()
    if "financial" in s or any(w in i for w in ("bank", "insurance", "capital markets", "credit")):
        return "financial", "금융업"
    if "software" in i:
        return "software", "소프트웨어형"
    if "semiconductor" in i:
        return "semis", "반도체형"
    if "technology" in s:
        return "hardware", "기술 하드웨어·기기형"
    if "internet" in i or "interactive" in i:
        return "platform", "인터넷 플랫폼형"
    if "communication" in s:
        return "media", "통신·미디어형"
    if "defensive" in s or "staples" in s:
        return "staples", "필수소비재(브랜드)형"
    if "utilit" in s:
        return "utility", "유틸리티(공공요금형)"
    if "real estate" in s:
        return "reit", "부동산·리츠"
    if "health" in s:
        return "health", "헬스케어형"
    if "energy" in s or "basic materials" in s:
        return "commodity", "원자재·에너지(경기순환)형"
    if s:
        return "other", {"industrials": "산업재형", "consumer cyclical": "경기소비재형"}.get(s, sector)
    gm = _n(gross_margin)       # 업종 정보가 없으면(국내 일부) 매출총이익률로
    if gm is None:
        return "unknown", "업종 정보 없음"
    return ("highmargin", "고마진형") if gm >= 0.6 else (("mid", "중간 마진 제조형") if gm >= 0.35 else ("low", "저마진 제조형"))


# ───────────────────────── 재무 정리 ─────────────────────────
def _fin_us(fin):
    """edgar_facts 결과 → 비율(%) 시계열·TTM."""
    if not fin:
        return None
    A, T = fin["annual"], fin["ttm"]

    def ratio(k, base="revenue"):
        return [_pct(a, b) for a, b in zip(A.get(k) or [], A.get(base) or [])]
    fcf_a = [(o - c) if (o is not None and c is not None) else None for o, c in zip(A["ocf"], A["capex"])]
    rev_a = A["revenue"]
    out = {
        "source": fin["source"], "years": fin["years"], "ttm_end": fin.get("ttm_end"),
        "op_margin_y": ratio("op_income"), "net_margin_y": ratio("net_income"),
        "fcf_margin_y": [_pct(f, r) for f, r in zip(fcf_a, rev_a)],
        "capex_rev_y": ratio("capex"),
        "tax_rate_y": [_pct(t, p) if (p and p > 0) else None for t, p in zip(A["tax"], A["pretax"])],
        "shares_y": A.get("shares_diluted"),
        "rev_y": rev_a,
        "divest_y": A.get("divestitures"),
        "acq_y": A.get("acquisitions"),
    }
    rev = _n(T.get("revenue"))
    ocf, capex = _n(T.get("ocf")), _n(T.get("capex"))
    fcf = (ocf - capex) if (ocf is not None and capex is not None) else None
    ni, op = _n(T.get("net_income")), _n(T.get("op_income"))
    out.update({
        "rev": rev, "op_income": op, "net_income": ni, "nonop": _n(T.get("nonop")),
        "pretax": _n(T.get("pretax")), "tax": _n(T.get("tax")),
        "ocf": ocf, "capex": capex, "fcf": fcf, "da": _n(T.get("da")),
        "acq": _n(T.get("acquisitions")), "divest": _n(T.get("divestitures")),
        "buyback": _n(T.get("buyback")), "dividends": _n(T.get("dividends")), "sbc": _n(T.get("sbc")),
        "op_margin": _pct(op, rev), "net_margin": _pct(ni, rev), "ocf_margin": _pct(ocf, rev),
        "fcf_margin": _pct(fcf, rev), "capex_rev": _pct(capex, rev),
        "capex_da": (capex / _n(T.get("da"))) if (capex and _n(T.get("da"))) else None,
        "fcf_conv": (fcf / ni) if (fcf is not None and ni and ni > 0) else None,
        "tax_rate": _pct(T.get("tax"), T.get("pretax")) if (_n(T.get("pretax")) or 0) > 0 else None,
        "unit": 1e9, "unit_lbl": "B",
    })
    return out


def _fin_kr(fin):
    """국내(WISEfn, 억원) — 확정 연도만. 설비투자·감가상각·영업외손익 등은 없음(null)."""
    if not fin or not fin.get("years"):
        return None
    idx = [i for i, y in enumerate(fin["years"]) if not str(y).endswith("E")][-5:]
    if not idx:
        return None

    def col(k):
        arr = fin.get(k) or []
        return [_n(arr[i]) if i < len(arr) else None for i in idx]
    rev, op, ni, ocf, fcf = col("revenue"), col("opinc"), col("netinc"), col("ocf"), col("fcf")
    L = -1
    out = {
        "source": "WISEfn(연간 확정치)", "years": [str(fin["years"][i]) for i in idx], "ttm_end": None,
        "op_margin_y": [_pct(a, b) for a, b in zip(op, rev)], "net_margin_y": [_pct(a, b) for a, b in zip(ni, rev)],
        "fcf_margin_y": [_pct(a, b) for a, b in zip(fcf, rev)], "capex_rev_y": [None] * len(idx),
        "tax_rate_y": [None] * len(idx), "shares_y": None, "rev_y": rev, "divest_y": None, "acq_y": None,
        "rev": rev[L], "op_income": op[L], "net_income": ni[L], "nonop": None, "pretax": None, "tax": None,
        "ocf": ocf[L], "capex": (ocf[L] - fcf[L]) if (ocf[L] is not None and fcf[L] is not None) else None,
        "fcf": fcf[L], "da": None, "acq": None, "divest": None, "buyback": None, "dividends": None, "sbc": None,
        "op_margin": _pct(op[L], rev[L]), "net_margin": _pct(ni[L], rev[L]), "ocf_margin": _pct(ocf[L], rev[L]),
        "fcf_margin": _pct(fcf[L], rev[L]), "capex_rev": None, "capex_da": None,
        "fcf_conv": (fcf[L] / ni[L]) if (fcf[L] is not None and ni[L] and ni[L] > 0) else None,
        "tax_rate": None, "unit": 1, "unit_lbl": "억원",
    }
    if out["capex"] is not None:
        out["capex_rev"] = _pct(out["capex"], rev[L])
        out["capex_rev_y"] = [_pct((o - f) if (o is not None and f is not None) else None, r)
                              for o, f, r in zip(ocf, fcf, rev)]
    return out


def _avg(xs):
    xs = [x for x in (xs or []) if x is not None]
    return sum(xs) / len(xs) if xs else None


def _money(v, F):
    if v is None:
        return None
    if F["unit_lbl"] == "B":
        return f"${v / 1e9:,.1f}B"
    return f"{v:,.0f}억원"


# ───────────────────────── PSR 밴드 (E) ─────────────────────────
def _band(ser, years, today):
    if years:
        cut = today.replace(year=today.year - years).isoformat()
        s = [p for p in ser if p["d"] >= cut]
        if len(s) < 10:
            s = ser
    else:
        s = ser
    v = [p["psr"] for p in s]
    n = len(v)
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / n)
    cur = v[-1]
    first, lastd = dt.date.fromisoformat(s[0]["d"]), dt.date.fromisoformat(s[-1]["d"])
    expect = years * 52.18 if years else (lastd - first).days / 7 + 1
    return {"span": f"{years}년" if years else "전체", "weeks": n, "expected_weeks": round(expect),
            "mean": round(m, 2), "sd": round(sd, 2), "cur": round(cur, 2),
            "z": round((cur - m) / sd, 2) if sd else 0.0,
            "pctl": round(sum(1 for x in v if x <= cur) / n * 100),
            "back_pct": round((m / cur - 1) * 100, 1) if cur else None,
            "start": s[0]["d"]}


def _cagr(a, b, yrs):
    return ((b / a) ** (1 / yrs) - 1) * 100 if (a and b and a > 0 and b > 0 and yrs > 0) else None


def _rev_growth_phases(rev_ttm):
    """분기별 TTM 매출 → 자료 첫 3년·최근 3년 연평균 성장률(%) + 각 기간 표기."""
    if not rev_ttm or len(rev_ttm) < 16:
        return None, None, None, None
    pts = [(dt.date.fromisoformat(r["d"]), r["v"]) for r in rev_ttm]

    def at(target):
        return min(pts, key=lambda p: abs((p[0] - target).days))
    s0 = pts[0]
    e0 = at(s0[0] + dt.timedelta(days=round(3 * 365.25)))
    s1 = at(pts[-1][0] - dt.timedelta(days=round(3 * 365.25)))
    return (_cagr(s0[1], e0[1], (e0[0] - s0[0]).days / 365.25),
            _cagr(s1[1], pts[-1][1], (pts[-1][0] - s1[0]).days / 365.25),
            f"{s0[0].year}~{e0[0].year}", f"{s1[0].year}~{pts[-1][0].year}")


# ───────────────────────── 본체 ─────────────────────────
def build_facts(a, psr=None, fin_us=None, today=None):
    C = CONFIG
    today = today or dt.date.today()
    ps = a.get("peg_sales") or {}
    kr = a.get("currency") == "KRW"
    F = _fin_kr(a.get("financials")) if kr else _fin_us(fin_us)
    flags = []
    per_t = _n(a.get("per_ttm")) if (_n(a.get("per_ttm")) or 0) > 0 else None
    per_f = _n(a.get("per_fwd")) if (_n(a.get("per_fwd")) or 0) > 0 else None
    G = {g["key"]: g["value"] * 100 for g in (ps.get("growth") or []) if _n(g.get("value")) is not None}
    g_this = G.get("y0", G.get("e1"))
    g_next = G.get("y1", G.get("e2"))
    g_two = G.get("y2", G.get("cagr2"))
    rf = ps.get("rev_fwd") or []
    rev_g_ttm = _n(ps.get("rev_growth_ttm"))
    rev_g_ttm = rev_g_ttm * 100 if rev_g_ttm is not None else None
    rev_g_this = _n(rf[0]["growth"]) * 100 if (len(rf) > 0 and _n(rf[0].get("growth")) is not None) else None
    rev_g_next = _n(rf[1]["growth"]) * 100 if (len(rf) > 1 and _n(rf[1].get("growth")) is not None) else None
    psr_ttm = _n(ps.get("psr"))
    psr_next = _n(rf[-1].get("psr")) if rf else None
    btype, blabel = biz_type(a.get("sector"), a.get("industry"), ps.get("gross_margin"))
    financial = btype == "financial"
    net_m = F["net_margin"] if F else None
    fcf_m = F["fcf_margin"] if F else None
    panel_fcf = _n(ps.get("fcf_margin")) * 100 if _n(ps.get("fcf_margin")) is not None else None
    panel_op = _n(ps.get("op_margin")) * 100 if _n(ps.get("op_margin")) is not None else None
    op_m = F["op_margin"] if (F and F.get("op_margin") is not None) else panel_op
    profitable = (per_t is not None) or (net_m is not None and net_m > 0)
    implied_nm = (psr_ttm / per_t * 100) if (psr_ttm and per_t) else None

    # ── A. 이익의 질 ──
    one_off = False
    if F and not financial:
        nonop_share = (F["nonop"] / F["net_income"]) if (F.get("nonop") is not None and F.get("net_income") and F["net_income"] > 0) else None
        gap = (net_m - op_m) if (net_m is not None and op_m is not None) else None
        if (gap is not None and gap >= C["one_off_net_minus_op_pp"]) or \
           (nonop_share is not None and nonop_share >= C["one_off_nonop_share"]):
            one_off = True
            flags.append(_flag("one_off_gain", "alert", "일회성 이익 의심",
                               {"순이익률(%)": _r(net_m), "영업이익률(%)": _r(op_m),
                                "PSR÷PER로 역산한 순이익률(%)": _r(implied_nm),
                                "최근 12개월 영업외손익": _money(F.get("nonop"), F),
                                "영업외손익÷순이익(%)": _r(nonop_share * 100 if nonop_share is not None else None),
                                "최근 12개월 순이익": _money(F.get("net_income"), F)},
                               "순이익이 본업(영업이익)보다 크게 부풀어 있어요. 지분·투자자산 평가이익 같은 영업외 이익이 섞였을 수 있어, 현재(TTM) PER·PEG가 실제보다 싸게 보입니다."))
        tr_avg = _avg(F["tax_rate_y"][:-1]) if F.get("tax_rate_y") else None
        if F.get("tax_rate") is not None and tr_avg is not None and abs(F["tax_rate"] - tr_avg) >= C["tax_gap_pp"]:
            flags.append(_flag("tax_anomaly", "info", "세율이 평소와 다름",
                               {"최근 12개월 실효세율(%)": _r(F["tax_rate"]), "이전 연도 평균(%)": _r(tr_avg)},
                               "세금이 평소보다 " + ("적게" if F["tax_rate"] < tr_avg else "많이")
                               + " 잡혀 순이익이 " + ("부풀었을" if F["tax_rate"] < tr_avg else "눌렸을") + " 수 있어요(일회성 세금 효과 가능성)."))
    per_inv = False
    if per_t and per_f and per_t < per_f and (g_this or 0) > 0 and (g_next or 0) > 0:
        per_inv = True
        flags.append(_flag("per_inversion", "warn", "PER 역전(현재 < 예상)",
                           {"현재 PER": _r(per_t), "예상 PER": _r(per_f), "올해 EPS 성장률(%)": _r(g_this), "내년 EPS 성장률(%)": _r(g_next)},
                           "이익이 늘 거라는데 예상 PER이 현재 PER보다 높다는 건 모순이에요. 최근 12개월 이익에 일회성 요인이 섞였을 가능성이 큽니다."))
    normalize = one_off or per_inv
    per_norm = per_f if (normalize and per_f) else None

    # ── B. 현금 창출 ──
    heavy = neg_fcf = fcf_anom = False
    if F and not financial:
        cx_avg = _avg(F["capex_rev_y"][:-1]) if F.get("capex_rev_y") else None
        if op_m is not None and fcf_m is not None and op_m - fcf_m >= C["heavy_capex_gap_pp"] and \
           ((F.get("capex_rev") is not None and cx_avg and F["capex_rev"] >= cx_avg * C["heavy_capex_vs_avg"]) or
                (F.get("capex_da") or 0) >= C["heavy_capex_to_da"]):
            heavy = True
            flags.append(_flag("heavy_capex", "warn", "대규모 설비투자 중",
                               {"영업이익률(%)": _r(op_m), "FCF 마진(%)": _r(fcf_m), "설비투자": _money(F.get("capex"), F),
                                "설비투자÷매출(%)": _r(F.get("capex_rev")), "이전 평균 설비투자÷매출(%)": _r(cx_avg),
                                "설비투자÷감가상각(배)": _r(F.get("capex_da"))},
                               "벌어들인 영업현금 대부분을 설비(데이터센터 등)에 다시 넣고 있어요. 이 투자가 몇 년 안에 매출·이익으로 돌아오느냐가 핵심 질문입니다."))
        fcf_avg = _avg(F["fcf_margin_y"])
        cur_fcf = panel_fcf if panel_fcf is not None else fcf_m
        if cur_fcf is not None and fcf_avg is not None and cur_fcf <= fcf_avg - C["fcf_anomaly_pp"] and \
           not (F.get("capex_rev") is not None and cx_avg and F["capex_rev"] >= cx_avg * C["fcf_anomaly_capex_normal"]):
            fcf_anom = True
            acq = F.get("acq")
            ev = {"화면 FCF 마진(%)": _r(cur_fcf), "5년 평균 FCF 마진(%)": _r(fcf_avg),
                  "최근 12개월 FCF 마진(%)": _r(fcf_m), "연도별 FCF 마진(%)": dict(zip(F["years"], [_r(x) for x in F["fcf_margin_y"]]))}
            if acq and F.get("rev") and acq / F["rev"] >= C["big_acquisition_share"]:
                ev["최근 12개월 인수 지출"] = _money(acq, F)
            hint = "설비투자는 평소 수준인데 현금이 덜 들어왔어요. 인수 대금·세금·소송·일회성 지급 같은 현금 유출 가능성이 있어 현금흐름표의 영업활동 세부 항목을 확인해야 해요."
            if fcf_m is not None and fcf_m >= fcf_avg - C["fcf_anomaly_pp"] / 2:
                hint += " 최근 12개월 기준으로는 이미 회복된 모습이라, 화면 값(직전 회계연도 기준)이 일시적으로 낮게 보이는 것일 수 있어요."
            flags.append(_flag("fcf_anomaly", "warn", "FCF가 평소보다 낮음", ev, hint))
        if (fcf_m is not None and fcf_m < 0) or (panel_fcf is not None and panel_fcf < 0):
            neg_fcf = True
            only_panel = fcf_m is not None and fcf_m >= 0
            flags.append(_flag("negative_fcf", "warn" if heavy else "alert",
                               "FCF 마이너스" + ("(화면 기준) · 공시 기준도 0에 가까움" if only_panel else ""),
                               {"최근 12개월 FCF": _money(F.get("fcf"), F), "최근 12개월 FCF 마진(%)": _r(fcf_m), "화면 FCF 마진(%)": _r(panel_fcf)},
                               ("화면(야후) 기준 FCF는 마이너스, 최근 12개월 공시 기준도 매출의 몇 % 수준이에요. 영업현금 대부분이 설비투자로 나가고 있다는 뜻이에요."
                                if only_panel else "영업으로 번 현금보다 설비투자 등으로 나간 돈이 더 많아요.")
                               + (" 투자 확대 때문이라면 일시적일 수 있어요." if heavy else "")))
        if panel_op is not None and op_m is not None and abs(panel_op - op_m) >= 8:
            flags.append(_flag("panel_basis_op", "info", "화면 영업이익률과 기준 차이",
                               {"화면 영업이익률(야후 최근 12개월, %)": _r(panel_op), F["source"] + " 영업이익률(%)": _r(op_m),
                                "재무 기준 연도": F["years"][-1] if kr else F.get("ttm_end")},
                               "화면 카드와 이 해석의 영업이익률 기간이 달라요." + (" 국내 종목은 연간 확정치라, 최근 이익이 급변한 경우 화면(최근 12개월)이 더 최신이에요." if kr else "")))
        if panel_fcf is not None and fcf_m is not None and abs(panel_fcf - fcf_m) >= 5:
            flags.append(_flag("panel_basis", "info", "화면 FCF와 기준 차이",
                               {"화면 FCF 마진(야후, %)": _r(panel_fcf), "최근 12개월 FCF 마진(공시, %)": _r(fcf_m)},
                               "위 매출 카드의 FCF 마진은 야후 기준(주로 직전 회계연도)이라 최근 12개월 공시 숫자와 기간이 달라요."))

    # ── C. 매출과 이익의 방향 ──
    rd_eu = regime = False
    if rev_g_next is not None and rev_g_next < 0 and (g_next or 0) > 0:
        rd_eu = True
        conf, poss = [], []
        sh = F.get("shares_y") if F else None
        sh_chg = None
        if sh and sh[0] and sh[-1]:
            sh_chg = (sh[-1] / sh[0] - 1) * 100
        if sh_chg is not None and sh_chg <= -C["share_shrink_pct"]:
            conf.append(f"희석 주식수 {len(sh)}년간 {abs(sh_chg):.1f}% 감소(자사주 효과)")
        else:
            poss.append("자사주 매입")
        om = F.get("op_margin_y") if F else None
        om_chg = (om[-1] - om[0]) if (om and om[0] is not None and om[-1] is not None) else None
        if om_chg is not None and om_chg >= 2:
            conf.append(f"영업이익률 {om_chg:+.1f}%p 상승(마진 확대)")
        else:
            poss.append("비용 절감·마진 확대")
        dvs = []                                   # (기간, 금액) — 최근 12개월 + 최근 2개 회계연도
        if F and F.get("divest"):
            dvs.append(("최근 12개월", F["divest"]))
        if F and F.get("divest_y"):
            dvs += [(y, v) for y, v in zip(F["years"][-2:], F["divest_y"][-2:]) if v]
        big = [(k, v) for k, v in dvs if F.get("rev") and v / F["rev"] >= 0.01]
        if big:
            k, v = max(big, key=lambda x: x[1])
            conf.append(f"사업·자산 매각 수입 {_money(v, F)}({k})")
        else:
            poss.append("저마진 사업 매각·리프랜차이징")
        flags.append(_flag("revenue_down_eps_up", "warn", "매출은 줄고 이익은 늘어남",
                           {"내년 매출 성장률(%)": _r(rev_g_next), "내년 EPS 성장률(%)": _r(g_next),
                            "희석 주식수 변화(%)": _r(sh_chg), "영업이익률 변화(%p)": _r(om_chg),
                            "확인됨": conf or None, "가능성": poss or None},
                           "매출이 줄어도 이익이 느는 건 보통 ① 자사주 매입 ② 저마진 사업 매각·리프랜차이징 ③ 비용 절감 때문이에요. 데이터로 확인된 것: "
                           + (", ".join(conf) if conf else "없음") + ". 나머지는 가능성이라 공시로 확인이 필요해요. 매출 기반이 줄면 PSR 밴드는 착시를 만들어요."))
    if F and F.get("op_margin_y"):
        om = [x for x in F["op_margin_y"] if x is not None]
        if len(om) >= 3 and abs(om[-1] - om[0]) >= C["margin_regime_pp"]:
            regime = True
            flags.append(_flag("margin_regime_change", "warn", "이익 구조가 달라짐",
                               {"연도별 영업이익률(%)": dict(zip(F["years"], [_r(x) for x in F["op_margin_y"]]))},
                               "영업이익률이 몇 년 사이 크게 바뀌어, 과거 PSR 밴드(같은 매출에 남는 이익이 달랐던 시기)와 지금을 직접 비교하기 어려워요."))

    # ── D. PEG 견고성 ──
    pers = [("ttm", "현재 PER", per_t), ("fwd", "예상 PER" + (" (정상화)" if normalize else ""), per_f)]
    gs = [("this", "올해", g_this, "y0" if "y0" in G else "e1"), ("next", "내년", g_next, "y1" if "y1" in G else "e2"),
          ("two", "2년 평균", g_two, "y2" if "y2" in G else "cagr2")]
    if G.get("ltg") is not None:
        gs.append(("ltg", "장기(5년)", G["ltg"], "ltg"))

    def band(p):
        return "cheap" if p < C["peg_cheap"] else ("fair" if p <= C["peg_expensive"] else "expensive")
    matrix, vals = [], []
    for bk, bl, pv in pers:
        if not pv:
            continue
        for gk, gl, gv, chip in gs:
            if gv is None:
                continue
            ok = gv >= C["peg_min_growth_pct"]
            peg = pv / gv if ok else None
            base = ok and gv > C["peg_base_effect_pct"]
            matrix.append({"basis": bk, "basis_label": bl, "per": _r(pv), "g_key": chip, "g_label": gl, "g": _r(gv),
                           "peg": _r(peg, 2), "band": band(peg) if peg is not None else None,
                           "note": ("이익 감소 예상" if gv < 0 else "성장률 1% 미만 — 의미 없음") if not ok
                           else ("성장률 50% 초과 — 기저효과로 PEG가 지나치게 낮게 나옴" if base else None),
                           "paired": (bk, gk) in (("ttm", "this"), ("fwd", "next")),
                           "distorted": (bk == "ttm" and normalize) or base})
            if peg is not None and not (bk == "ttm" and normalize) and not base:
                vals.append(peg)
    ypeg = _n(ps.get("yahoo_peg"))
    if ypeg and ypeg > 0 and vals:          # 일반 조합이 하나도 없으면(전부 기저효과) 야후 값도 같은 왜곡이라 제외
        vals.append(ypeg)
    peg_rec = next((m for m in matrix if m["basis"] == "fwd" and m["g_key"] in ("y1", "e2") and m["peg"] is not None and not m["distorted"]), None) \
        or next((m for m in matrix if m["paired"] and m["peg"] is not None and not m["distorted"]), None)
    peg_info = {"matrix": matrix, "yahoo_5y": _r(ypeg, 2), "min": _r(min(vals), 2) if vals else None,
                "max": _r(max(vals), 2) if vals else None,
                "recommended": peg_rec, "normalized": normalize}
    based = [m for m in matrix if m["peg"] is not None and m["note"] and "기저효과" in m["note"]]
    if based and not financial:
        flags.append(_flag("peg_base_effect", "info", "EPS 급반등 — PEG 과소 주의",
                           {"성장률(%)": {m["g_label"]: m["g"] for m in based}},
                           "이익이 바닥에서 급반등하는 해에는 성장률이 수십~수백 %라 PEG가 0에 가깝게 나와요. 이런 조합은 판정에서 뺐어요(경기순환 업종이면 PBR·PER 밴드가 더 적합)."))
    if vals and not financial:
        bands = {band(v) for v in vals}
        ev = {"PEG 최소": peg_info["min"], "PEG 최대": peg_info["max"], "야후 5년 PEG": peg_info["yahoo_5y"],
              "권장 조합": f'{peg_rec["basis_label"]} ÷ {peg_rec["g_label"]} = {peg_rec["peg"]}' if peg_rec else None}
        if len(bands) >= 2:
            flags.append(_flag("peg_unstable", "warn", "PEG 결론이 성장률 가정에 민감",
                               ev, f"어떤 PER·성장률을 쓰느냐에 따라 PEG가 {peg_info['min']}~{peg_info['max']}로 갈려요. "
                               "결론이 '싸다·적정·비싸다' 사이를 오가므로, 내년 이익 성장을 믿느냐가 관건입니다."))
        elif bands == {"expensive"}:
            flags.append(_flag("peg_robust_expensive", "warn", "PEG: 어떻게 계산해도 비쌈", ev,
                               f"모든 조합에서 PEG가 {C['peg_expensive']:g}를 넘어요. 성장률 가정을 바꿔도 성장 대비 가격이 높다는 결론은 같습니다."))
        elif bands == {"cheap"}:
            flags.append(_flag("peg_robust_cheap", "info", "PEG: 어떻게 계산해도 쌈", ev,
                               "모든 조합에서 PEG가 1 미만이에요. 다만 성장 예상이 실제로 나와야 한다는 전제가 붙어요."))

    # ── E. PSR 밴드 ──
    bands_out, psr_dir = None, None
    early = extreme = brk = gap = False
    ser = (psr or {}).get("series") or []
    if len(ser) >= 20:
        bands_out = {k: _band(ser, y, today) for k, y in (("all", 0), ("y5", 5), ("y3", 3))}
        b_all, b5 = bands_out["all"], bands_out["y5"]
        g_early, g_recent, p_early, p_recent = _rev_growth_phases((psr or {}).get("rev_ttm"))
        bands_out["rev_growth_phases"] = {"자료 첫 3년": {"기간": p_early, "연평균 매출 성장률(%)": _r(g_early)},
                                          "최근 3년": {"기간": p_recent, "연평균 매출 성장률(%)": _r(g_recent)}}
        if b5["mean"] and b_all["mean"] >= b5["mean"] * C["early_inflation_mean_ratio"] and b_all["start"] < b5["start"] and \
           g_early is not None and g_recent is not None and g_early - g_recent >= C["early_growth_gap_pp"]:
            early = True
            flags.append(_flag("early_growth_inflation", "warn", "전체 기간 PSR 평균이 부풀려짐",
                               {"전체 평균 PSR": b_all["mean"], "5년 평균 PSR": b5["mean"],
                                f"자료 첫 3년({p_early}) 매출 성장률(%/년)": _r(g_early), f"최근 3년({p_recent}) 매출 성장률(%/년)": _r(g_recent),
                                "전체 기준 평균 회귀 시(%)": b_all["back_pct"], "5년 기준 평균 회귀 시(%)": b5["back_pct"]},
                               "전체 기간 평균에는 초고성장기에 받던 높은 PSR이 섞여 있어요. 그 평균으로 돌아간다는 계산은 과대하니 5년·3년 기준을 우선 보세요."))
        zs = {b["span"]: b["z"] for b in (bands_out["all"], bands_out["y5"], bands_out["y3"])}
        zmax = max(zs.values(), key=abs)
        if abs(zmax) >= C["extreme_sigma"]:
            extreme = True
            flags.append(_flag("extreme_band", "warn" if zmax > 0 else "info",
                               "PSR이 역사적 " + ("상단(+2σ 이상)" if zmax > 0 else "하단(−2σ 이하)"),
                               {"구간별 σ 위치": zs, "현재 PSR": b5["cur"], "5년 백분위(%)": b5["pctl"]},
                               "매출 대비 주가가 과거 범위의 " + ("맨 위" if zmax > 0 else "맨 아래") + "에 있어요. "
                               + ("이익 구조가 좋아졌거나 기대가 크게 반영된 상태예요." if zmax > 0 else "시장이 성장 둔화·위험을 반영하고 있을 수 있어요.")))
        # 구조 이탈: 최근 52주가 직전 3년 박스권 밖
        cut52 = (today - dt.timedelta(days=365)).isoformat()
        cut4 = (today - dt.timedelta(days=365 * 4)).isoformat()
        last = [p["psr"] for p in ser if p["d"] >= cut52]
        box = [p["psr"] for p in ser if cut4 <= p["d"] < cut52]
        if len(last) >= 26 and len(box) >= 100:
            hi, lo, cur = max(box), min(box), last[-1]
            up = sum(1 for x in last if x > hi) / len(last)
            dn = sum(1 for x in last if x < lo) / len(last)
            if (cur > hi and up >= C["break_share"]) or (cur < lo and dn >= C["break_share"]):
                brk = True
                flags.append(_flag("structural_break", "warn", "PSR이 3년 박스권을 " + ("위로" if cur > hi else "아래로") + " 이탈",
                                   {"직전 3년 PSR 범위": f"{lo:.1f}~{hi:.1f}", "현재 PSR": round(cur, 2),
                                    "최근 52주 중 박스 밖 비율(%)": round((up if cur > hi else dn) * 100)},
                                   "최근 1년 PSR이 과거 범위를 한 방향으로 벗어났어요. 시장이 이 회사를 다시 평가(리레이팅)했거나, 매출 구조가 바뀌었을 가능성이 있어요."))
        gaps = [b for b in (bands_out["y5"], bands_out["y3"]) if b["weeks"] < b["expected_weeks"] * C["data_gap_ratio"]]
        if gaps:
            gap = True
            print(f"[val_rules] PSR 데이터 누락: {a.get('ticker')} " + ", ".join(f"{b['span']} {b['weeks']}/{b['expected_weeks']}주" for b in gaps))
            flags.append(_flag("data_gap", "info", "과거 PSR 데이터 일부 누락",
                               {b["span"]: f"{b['weeks']}주 / 기대 {b['expected_weeks']}주" for b in gaps},
                               "공시 매출·주식수가 빠진 구간이 있어 밴드 통계가 덜 정확할 수 있어요."))
    if psr_ttm and psr_next:
        psr_dir = "down" if psr_next < psr_ttm * 0.99 else ("up" if psr_next > psr_ttm * 1.01 else "flat")

    # ── F. 지표 추천 ──
    g_rev = rev_g_next if rev_g_next is not None else (rev_g_ttm if rev_g_ttm is not None else rev_g_this)
    structural = rd_eu or regime
    if financial:
        rec = ("PBR(주가순자산비율)", None, "은행·보험은 매출·영업이익 개념이 일반 기업과 달라 PSR·EV/매출이 맞지 않아요. 자기자본 대비 가격(PBR)과 ROE로 봐야 하는데, 이 카드의 범위 밖이에요.", "financial")
    elif normalize:
        rec = ("예상 PER", "EV/EBITDA", "최근 12개월 순이익에 일회성 요인이 섞여 현재 PER이 왜곡됐어요. 이익이 정상화된 예상 PER과, 영업외 손익을 빼고 보는 EV/EBITDA가 더 정확해요.", "one_off")
    elif structural and profitable and (g_rev is None or g_rev < C["mature_growth_pct"]):
        rec = ("PER 밴드", "배당수익률" if btype in ("staples", "utility") else "PEG",
               "매출 기반이 구조적으로 바뀌는 중이라(매출 감소·이익 구조 변화) PSR 밴드는 착시를 만들어요. 이익 기준인 PER 밴드로 보는 게 더 적합해요.", "per_band")
    elif based and profitable and per_t and (a.get("cyclical") or btype in ("semis", "hardware", "commodity")):
        rec = ("PER 밴드(사이클 평균 이익 기준)", "PBR", "이익이 바닥에서 급반등하는 경기순환 구간이라 PEG가 0에 가깝게 나와 의미가 약해요. 호황·불황을 합친 평균 이익 기준의 PER 밴드와 PBR로 보는 게 안전해요.", "cycle")
    elif heavy or neg_fcf:
        rec = ("PER(정상화) + 투자 회수 체크", "PSR", "대규모 투자로 FCF가 일시적으로 눌려 있어 P/FCF(현금흐름 배수)는 참고에서 빼는 게 좋아요. 이익(PER)으로 보면서 투자가 매출로 돌아오는지 확인하세요.", "capex")
    elif profitable and g_rev is not None and g_rev >= C["high_growth_pct"] and (fcf_m is None or fcf_m > 0):
        rec = ("PEG", "PSR", "이익을 내면서 빠르게 크는 기업이라 성장 대비 가격(PEG)과 매출 배수(PSR)를 같이 봐요.", "growth")
    elif (not profitable) or (net_m is not None and net_m < C["thin_margin_pct"] and (g_rev or 0) >= C["high_growth_pct"]):
        rec = ("PSR / EV/매출", None, "아직 이익이 없거나 아주 작아 PER·PEG가 의미 없어요. 매출 배수와 매출 성장률, 매출총이익률로 봐요.", "sales")
    elif btype in ("staples", "utility") and (g_rev is None or g_rev < C["mature_growth_pct"]):
        rec = ("PER 밴드", "배당수익률", "이익이 안정적인 성숙 기업은 이익(PER)과 배당 기준으로 봐요.", "per_band")
    else:
        rec = ("PEG", "PER 밴드", "이익을 꾸준히 내는 기업이라 성장 대비 가격(PEG)과 과거 PER 범위를 함께 봐요.", "default")
    recommend = {"primary": rec[0], "secondary": rec[1], "reason": rec[2], "kind": rec[3],
                 "per_band_link": "PER 밴드" in rec[0] or (rec[1] or "").startswith("PER 밴드")}

    # Rule of 40 (G)
    r40 = None
    if rev_g_ttm is not None and panel_fcf is not None:
        r40v = rev_g_ttm + panel_fcf
        active = btype in ("software", "highmargin", "platform", "semis") and rev_g_ttm >= C["rule40_min_growth_pct"]
        r40 = {"value": _r(r40v), "applies": active,
               "note": ("성장 기술기업의 기준선(40)으로 해석할 수 있어요." if active
                        else "이 업종·성장 단계에서는 참고 지표 정도로만 봐요.")}

    # ── H. 4가지 판정 ──
    score, why = 0.0, []
    b5 = (bands_out or {}).get("y5")
    if b5:
        w = 0.5 if structural else 1.0
        z = b5["z"]
        s = 2 if z >= 2 else (1 if z >= C["psr_z_exp"] else (-2 if z <= -2 else (-1 if z <= C["psr_z_cheap"] else 0)))
        score += s * w
        why.append(f"5년 PSR {z:+.1f}σ")
    if peg_rec and peg_rec["peg"] is not None:
        robust = any(f["id"].startswith("peg_robust") for f in flags)
        s = (-1 if peg_rec["peg"] < 1 else (1 if peg_rec["peg"] > 2 else 0)) * (2 if robust else 1)
        score += s
        why.append(f"권장 PEG {peg_rec['peg']}")
    if financial:
        val = "판단 보류"
    else:
        val = "비싸다" if score >= 2 else ("싸다" if score <= -2 else "적정")
    if one_off or per_inv:
        qual = "의심"
    elif F and F.get("fcf_conv") is not None and F["fcf_conv"] >= 0.8 and not any(f["id"] == "tax_anomaly" for f in flags):
        qual = "좋음"
    else:
        qual = "보통"
    if heavy:
        cash = "투자 중"
    elif fcf_m is None:
        cash = "판단 보류"
    else:
        cash = "강함" if fcf_m >= C["cash_strong_fcf_pct"] else "약함"
    if g_rev is None:
        grow = "판단 보류"
    elif g_rev < 0:
        grow = "역성장"
    elif rev_g_ttm is not None and g_rev - rev_g_ttm >= C["growth_accel_pp"]:
        grow = "가속"
    elif rev_g_ttm is not None and g_rev - rev_g_ttm <= C["growth_slow_pp"]:
        grow = "둔화"
    else:
        grow = "유지"
    verdicts = {"valuation": val, "quality": qual, "cash": cash, "growth": grow, "valuation_basis": " · ".join(why) or None}

    def r1(x):
        return _r(x, 1)
    metrics = {
        "price": a.get("price"), "currency": a.get("currency"),
        "per_ttm": r1(per_t), "per_fwd": r1(per_f), "per_normalized": r1(per_norm),
        "eps_growth": {"올해": r1(g_this), "내년": r1(g_next), "2년 평균": r1(g_two), "장기": r1(G.get("ltg"))},
        "psr_ttm": _r(psr_ttm, 2), "psr_next": _r(psr_next, 2), "ev_sales": _r(_n(ps.get("ev_s")), 2),
        "forward_psr_direction": psr_dir,
        "rev_growth": {"최근 12개월": r1(rev_g_ttm), "올해": r1(rev_g_this), "내년": r1(rev_g_next)},
        "gross_margin": r1(_n(ps.get("gross_margin")) * 100 if _n(ps.get("gross_margin")) is not None else None),
        "op_margin": r1(op_m), "op_margin_panel": r1(panel_op), "net_margin": r1(net_m),
        "implied_net_margin": r1(implied_nm),
        "fcf_margin": r1(fcf_m), "fcf_margin_panel": r1(panel_fcf),
        "ocf_margin": r1(F.get("ocf_margin")) if F else None, "capex_to_revenue": r1(F.get("capex_rev")) if F else None,
        "capex_to_da": _r(F.get("capex_da"), 2) if F else None, "fcf_conversion": _r(F.get("fcf_conv"), 2) if F else None,
        "fcf_margin_5y_avg": r1(_avg(F["fcf_margin_y"])) if F else None,
        "rule_of_40": r40,
    }
    if F:
        metrics["ttm_amounts"] = {k: _money(F.get(k), F) for k in ("rev", "op_income", "net_income", "nonop", "ocf", "capex", "fcf", "da", "acq", "divest", "buyback", "dividends", "sbc")}
        metrics["annual"] = {"연도": F["years"], "영업이익률(%)": [r1(x) for x in F["op_margin_y"]],
                             "FCF 마진(%)": [r1(x) for x in F["fcf_margin_y"]], "설비투자÷매출(%)": [r1(x) for x in F["capex_rev_y"]]}
    if financial:      # 은행·보험은 PSR 개념이 맞지 않아 PSR 밴드 진단은 숨김(숫자는 psr_bands에 남김)
        flags = [x for x in flags if x["id"] not in ("extreme_band", "structural_break", "early_growth_inflation", "data_gap")]
    order = {"alert": 0, "warn": 1, "info": 2}
    flags.sort(key=lambda f: order[f["level"]])
    return {
        "ticker": a.get("ticker"), "name": a.get("name"), "asof": today.isoformat(),
        "sector": a.get("sector"), "industry": a.get("industry"), "biz_type": blabel,
        "fin_source": F["source"] if F else None, "ttm_end": F.get("ttm_end") if F else None,
        "metrics": metrics, "peg": peg_info, "psr_bands": bands_out, "flags": flags,
        "recommend": recommend, "verdicts": verdicts, "config_version": 1,
    }


# ───────────────────────── 템플릿 문장(LLM 실패·키 없음 폴백) ─────────────────────────
def template_text(f):
    v, m, rec = f["verdicts"], f["metrics"], f["recommend"]
    ids = {x["id"]: x for x in f["flags"]}
    head = {"싸다": "숫자상 싼 편이에요", "비싸다": "숫자상 비싼 편이에요", "적정": "가격은 적정 범위예요",
            "판단 보류": "이 카드의 지표로는 판단하기 어려워요"}[v["valuation"]]
    tail = {"의심": " — 단, 이익에 일회성 요인 의심", "투자 중": ""}.get(v["quality"], "")
    if v["cash"] == "투자 중" and not tail:
        tail = " — 대규모 투자 회수가 관건"
    cheap, exp = [], []
    b5 = (f.get("psr_bands") or {}).get("y5")
    if b5:
        (cheap if b5["z"] < 0 else exp).append(f"5년 PSR 평균 대비 {b5['z']:+.1f}σ(백분위 {b5['pctl']}%)")
    pr = (f["peg"] or {}).get("recommended")
    if pr and pr["peg"] is not None:
        (cheap if pr["peg"] < 1 else exp if pr["peg"] > 2 else cheap if pr["peg"] < 1.5 else exp).append(
            f"{pr['basis_label']} ÷ {pr['g_label']} EPS 성장률 = PEG {pr['peg']}")
    if m.get("fcf_margin") is not None and m["fcf_margin"] >= 15:
        cheap.append(f"FCF 마진 {m['fcf_margin']}%로 현금 창출력이 좋아요")
    illusions = [{"title": x["title"], "body": x["hint"]} for x in f["flags"] if x["level"] in ("alert", "warn")][:3]
    for x in f["flags"]:
        if x["id"] in ("one_off_gain", "per_inversion", "heavy_capex", "negative_fcf", "revenue_down_eps_up",
                       "structural_break", "peg_unstable") and len(exp) < 3:
            exp.append(x["title"])
    check = []
    if "one_off_gain" in ids:
        check.append("손익계산서 › 영업외손익(기타수익) 세부 내역")
    if "heavy_capex" in ids or "negative_fcf" in ids:
        check.append("현금흐름표 › 투자활동 › 유형자산 취득(설비투자) 추이와 회사의 투자 가이던스")
    if "fcf_anomaly" in ids:
        check.append("현금흐름표 › 영업활동 › 일회성 지급(인수 대금·세금·소송) 항목")
    if "revenue_down_eps_up" in ids:
        check.append("공시 › 사업 매각·리프랜차이징 계획과 주식수 변화")
    if not check:
        check.append("최근 분기 실적 발표의 내년 가이던스")
    lesson = {("비싸다", "좋음"): "좋은 회사 ≠ 좋은 가격", ("싸다", "의심"): "싸 보이는 PER은 이익의 질부터 확인"}.get(
        (v["valuation"], v["quality"]), "한 가지 지표가 아니라 지표 사이의 모순을 보자")
    q = {"capex": "지금의 대규모 투자가 몇 년 안에 매출·이익으로 돌아올까?",
         "one_off": "일회성 이익을 빼고 나면 이 회사의 진짜 이익 성장률은 얼마일까?",
         "per_band": "매출이 줄어도 이익 성장이 계속될 수 있을까?",
         "sales": "적자를 벗어날 때까지 매출 성장이 유지될까?"}.get(rec["kind"], "내년 이익 성장 예상이 실제로 나올까?")
    return {"one_line": head + tail, "cheap_reasons": cheap[:3], "expensive_reasons": exp[:3],
            "illusions": illusions, "metric_advice": f"1순위는 {rec['primary']}" + (f", 보조로 {rec['secondary']}" if rec["secondary"] else "") + f". {rec['reason']}",
            "key_question": q, "checklist": check[:3], "lesson": lesson}
