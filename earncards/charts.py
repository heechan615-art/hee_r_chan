"""SVG 차트 — 외부 라이브러리 없이 직접 그린다.

공통 규칙(설계서 2장): 선 8px 이상, 흰 속 원형 마커, 모든 포인트에 값 라벨,
마지막(이번 분기) 값은 빨간 굵은 라벨, 추세가 꺾이면 빨간 점선 화살표.
"""
from __future__ import annotations

from html import escape

RED = "#E03131"
INK = "#1A1A1A"
GRID = "#D9D2C3"
MUTED = "#6B645A"


def _svg(w, h, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" class="chart">'
            '<defs><marker id="ah" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" '
            f'markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{RED}"/></marker></defs>'
            f'{body}</svg>')


def _text(x, y, s, size, weight=700, fill=INK, anchor="middle", cls="lbl"):  # noqa: E302
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" class="{cls}">{escape(s)}</text>')


def _box(x, y, text, size, anchor):
    """글자 상자 추정 (x0, y0, x1, y1). 한글·숫자 평균 폭 ≈ 0.56em"""
    tw = len(text) * size * 0.56
    x0 = x - tw / 2 if anchor == "middle" else (x - tw if anchor == "end" else x)
    return (x0, y - size * 0.82, x0 + tw, y + size * 0.12)


def _seg_hits_box(p, q, b, pad=5):
    x0, y0, x1, y1 = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
    for t in range(0, 21):  # 선분을 20등분해서 확인 (충분히 촘촘함)
        x = p[0] + (q[0] - p[0]) * t / 20
        y = p[1] + (q[1] - p[1]) * t / 20
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return False


def _overlap(a, b, pad=3):
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def _place(x, y, text, size, prefer, segs, dots, taken, w, h):
    """선·마커·다른 라벨과 안 부딪히는 자리. prefer='above'|'below'"""
    up = [(0, -18, "middle"), (-12, -14, "end"), (12, -14, "start"), (0, -40, "middle")]
    dn = [(0, 34, "middle"), (-12, 30, "end"), (12, 30, "start"), (0, 54, "middle")]
    cands = up + dn if prefer == "above" else dn + up
    first = None
    for dx, dy, anc in cands:
        b = _box(x + dx, y + dy, text, size, anc)
        if b[0] < 2 or b[2] > w - 2 or b[1] < 2 or b[3] > h - 24:
            continue
        first = first or (dx, dy, anc, b)
        if any(_seg_hits_box(p, q, b) for p, q in segs):
            continue
        if any(_overlap(b, (cx - 11, cy - 11, cx + 11, cy + 11), 0) for cx, cy in dots):
            continue
        if any(_overlap(b, t) for t in taken):
            continue
        return dx, dy, anc, b
    if first:
        return first
    dx, dy, anc = cands[0]
    return dx, dy, anc, _box(x + dx, y + dy, text, size, anc)


def _xs(n, w, left, right):
    if n == 1:
        return [w / 2]
    step = (w - left - right) / (n - 1)
    return [left + i * step for i in range(n)]


def _range(vals, pad_top=0.18, pad_bot=0.18, include_zero=False):
    lo, hi = min(vals), max(vals)
    if include_zero:
        lo, hi = min(lo, 0), max(hi, 0)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    r = hi - lo
    return lo - r * pad_bot, hi + r * pad_top


def line_chart(w, h, xlabels, series, fmt, arrow=True) -> str:
    """series: [{'values': [...|None], 'color': '#..', 'pos': 'above'|'below', 'name': str}]"""
    n = len(xlabels)
    below = any(s.get("pos") == "below" for s in series)
    top, bot = 40, 64  # 아래 라벨(가장 낮은 점·두 번째 선) 한 줄 자리는 늘 남김
    left = right = 40
    allv = [v for s in series for v in s["values"] if v is not None]
    if not allv:
        return _svg(w, h, _text(w / 2, h / 2, "데이터 없음", 18, fill=MUTED))
    lo, hi = _range(allv, 0.08, 0.08)
    ys = lambda v: top + (hi - v) / (hi - lo) * (h - top - bot)  # noqa: E731
    xs = _xs(n, w, left, right)
    out = []
    # x축 라벨
    for i, lab in enumerate(xlabels):
        out.append(_text(xs[i], h - 8, lab, 15, 600, MUTED, cls="xl"))
    if min(allv) < 0 < max(allv):
        out.append(f'<line x1="{left - 20}" x2="{w - right + 20}" y1="{ys(0):.1f}" y2="{ys(0):.1f}" '
                   f'stroke="{MUTED}" stroke-width="2" stroke-dasharray="4 5"/>')
    segs, dots, taken, labels = [], [], [], []
    for s in series:
        pts = [(xs[i], ys(v)) for i, v in enumerate(s["values"]) if v is not None]
        segs += list(zip(pts, pts[1:]))
        dots += pts
    for s in series:
        pts = [(xs[i], ys(v), v) for i, v in enumerate(s["values"]) if v is not None]
        if len(pts) > 1:
            d = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}" for j, (x, y, _) in enumerate(pts))
            out.append(f'<path d="{d}" fill="none" stroke="{s["color"]}" stroke-width="8" '
                       'stroke-linecap="round" stroke-linejoin="round"/>')
        last_i = max(i for i, v in enumerate(s["values"]) if v is not None)
        for i, v in enumerate(s["values"]):
            if v is None:
                continue
            x, y = xs[i], ys(v)
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="#fff" '
                       f'stroke="{s["color"]}" stroke-width="5"/>')
            is_last = i == last_i and i == n - 1
            size = 22 if is_last else 18
            txt = fmt(v)
            pref = s.get("pos", "above")
            vv = s["values"]
            lv = vv[i - 1] if i > 0 else None
            rv = vv[i + 1] if i + 1 < n else None
            if pref == "above" and lv is not None and rv is not None and lv > v and rv > v:
                pref = "below"  # V자 바닥: 위는 양쪽 선이 막고 있어 아래로
            elif pref == "below" and lv is not None and rv is not None and lv < v and rv < v:
                pref = "above"  # ∧자 꼭대기
            dx, dy, anc, b = _place(x, y, txt, size, pref, segs, dots, taken, w, h)
            taken.append(b)
            labels.append(_text(x + dx, y + dy, txt, size, 800 if is_last else 700,
                                RED if is_last else INK, anc))
        # 추세 꺾임 화살표: 직전 두 구간 방향이 반대이고 마지막이 이번 분기
        vals = s["values"]
        if arrow and last_i == n - 1 and n >= 3 and None not in vals[-3:]:
            a, b, c = vals[-3:]
            if (b - a) * (c - b) < 0 and abs(c - b) > 0.03 * (hi - lo):
                x1, y1, x2, y2 = xs[-2], ys(b), xs[-1], ys(c)
                # 라벨 반대편(선 아래쪽 라벨이면 위로)에 그려서 글자와 안 겹치게
                off = 40 if s.get("pos", "above") == "above" else -36
                sx, sy = x1 + (x2 - x1) * 0.15, y1 + (y2 - y1) * 0.15 + off
                ex, ey = x1 + (x2 - x1) * 0.70, y1 + (y2 - y1) * 0.70 + off
                out.append(f'<path d="M{sx:.1f},{sy:.1f} L{ex:.1f},{ey:.1f}" stroke="{RED}" '
                           'stroke-width="4" stroke-dasharray="7 6" fill="none" marker-end="url(#ah)"/>')
    return _svg(w, h, "".join(out + labels))


def bar_chart(w, h, xlabels, values, fmt) -> str:
    """세로 막대. 음수는 빨강, 마지막 막대는 진하게 + 빨간 라벨."""
    n = len(xlabels)
    top, bot = 36, 34
    left = right = 10
    vals = [v for v in values if v is not None]
    if not vals:
        return _svg(w, h, _text(w / 2, h / 2, "데이터 없음", 18, fill=MUTED))
    neg = min(vals) < 0
    lo, hi = _range(vals, 0.20, 0.30 if neg else 0, include_zero=True)
    ys = lambda v: top + (hi - v) / (hi - lo) * (h - top - bot)  # noqa: E731
    slot = (w - left - right) / n
    bw = min(56, slot * 0.58)
    out = [f'<line x1="{left}" x2="{w - right}" y1="{ys(0):.1f}" y2="{ys(0):.1f}" '
           f'stroke="{INK}" stroke-width="3"/>']
    last = max(i for i, v in enumerate(values) if v is not None)
    for i, v in enumerate(values):
        cx = left + slot * (i + 0.5)
        out.append(_text(cx, h - 8, xlabels[i], 15, 600, MUTED, cls="xl"))
        if v is None:
            out.append(_text(cx, ys(0) - 12, "—", 16, 600, MUTED))
            continue
        y0, y1 = ys(0), ys(v)
        is_last = i == last
        if v < 0:
            fill = RED if is_last else "#F2A0A0"
        else:
            fill = INK if is_last else "#8C8478"
        out.append(f'<rect x="{cx - bw / 2:.1f}" y="{min(y0, y1):.1f}" width="{bw:.1f}" '
                   f'height="{max(2, abs(y1 - y0)):.1f}" rx="5" fill="{fill}" '
                   f'stroke="{INK}" stroke-width="2.5"/>')
        ly = y1 - 10 if v >= 0 else y1 + 24
        out.append(_text(cx, ly, fmt(v), 20 if is_last else 16, 800 if is_last else 700,
                         RED if is_last else INK))
    return _svg(w, h, "".join(out))


def hbar_chart(w, h, rows, fmt) -> str:
    """가로 막대. rows: [{'name', 'sub', 'value'}] — 1위는 빨강."""
    n = len(rows)
    if not n:
        return _svg(w, h, _text(w / 2, h / 2, "부문 데이터 없음", 18, fill=MUTED))
    name_w = 168
    row_h = min(48, h / n)
    top = (h - row_h * n) / 2
    vals = [r["value"] for r in rows]
    lo, hi = min(0, min(vals)), max(0, max(vals))
    span = (hi - lo) or 1
    lab_w = max(len(fmt(v)) for v in vals) * 21 * 0.6 + 14  # 가장 긴 값 라벨이 들어갈 자리
    bar_area = w - name_w - max(78, lab_w)
    xz = name_w + (-lo / span) * bar_area
    best = max(range(n), key=lambda i: vals[i])
    out = []
    for i, r in enumerate(rows):
        cy = top + row_h * (i + 0.5)
        out.append(_text(name_w - 12, cy + 1, r["name"], 18, 800, INK, "end"))
        if r.get("sub"):
            out.append(_text(name_w - 12, cy + 19, r["sub"], 13, 600, MUTED, "end"))
        bh = min(26, row_h * 0.58)
        xv = xz + r["value"] / span * bar_area
        x0, x1 = min(xz, xv), max(xz, xv)
        fill = RED if i == best else ("#F2A0A0" if r["value"] < 0 else "#8C8478")
        out.append(f'<rect x="{x0:.1f}" y="{cy - bh / 2 - 4:.1f}" width="{max(3, x1 - x0):.1f}" '
                   f'height="{bh:.1f}" rx="5" fill="{fill}" stroke="{INK}" stroke-width="2.5"/>')
        txt = fmt(r["value"])
        size = 21 if i == best else 18
        if r["value"] >= 0:
            lx, anc = x1 + 8, "start"
        elif x0 - 8 - len(txt) * size * 0.56 > name_w + 4:
            lx, anc = x0 - 8, "end"
        else:  # 왼쪽에 자리가 없으면 0선 오른쪽에
            lx, anc = xz + 8, "start"
        out.append(_text(lx, cy + 3, txt, size, 800, RED if i == best else INK, anc))
    out.append(f'<line x1="{xz:.1f}" x2="{xz:.1f}" y1="{top - 4:.1f}" y2="{top + row_h * n:.1f}" '
               f'stroke="{INK}" stroke-width="2"/>')
    return _svg(w, h, "".join(out))
