"""HTML(Jinja2) → PNG(Playwright) 렌더링 + 간단 점검.

카드 1: 핵심지표 (2×2) — 매출 성장률 / 부문별 성장률 / 이익률 / 잉여현금흐름
해석 문구(형광펜)는 숫자에서 규칙으로 만든다. 지어낸 해석·매수매도 표현은 쓰지 않는다.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

import charts

ROOT = Path(__file__).resolve().parent
SIZES = {"1080x1080": (1080, 1080), "1080x1350": (1080, 1350), "1920x1080": (1920, 1080)}
N_SHOW = 6
INK = "#1A1A1A"
FONT_URL = None  # 웹(밸류AI)에서 쓸 때 폰트 주소. 없으면 이 컴퓨터의 assets/fonts


def font_url() -> str:
    return FONT_URL or (ROOT / "assets" / "fonts").as_uri()


# ---------- 숫자 표기 ----------

def money(v, cur, dec=1) -> str:
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if cur == "USD":
        return f"{sign}${a / 1e9:,.{dec}f}B"
    if a >= 1e12:
        return f"{sign}{a / 1e12:,.{dec}f}조"
    return f"{sign}{a / 1e8:,.0f}억"


def pct(v, plus=True) -> str:
    if v is None:
        return "—"
    s = "+" if plus and v > 0 else ""
    return f"{s}{v:,.0f}%" if abs(v) >= 100 else f"{s}{v:.1f}%"


def pp(v) -> str:
    return f"{'+' if v > 0 else ''}{v:.1f}%p"


def short_label(r) -> str:
    """x축: 12월 결산 '25.3Q', 아니면 'FY27 1Q'"""
    lab = r["label"]
    if lab.startswith("FY"):
        return lab.split(" (")[0]
    y, q = lab.split()
    return f"{y[2:]}.{q}"


def layout(W, H) -> dict:
    L = {"pad": 34, "header_h": 138 if H <= 1080 else 160, "footer_h": 70, "gap": 22,
         "ppad": 16, "title_h": 64, "hl_h": 40}
    grid_w = W - 2 * L["pad"]
    grid_h = H - 2 * L["pad"] - L["header_h"] - L["footer_h"] - 2 * 16
    pw = (grid_w - L["gap"]) / 2
    ph = (grid_h - L["gap"]) / 2
    L["chart_w"] = int(pw - 6 - 2 * L["ppad"])
    L["chart_h"] = int(ph - 6 - 2 * L["ppad"] - L["title_h"] - L["hl_h"] - 2 * 6)
    return L


def brand(data) -> tuple[str, str]:
    cfg = yaml.safe_load((ROOT / "config" / "brands.yaml").read_text()) or {}
    b = cfg.get(data["ticker"]) or cfg.get(str(data["ticker"])) or {}
    name = data.get("name_display") or b.get("name") or data.get("name_ko") or data.get("name_en")
    return name, b.get("color") or cfg.get("default", "#2563EB")


# ---------- 패널 만들기 ----------

def _consec_rises(vals) -> int:
    k = 0
    for a, b in zip(vals[-2::-1], vals[::-1]):
        if a is None or b is None or b <= a:
            break
        k += 1
    return k


def panel_revenue(qs, cur, L):
    yoy = [r["m"].get("revenue_yoy") for r in qs]
    last = qs[-1]
    svg = charts.line_chart(L["chart_w"], L["chart_h"], [short_label(r) for r in qs],
                            [{"values": yoy, "color": INK, "pos": "above"}], pct)
    v = [x for x in yoy if x is not None]
    note, tone = None, "pos"
    if len(v) >= 2:
        k = _consec_rises(yoy)
        if v[-1] < v[-2]:
            note, tone = f"성장 속도 둔화: {pct(v[-2])} → {pct(v[-1])}", "neg"
        elif k >= 2:
            note = f"성장률 {k}분기 연속 빨라졌어요"
        else:
            note = f"전년 같은 분기보다 매출 {pct(v[-1])}"
    return {"icon": "📈", "title": "매출 성장률",
            "sub": f"전년 같은 분기 대비 · 이번 분기 매출 <i>{money(last['values'].get('revenue'), cur)}</i>",
            "callout": pct(last["m"].get("revenue_yoy")), "svg": svg, "note": note, "tone": tone,
            "key": "revenue"}


def panel_segments(qs, cur, L, data=None):
    last = qs[-1]
    segs = [s for s in last.get("segments", []) if not s.get("hide_growth") and s.get("yoy") is not None]
    # 금액 없이 성장률만 공개된 항목(예: MS Azure)을 같이 보여 줌
    gy = (data or {}).get("series_yoy", {})
    q, pq = last["calendar_quarter"], None
    if qs[-2:-1]:
        pq = qs[-2]["calendar_quarter"]
    for name in (data or {}).get("growth_in_panel", []):
        h = gy.get(name, {})
        if q in h:
            segs.append({"name": name, "yoy": h[q], "prev_yoy": h.get(pq), "growth_only": True})
    if segs:
        segs.sort(key=lambda s: s["yoy"], reverse=True)
        def sub(s):
            t = "성장률만 공개" if s.get("growth_only") else f"매출 {money(s.get('revenue'), cur)}"
            if s.get("prev_yoy") is not None:
                arrow = "▼" if s["yoy"] < s["prev_yoy"] - 1 else ("▲" if s["yoy"] > s["prev_yoy"] + 1 else "")
                t += f" · 직전 {pct(s['prev_yoy'])}{arrow}"
            return t
        rows = [{"name": s["name"], "sub": sub(s), "value": s["yoy"]} for s in segs]
        svg = charts.hbar_chart(L["chart_w"], L["chart_h"], rows, pct)
        top = segs[0]
        neg = [s for s in last.get("segments", []) if s.get("op") is not None and s["op"] < 0]
        # 가장 큰 부문이 직전 분기보다 2%p 넘게 둔화하면 그게 이번 분기 이야기
        big = max(segs, key=lambda s: s.get("revenue") or 0)
        worst = min(segs, key=lambda s: s["yoy"])
        slow = (big is not top and big.get("prev_yoy") is not None
                and big["yoy"] < big["prev_yoy"] - 2)
        if worst["yoy"] < 0 and worst.get("prev_yoy") is not None and worst["yoy"] < worst["prev_yoy"] - 2:
            note, tone = f"{top['name']} {pct(top['yoy'])} · {worst['name']} {pct(worst['yoy'])}", "neg"
        elif slow:
            note, tone = (f"{top['name']} {pct(top['yoy'])} · {big['name']} 둔화 "
                          f"{big['prev_yoy']:.0f}→{big['yoy']:.0f}%"), "neg"
        elif neg:
            n = neg[0]
            note, tone = f"{top['name']}가 끌고, {n['name']}는 영업적자 {money(-n['op'], cur)}", "neg"
        else:
            note, tone = f"{top['name']} {pct(top['yoy'])}로 가장 빠르게 성장", "pos"
        return {"icon": "🧩", "title": "부문별 매출 성장률", "sub": "전년 같은 분기 대비",
                "callout": None, "svg": svg, "note": note, "tone": tone, "key": "segment",
                "top_yoy": top["yoy"]}
    # 부문 입력이 없으면: 영업이익 성장률
    oy = [r["m"].get("operating_income_yoy") for r in qs]
    svg = charts.bar_chart(L["chart_w"], L["chart_h"], [short_label(r) for r in qs], oy, pct)
    v = last["values"].get("operating_income")
    note = f"이번 분기 영업이익 {money(v, cur)}" if v is not None else None
    return {"icon": "💰", "title": "영업이익 성장률",
            "sub": "전년 같은 분기 대비 · 부문 실적은 수동 입력 시 표시",
            "callout": pct(last["m"].get("operating_income_yoy")), "svg": svg,
            "note": note, "tone": "pos", "key": "segment"}


def panel_margins(qs, cur, L, color):
    gpm = [r["m"].get("gpm") for r in qs]
    opm = [r["m"].get("opm") for r in qs]
    fmt = lambda v: f"{v:.1f}%"  # noqa: E731
    series = []
    has_g = any(x is not None for x in gpm)
    if has_g:
        series.append({"values": gpm, "color": color, "pos": "above"})
    series.append({"values": opm, "color": INK, "pos": "below" if has_g else "above"})
    svg = charts.line_chart(L["chart_w"], L["chart_h"], [short_label(r) for r in qs], series, fmt)
    m = qs[-1]["m"]
    legend = (f'<span style="color:{color}">●</span> 매출총이익률 · <span>●</span> 영업이익률'
              if has_g else "영업이익 ÷ 매출")
    note, tone = None, "pos"
    if m.get("opm") is not None:
        d = m.get("opm_yoy_pp")
        note = f"영업이익률 {m['opm']:.1f}%" + (f", 전년보다 {pp(d)}" if d is not None else "")
        tone = "neg" if d is not None and d < 0 else "pos"
    return {"icon": "📊", "title": "이익률", "sub": legend,
            "callout": f"{m['opm']:.1f}%" if m.get("opm") is not None else None,
            "callout_dark": True, "svg": svg, "note": note, "tone": tone, "key": "margin"}


def panel_cash(qs, cur, L):
    fcf = [r["values"].get("fcf") for r in qs]
    svg = charts.bar_chart(L["chart_w"], L["chart_h"], [short_label(r) for r in qs],
                           fcf, lambda v: money(v, cur))
    have = [r for r in qs if r["values"].get("fcf") is not None]
    if not have:
        return {"icon": "💵", "title": "잉여현금흐름", "sub": "영업현금흐름 − 설비투자", "callout": None,
                "svg": svg, "note": None, "tone": "pos", "key": "cash"}
    r = have[-1]
    v = r["values"]
    is_last = r is qs[-1]
    sub = f"영업현금 {money(v['operating_cash_flow'], cur)} − 설비투자 {money(v['capex'], cur)}"
    if not is_last:
        sub = f"{short_label(r)} 기준 · " + sub
        note, tone = f"{short_label(qs[-1])} 현금흐름은 분기보고서 공시 후 반영", "pos"
    elif v["fcf"] < 0:
        note, tone = f"설비투자가 영업현금보다 {money(-v['fcf'], cur)} 많아요", "neg"
    else:
        note, tone = f"번 현금의 {r['m'].get('capex_to_ocf', 0):.0f}%를 다시 투자했어요", "pos"
    return {"icon": "💵", "title": "잉여현금흐름", "sub": sub,
            "callout": money(v["fcf"], cur), "callout_dark": v["fcf"] >= 0,
            "svg": svg, "note": note, "tone": tone, "key": "cash", "fcf_neg": v["fcf"] < 0 and is_last}


def pick_hot(panels, data):
    want = data.get("highlight")
    if not want:
        rev, seg, cash = panels[0], panels[1], panels[3]
        ry = data["quarters"][-1]["m"].get("revenue_yoy") or 0
        if seg.get("top_yoy") is not None and seg["top_yoy"] >= max(30, 2 * ry):
            want = "segment"
        elif cash.get("fcf_neg"):
            want = "cash"
        else:
            want = "revenue"
    for p in panels:
        p["hot"] = p["key"] == want


def source_text(data) -> str:
    qs = data["quarters"][-N_SHOW:]
    auto = [r for r in qs if not r.get("manual")]
    base = "SEC EDGAR XBRL" if data["market"] == "US" else "OpenDART 정기보고서(연결)"
    if not any(r.get("manual") for r in qs):
        t = f"{base} ({short_label(qs[0])}~{short_label(qs[-1])})"
        return t + (f" · 부문 등: {data['manual_source']}" if data.get("manual_source") else "")
    parts = []
    if auto:
        parts.append(f"{base} ({short_label(auto[0])}~{short_label(auto[-1])})")
    parts.append(data["manual_source"])
    return " · ".join(parts)


def qtitle(r) -> str:
    lab = r["label"]
    if lab.startswith("FY"):
        return lab
    y, q = lab.split()
    return f"{y}년 {q[0]}분기"


# ---------- 렌더링 ----------

def build_metrics_html(data: dict, size: str) -> str:
    W, H = SIZES[size]
    L = layout(W, H)
    qs = data["quarters"][-N_SHOW:]
    cur = data["currency"]
    name, color = brand(data)
    panels = [panel_revenue(qs, cur, L), panel_segments(qs, cur, L, data),
              panel_margins(qs, cur, L, color), panel_cash(qs, cur, L)]
    pick_hot(panels, data)
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    css = env.get_template("base.css").render(W=W, H=H, L=L,
                                              font_dir=font_url())
    last = qs[-1]
    foot = None
    if last.get("status") == "잠정":
        foot = "이번 분기는 감사 전 잠정치로 바뀔 수 있어요"
    elif last.get("manual"):
        foot = "이번 분기는 회사 실적 발표 자료 기준(감사 전)"
    return env.get_template("metrics.html").render(
        css=css, name=name, color=color, ticker=data["ticker"], qtitle=qtitle(last),
        status=last.get("status"), nq=len(qs), panels=panels, source=source_text(data),
        footnote=foot)


def to_png(html: str, out_dir: Path, stem: str, size: str) -> tuple[Path, dict]:
    """HTML → PNG + 품질 점검·자동 보정 (qc.py). 반환: (PNG 경로, {before, fixed, after})"""
    import qc
    W, H = SIZES[size]
    return qc.render(html, out_dir, stem, W, H)
