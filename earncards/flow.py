"""돈의 흐름 카드 — "얼마 벌고 어디에 썼나" 생키(Sankey) 다이어그램.

두 방식 (설계서 4장):
- cost           : 부문 매출 → 매출 → 매출총이익/매출원가 → 영업이익/영업비용 → 비용 항목 (미국식)
- segment_profit : 흑자 부문 영업이익 → 합계 → 전사 영업이익, 적자 부문은 빨간 흐름으로 빠짐 (한국식)
YAML flow_mode 가 없으면: 부문 영업이익은 있는데 원가 자료가 없으면 segment_profit, 아니면 cost.
아래 띠: "매출 100으로 보면" (cost) / "매출 비중 vs 이익 비중" 두 줄 (segment_profit).
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from render import font_url as render_font_url, SIZES, brand, qtitle, source_text
from story import PALETTE as _SP, won

# 이 카드에서 빨강은 '비용·적자' 뜻이라 부문 색에서 빨강을 뺀다
PALETTE = [(bg, {"#E03131": "#E67700", "#C92A2A": "#D6336C"}.get(fg, fg), rib) for bg, fg, rib in _SP]

ROOT = Path(__file__).resolve().parent
INK, MUTED = "#1A1A1A", "#6B645A"
GREEN, GREEN_L = "#2B8A3E", "#B2F2BB"
RED, RED_L = "#E03131", "#FFC9C9"
NODE_W = 18


def _pct(v):
    if v is None:
        return ""
    if abs(v) < 0.05:
        return "보합"
    return f"{v:+.0f}%" if abs(v) >= 100 else f"{v:+.1f}%"


def _ribbon(x0, a0, a1, x1, b0, b1, color, opacity=0.85):
    mx = (x0 + x1) / 2
    return (f'<path d="M{x0:.1f},{a0:.1f} C{mx:.1f},{a0:.1f} {mx:.1f},{b0:.1f} {x1:.1f},{b0:.1f} '
            f'L{x1:.1f},{b1:.1f} C{mx:.1f},{b1:.1f} {mx:.1f},{a1:.1f} {x0:.1f},{a1:.1f} Z" '
            f'fill="{color}" opacity="{opacity}"/>')


def _node(x, y, h, color):
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{NODE_W}" height="{max(3, h):.1f}" rx="3" '
            f'fill="{color}" stroke="{INK}" stroke-width="2.5"/>')


def _t(x, y, s, size, weight, fill, anchor):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" class="lbl">{escape(s)}</text>')


def _label(x, y, lines, anchor, valign="middle"):
    """lines: [(글자, 크기, 굵기, 색)] — y 는 가운데(middle)/아래 끝(bottom)/위 끝(top) 기준"""
    hs = [sz * 1.18 for _, sz, _, _ in lines]
    total = sum(hs)
    top = {"middle": y - total / 2, "bottom": y - total, "top": y}[valign]
    out, cy = [], top
    for (s, sz, w, c), h in zip(lines, hs):
        cy += h
        if s:
            out.append(_t(x, cy - h * 0.22, s, sz, w, c, anchor))
    return '<g class="grp">' + "".join(out) + "</g>"


def _relax(centers, min_gap, lo, hi):
    """라벨 가운데 y 들을 겹치지 않게 벌린다 (순서 유지)."""
    ys = list(centers)
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + min_gap)
    over = ys[-1] - hi if ys else 0
    if over > 0:
        ys = [y - over for y in ys]
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = min(ys[i], ys[i + 1] - min_gap)
    return [max(lo, y) for y in ys]


def pick_mode(data) -> str:
    last = data["quarters"][-1]
    segs = last.get("segments", [])
    has_seg_op = any(s.get("op") is not None and s["op"] > 0 for s in segs)
    if data.get("flow_mode") == "segment_profit" and not has_seg_op:
        return "cost"  # 그 분기에 부문 이익 자료가 없으면(예: 지난 분기 보기) 원가 흐름으로
    if data.get("flow_mode"):
        return data["flow_mode"]
    if any(s.get("op") is not None for s in segs) and "cost_of_revenue" not in last["values"]:
        return "segment_profit"
    return "cost"


# ---------- cost 방식 ----------

def _cost_items(v, cur):
    """영업비용 세부 [(이름, 짧은 이름, 값)] + 영업비용 합계"""
    opex = None
    if v.get("gross_profit") is not None and v.get("operating_income") is not None:
        opex = v["gross_profit"] - v["operating_income"]
    elif v.get("operating_expenses") is not None:
        opex = v["operating_expenses"]
    items = [(n, s, v[k]) for k, n, s in (("rnd", "연구개발비", "R&D"),
                                          ("sales_marketing", "판매·마케팅", "마케팅"),
                                          ("general_admin", "일반관리비", "관리"))
             if v.get(k) is not None]
    if not items and v.get("sga") is not None:
        items = [("판매관리비", "판관비", v["sga"])]
    if opex is not None and items:
        gap = opex - sum(x[2] for x in items)
        if abs(gap) > 0.01 * opex:
            items.append(("기타 영업비용", "기타", gap))
    if len(items) == 1 and opex is not None and abs(items[0][2] - opex) <= 0.01 * opex:
        items = []  # 영업비용 = 판관비 하나뿐이면 세부 칸은 생략
    return opex, items


def build_cost(data, w, h):
    last = data["quarters"][-1]
    v, m, cur = last["values"], last["m"], data["currency"]
    rev = v["revenue"]
    gp = v.get("gross_profit")
    op = v["operating_income"]
    cogs = v.get("cost_of_revenue")
    opex, items = _cost_items(v, cur)
    by_q = {r["calendar_quarter"]: r for r in data["quarters"]}
    y, q = int(last["calendar_quarter"][:4]), last["calendar_quarter"][-1]
    ly = by_q.get(f"{y - 1}Q{q}", {}).get("values", {})

    def yoy_of(cur_v, key):
        b = ly.get(key)
        return _pct((cur_v / b - 1) * 100) if b else ""

    segs = sorted([s for s in last.get("segments", []) if s.get("revenue")],
                  key=lambda s: s["revenue"], reverse=True)
    small = [s for s in segs if s["revenue"] < 0.02 * rev]
    segs = [s for s in segs if s not in small]
    if small:
        segs.append({"name": "기타", "revenue": sum(s["revenue"] for s in small), "yoy": None, "_other": True})
    if segs:
        gap = rev - sum(s["revenue"] for s in segs)
        if abs(gap) > 0.01 * rev:
            segs.append({"name": "기타/조정", "revenue": gap, "yoy": None, "_other": True})

    has_seg = bool(segs)
    has_gp = gp is not None and cogs is not None
    n_cols = 2 + (1 if has_gp else 0) + (1 if items else 0)  # 매출 + (총이익) + 영업이익 + (비용 세부)
    if has_seg:  # 1080 기준(그림 폭 974) 좌표를 실제 폭에 맞춰 늘림 — 왼쪽 라벨 칸 200, 오른쪽 라벨 칸 ~175는 고정
        sx = (w - 175 - 200) / (800 - 200)
        cols = [200 + (c - 200) * sx for c in [200, 360, 530, 690, 800]][:n_cols + 1]
    else:  # 부문 칸이 없으면 열을 가로 폭에 고르게
        left, right = 110, w - 230
        step = (right - left) / (n_cols - 1)
        cols = [None] + [left + i * step for i in range(n_cols)]
    out, labels = [], []
    k = h * 0.62 / rev
    R = k * rev
    rev_top = max(h * 0.16, 108)  # 맨 위 영업이익 라벨(3줄)이 그림 위로 안 나가게
    xr = cols[1]
    # 매출 노드
    out_nodes = [_node(xr, rev_top, R, INK)]
    labels.append(_label(xr + NODE_W / 2, rev_top - 10, [
        ("매출", 16, 800, INK), (won(rev, cur), 26, 900, INK),
        (f"전년 대비 {_pct(m.get('revenue_yoy'))}", 13, 700, MUTED)], "middle", "bottom"))

    # 부문 → 매출
    if has_seg:
        g = 10
        tot = R + g * (len(segs) - 1)
        yy = rev_top + R / 2 - tot / 2
        ty = rev_top
        centers, seg_lbl = [], []
        x0 = cols[0]
        for i, s in enumerate(segs):
            hh = k * s["revenue"]
            bg, fg, rib = (("#EEE8DD", MUTED, "#D9D2C3") if s.get("_other") else PALETTE[i % len(PALETTE)])
            out.append(_ribbon(x0 + NODE_W, yy, yy + hh, xr, ty, ty + hh, rib))
            out_nodes.append(_node(x0, yy, hh, fg))
            centers.append(yy + hh / 2)
            seg_lbl.append((s, fg))
            yy += hh + g
            ty += hh
        ys = _relax(centers, 40, 18, h - 18)
        for (s, fg), cy in zip(seg_lbl, ys):
            sub = won(s["revenue"], cur) + (f" · {_pct(s['yoy'])}" if s.get("yoy") is not None else "")
            labels.append(_label(x0 - 10, cy, [(s["name"], 15, 800, INK), (sub, 15, 800, fg)], "end"))

    x2 = cols[2]
    if has_gp:
        gp_top = rev_top - 14
        G = k * gp
        cogs_top = gp_top + G + 44
        C = k * cogs
        out.append(_ribbon(xr + NODE_W, rev_top, rev_top + G, x2, gp_top, gp_top + G, GREEN_L))
        out.append(_ribbon(xr + NODE_W, rev_top + G, rev_top + R, x2, cogs_top, cogs_top + C, RED_L))
        out_nodes += [_node(x2, gp_top, G, GREEN), _node(x2, cogs_top, C, RED)]
        labels.append(_label(x2 + NODE_W / 2, gp_top - 10, [
            ("매출총이익", 15, 800, INK), (won(gp, cur), 22, 900, GREEN),
            (f"이익률 {m['gpm']:.1f}%" if m.get("gpm") is not None else "", 13, 700, MUTED)], "middle", "bottom"))
        labels.append(_label(x2 + NODE_W / 2, cogs_top + C + 8, [
            ("매출원가", 15, 800, INK), (won(cogs, cur), 22, 900, RED),
            (f"매출의 {cogs / rev * 100:.1f}% · {yoy_of(cogs, 'cost_of_revenue')}", 13, 700, MUTED)], "middle", "top"))
        src_x, src_top, src_h, x3 = x2 + NODE_W, gp_top, G, cols[3]
    else:  # 영업수익−영업비용 구조: 매출에서 바로 영업이익/영업비용
        src_x, src_top, src_h, x3 = xr + NODE_W, rev_top, R, x2

    # 영업이익 / 영업비용
    O = k * op
    op_top = src_top - 12
    E = k * (opex or 0)
    ox_top = op_top + O + 38
    out.append(_ribbon(src_x, src_top, src_top + O, x3, op_top, op_top + O, GREEN_L))
    out_nodes.append(_node(x3, op_top, O, GREEN))
    d = m.get("opm_yoy_pp")
    labels.append(_label(x3 + NODE_W / 2, op_top - 10, [
        ("영업이익", 15, 800, INK), (won(op, cur), 22, 900, GREEN),
        (f"이익률 {m['opm']:.1f}%" + (f" · {d:+.1f}%p" if d is not None else ""), 13, 700, MUTED)],
        "middle", "bottom"))
    if opex:
        out.append(_ribbon(src_x, src_top + O, src_top + src_h, x3, ox_top, ox_top + E, RED_L))
        out_nodes.append(_node(x3, ox_top, E, RED))
        opx_name = "판매관리비" if (not items and v.get("sga") is not None
                                    and abs(v["sga"] - opex) <= 0.01 * opex) else "영업비용"
        opx_lbl = [(opx_name, 15, 800, INK), (won(opex, cur), 22, 900, RED),
                   (f"매출의 {opex / rev * 100:.1f}%", 13, 700, MUTED)]
        if items:  # 세부가 오른쪽에 있으면 라벨은 노드 아래
            labels.append(_label(x3 + NODE_W / 2, ox_top + E + 8, opx_lbl, "middle", "top"))
        else:
            labels.append(_label(x3 + NODE_W + 12, ox_top + E / 2, opx_lbl, "start"))

    # 비용 항목 (keys는 아래 '빨리 늘어난 비용' 문구에서도 씀 — 영업비용 합계가 없을 때도 정의돼 있어야 함)
    keys = {"연구개발비": "rnd", "판매·마케팅": "sales_marketing", "일반관리비": "general_admin",
            "판매관리비": "sga"}
    if items and opex:
        x4 = cols[4]
        g = 16
        tot = E + g * (len(items) - 1)
        yy = max(op_top, ox_top + E / 2 - tot / 2)
        sy = ox_top
        centers, meta = [], []
        for name, short, val in items:
            hh = k * val
            out.append(_ribbon(x3 + NODE_W, sy, sy + hh, x4, yy, yy + hh, RED_L))
            out_nodes.append(_node(x4, yy, hh, "#F76707" if name == "연구개발비" else "#FA5252"))
            centers.append(yy + hh / 2)
            meta.append((name, val, keys.get(name)))
            sy += hh
            yy += hh + g
        ys = _relax(centers, 64, 30, h - 30)
        for (name, val, key), cy in zip(meta, ys):
            yo = yoy_of(val, key) if key else ""
            labels.append(_label(x4 + NODE_W + 10, cy, [
                (name, 15, 800, INK), (won(val, cur), 20, 900, RED),
                (f"매출의 {val / rev * 100:.1f}%" + (f" · {yo}" if yo else ""), 13, 700, MUTED)], "start"))

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" class="chart">'
           + "".join(out) + "".join(out_nodes) + "".join(labels) + "</svg>")

    # 100으로 보면
    parts = []
    if has_gp:
        parts.append(("원가", cogs / rev * 100, RED))
    for name, short, val in items:
        parts.append((short, val / rev * 100, "#F76707" if short == "R&D" else "#FA5252"))
    if opex and not items:
        parts.append(("영업비용", opex / rev * 100, "#FA5252"))
    parts.append(("영업이익", op / rev * 100, GREEN))
    unit = "$" if cur == "USD" else "원"

    # 형광펜 문구
    notes = [(f"매출 100{unit} 벌면 영업이익으로 {op / rev * 100:.1f}{unit} 남아요", "pos")]
    ry = m.get("revenue_yoy")
    fast = []
    for name, short, val in items:
        key = keys.get(name) if items else None
        b = ly.get(key) if key else None
        if b and ry is not None:
            g_ = (val / b - 1) * 100
            if g_ > ry + 5:
                fast.append((g_, name))
    if fast:
        g_, name = max(fast)
        notes.append((f"{name} {_pct(g_)}, 매출({_pct(ry)})보다 빨리 늘어요", "neg"))
    elif has_gp and m.get("gpm_yoy_pp") is not None:
        d = m["gpm_yoy_pp"]
        notes.append((f"매출총이익률 {m['gpm']:.1f}%, 전년보다 {d:+.1f}%p", "neg" if d < 0 else "pos"))
    return svg, {"title": f"매출 100{unit}로 보면", "parts": parts, "unit": unit}, notes, "얼마 벌고 어디에 썼나"


# ---------- segment_profit 방식 ----------

def build_segment_profit(data, w, h):
    last = data["quarters"][-1]
    v, cur = last["values"], data["currency"]
    op = v["operating_income"]
    segs = [s for s in last.get("segments", []) if s.get("op") is not None]
    pos = sorted([s for s in segs if s["op"] > 0], key=lambda s: s["op"], reverse=True)
    neg = [s for s in segs if s["op"] < 0]
    sp = sum(s["op"] for s in pos)
    gap = op - (sp + sum(s["op"] for s in neg))
    outs = [{"name": f"{s['name']} 적자", "val": -s["op"], "seg": s} for s in neg]
    if abs(gap) > 0.01 * op:
        if gap < 0:
            outs.append({"name": "기타/조정", "val": -gap, "seg": None})
    k = h * 0.6 / sp
    x0, x2 = 230, w - 190
    x1 = (x0 + x2) / 2
    out, nodes, labels = [], [], []
    S = k * sp
    s_top = h * 0.2
    # 부문 → 합계
    g = 12
    tot = S + g * (len(pos) - 1)
    yy = s_top + S / 2 - tot / 2
    ty = s_top
    centers, meta = [], []
    for i, s in enumerate(pos):
        hh = k * s["op"]
        bg, fg, rib = PALETTE[i % len(PALETTE)]
        out.append(_ribbon(x0 + NODE_W, yy, yy + hh, x1, ty, ty + hh, rib))
        nodes.append(_node(x0, yy, hh, fg))
        centers.append(yy + hh / 2)
        meta.append((s, fg))
        yy += hh + g
        ty += hh
    ys = _relax(centers, 72, 30, h - 30)
    for (s, fg), cy in zip(meta, ys):
        opm = f"이익률 {s['op'] / s['revenue'] * 100:.0f}%" if s.get("revenue") else ""
        sub = " · ".join(x for x in (f"매출 {won(s.get('revenue'), cur)}" if s.get("revenue") else "", opm) if x)
        labels.append(_label(x0 - 10, cy, [(s["name"], 16, 800, INK), (won(s["op"], cur), 20, 900, fg),
                                           (sub, 12, 700, MUTED)], "end"))
    nodes.append(_node(x1, s_top, S, INK))
    labels.append(_label(x1 + NODE_W / 2, s_top - 10, [
        ("흑자 부문 이익 합계", 15, 800, INK), (won(sp, cur), 24, 900, INK)], "middle", "bottom"))
    # 합계 → 전사 영업이익 / 적자로 빠지는 몫
    O = k * op
    o_top = s_top - 10
    out.append(_ribbon(x1 + NODE_W, s_top, s_top + min(O, S), x2, o_top, o_top + O, GREEN_L))
    nodes.append(_node(x2, o_top, O, GREEN))
    m = last["m"]
    labels.append(_label(x2 + NODE_W + 12, o_top + O / 2, [
        ("전사 영업이익", 16, 800, INK), (won(op, cur), 26, 900, GREEN),
        (f"전년 대비 {_pct(m.get('operating_income_yoy'))}" if m.get("operating_income_yoy") is not None else "",
         13, 700, MUTED)], "start"))
    sy = s_top + min(O, S)
    oy = o_top + O + 60
    for o in outs:
        hh = max(5, k * o["val"])
        out.append(_ribbon(x1 + NODE_W, sy, sy + hh, x2, oy, oy + hh, "#FF8787", 0.95))
        nodes.append(_node(x2, oy, hh, RED))
        s = o["seg"]
        sub = ""
        if s and s.get("op_prev") is not None:
            sub = (f"전년 {won(s['op_prev'], cur)} 흑자 → 적자 전환" if s["op_prev"] > 0
                   else f"전년 {won(s['op_prev'], cur)}")
        labels.append(_label(x2 + NODE_W + 12, oy + hh / 2, [
            (o["name"], 15, 800, RED), (f"−{won(o['val'], cur)}", 22, 900, RED), (sub, 12, 700, MUTED)], "start"))
        sy += hh
        oy += hh + 70
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" class="chart">'
           + "".join(out) + "".join(nodes) + "".join(labels) + "</svg>")
    # 매출 비중 vs 이익 비중 (매출이 있는 부문만)
    color_of = {s["name"]: PALETTE[i % len(PALETTE)][1] for i, s in enumerate(pos)}
    order = pos + neg
    rev_tot = sum(s.get("revenue") or 0 for s in order)
    short = lambda n: n.split("(")[0]  # noqa: E731
    rows = []
    if rev_tot:
        rows.append(("매출", [(short(s["name"]), (s.get("revenue") or 0) / rev_tot * 100,
                              color_of.get(s["name"], "#ADB5BD")) for s in order]))
    rows.append(("이익", [(short(s["name"]), s["op"] / sp * 100, color_of[s["name"]]) for s in pos]))
    top = pos[0]
    notes = []
    if top.get("revenue") and rev_tot:
        notes.append((f"{short(top['name'])}: 매출의 {top['revenue'] / rev_tot * 100:.0f}% → "
                      f"흑자 이익의 {top['op'] / sp * 100:.0f}%", "pos"))
    else:
        notes.append((f"{top['name']}가 흑자 부문 이익의 {top['op'] / sp * 100:.0f}%", "pos"))
    for s in neg:
        if s.get("op_prev") is not None and s["op_prev"] > 0:
            notes.append((f"{s['name']} 적자 전환: {won(s['op_prev'], cur)} → −{won(-s['op'], cur)}", "neg"))
        else:
            notes.append((f"{s['name']} 영업적자 {won(-s['op'], cur)}", "neg"))
    return svg, {"title": "매출 비중 vs 이익 비중", "rows": rows, "unit": ""}, notes, "이익은 어디서 났나"




def _rows_svg(rows, w):
    """두 줄 비교 막대 (매출 비중 / 이익 비중) — 넓은 칸엔 '이름 70%' """
    label_w, bar_h, g = 46, 26, 10
    out = []
    for r, (title, parts) in enumerate(rows):
        y = 2 + r * (bar_h + g)
        out.append(_t(0, y + bar_h / 2 + 6, title, 15, 900, INK, "start"))
        tot = sum(p[1] for p in parts) or 1
        x = label_w
        for name, val, color in parts:
            pw = (w - label_w) * val / tot
            out.append(f'<rect x="{x:.1f}" y="{y}" width="{pw:.1f}" height="{bar_h}" fill="{color}" '
                       f'stroke="{INK}" stroke-width="2.5"/>')
            txt = f"{name} {val:.0f}%"
            if pw > len(txt) * 8.5 + 10:
                out.append(_t(x + pw / 2, y + bar_h / 2 + 5, txt, 14, 900, "#fff", "middle"))
            elif pw > len(f"{val:.0f}%") * 8.5 + 6:
                out.append(_t(x + pw / 2, y + bar_h / 2 + 5, f"{val:.0f}%", 13, 900, "#fff", "middle"))
            x += pw
    h = len(rows) * (bar_h + g) + 4
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" class="chart">'
            + "".join(out) + "</svg>")


def strip_svg(strip, w, h=66):
    """100으로 보면 — 가로 누적 막대 + 아래 이름 (rows 가 있으면 두 줄 비교)"""
    if strip.get("rows"):
        return _rows_svg(strip["rows"], w)
    parts = [p for p in strip["parts"] if p[1] > 0]
    tot = sum(p[1] for p in parts) or 1
    x = 0
    out = []
    bar_h = 34
    for name, val, color in parts:
        pw = w * val / tot
        out.append(f'<rect x="{x:.1f}" y="2" width="{pw:.1f}" height="{bar_h}" fill="{color}" '
                   f'stroke="{INK}" stroke-width="2.5"/>')
        num = f"{val:.1f}"
        if pw > len(num) * 9 + 8:
            out.append(_t(x + pw / 2, 2 + bar_h / 2 + 6, num, 17, 900, "#fff", "middle"))
        if pw > len(name) * 14 + 4:
            out.append(_t(x + pw / 2, bar_h + 24, name, 14, 800, INK, "middle"))
        elif pw > 18:
            out.append(_t(x + pw / 2, bar_h + 24, name[:2], 12, 800, INK, "middle"))
        x += pw
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" class="chart">'
            + "".join(out) + "</svg>")


def build_html(data: dict, size: str = "1080x1080") -> str:
    W, H = SIZES[size]
    pad, header_h, footer_h, gap = 34, 138, 70, 16
    strip_h = 150
    main_h = H - 2 * pad - header_h - footer_h - strip_h - 3 * gap
    sk_w, sk_h = W - 2 * pad - 6 - 32, main_h - 6 - 28
    mode = pick_mode(data)
    if mode == "segment_profit":
        svg, strip, notes, sub = build_segment_profit(data, sk_w, sk_h)
    else:
        svg, strip, notes, sub = build_cost(data, sk_w, sk_h)
    mascot = ROOT / "assets" / "mascot.png"
    strip_w = W - 2 * pad - 6 - 32 - (150 if mascot.exists() else 0)
    last = data["quarters"][-1]
    name, color = brand(data)
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    from render import layout
    css = env.get_template("base.css").render(W=W, H=H, L=layout(W, H),
                                              font_dir=render_font_url())
    foot = None
    if last.get("status") == "잠정":
        foot = "이번 분기는 감사 전 잠정치로 바뀔 수 있어요"
    elif last.get("manual"):
        foot = "이번 분기는 회사 실적 발표 자료 기준(감사 전)"
    return env.get_template("flow.html").render(
        css=css, W=W, H=H, name=name, color=color, ticker=data["ticker"], qtitle=qtitle(last),
        subtitle=sub, status=last.get("status"), main_h=main_h, strip_h=strip_h, svg=svg,
        strip_title=strip["title"], strip_svg=strip_svg(strip, strip_w), notes=notes,
        mascot=mascot.as_uri() if mascot.exists() else None,
        source=source_text(data), footnote=foot, mode=mode)
