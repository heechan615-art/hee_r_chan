"""이슈 카드 — "클라우드 2배인데 주가는 왜?" 같은 한 장짜리 이야기 카드.

구성: 질문형 제목 → 부문 매출 흐름(상자 → 띠 → 매출) + 한눈에 보기
      → 두 부문 성장률 비교 차트 + 주가 반응과 부담 요인 3가지
문구는 stories/{ticker}_{quarter}.yaml (Claude가 원문을 읽고 작성), 숫자·차트는 data 에서 자동.
"""
from __future__ import annotations

import re
from html import escape
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

import charts
from render import font_url as render_font_url, SIZES, brand, short_label

ROOT = Path(__file__).resolve().parent
# 부문 상자 색: (배경, 숫자, 띠)
PALETTE = [("#DDEBFF", "#1F5FD6", "#A8CBFF"), ("#FFF1C2", "#E03131", "#FFD666"),
           ("#ECE6FF", "#6741D9", "#C9B8FF"), ("#FFE3E6", "#C92A2A", "#FFB3BA"),
           ("#DDF8EA", "#087F5B", "#8CE6BF")]
TONE_ICON = {"positive": "✅", "caution": "⚠️", "negative": "❌", "neutral": "•"}


def path_for(ticker: str, quarter: str) -> Path:
    return ROOT / "stories" / f"{ticker}_{quarter}.yaml"


def load(ticker: str, quarter: str) -> dict | None:
    p = path_for(ticker, quarter)
    return yaml.safe_load(p.read_text()) if p.exists() else None


def won(v, cur) -> str:
    """한국식 큰 단위: 달러는 '1,276억$', 원은 '195.3조'"""
    if v is None:
        return "—"
    if cur == "USD":
        return f"{'-' if v < 0 else ''}{abs(v) / 1e8:,.0f}억$"
    return f"{v / 1e12:,.1f}조" if abs(v) >= 1e12 else f"{v / 1e8:,.0f}억"


def bold(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(s))


def _pct(v):
    return "—" if v is None else (f"{v:+.0f}%" if abs(v) >= 100 else f"{v:+.1f}%")


def _ribbon(x0, s_top, s_bot, x1, t_top, t_bot, color):
    mx = (x0 + x1) / 2
    return (f'<path d="M{x0:.1f},{s_top:.1f} C{mx:.1f},{s_top:.1f} {mx:.1f},{t_top:.1f} {x1:.1f},{t_top:.1f} '
            f'L{x1:.1f},{t_bot:.1f} C{mx:.1f},{t_bot:.1f} {mx:.1f},{s_bot:.1f} {x0:.1f},{s_bot:.1f} Z" '
            f'fill="{color}" opacity="0.9"/>')


def build_html(data: dict, st: dict, size: str = "1080x1080") -> str:
    W, H = SIZES[size]
    cur = data["currency"]
    last = data["quarters"][-1]
    v = last["values"]
    name, color = brand(data)
    pad = 44
    # 세로 배치
    top_mid = 182
    mid_h = int(H * 0.32)
    top_bot = top_mid + mid_h + 30
    foot_h = 74
    bot_h = H - top_bot - foot_h - 22

    # ---- 부문 상자 + 띠 ----
    segs = sorted([s for s in last.get("segments", []) if not s.get("hide_growth")],
                  key=lambda s: s.get("revenue") or 0, reverse=True)[:5]
    n = max(1, len(segs))
    total = sum(s["revenue"] for s in segs) or 1
    gap = 10
    # 1위 부문 상자만 크게, 나머지는 같은 높이
    big_h = min(108, mid_h * 0.31) if n > 1 else mid_h
    small_h = (mid_h - big_h - (n - 1) * gap) / max(1, n - 1)
    extra_w = W - 1080  # 넓은 화면(1920)에서는 부문 상자·띠·매출 상자도 같이 넓힘
    box_w = 250 + int(extra_w * 0.12)
    rev_w = 222 + int(extra_w * 0.06)
    rev_x = pad + box_w + 132 + int(extra_w * 0.22)
    if not last.get("segments"):  # 부문 자료가 없으면 매출 상자를 왼쪽에 크게
        rev_x, rev_w = pad + 20, 360 + int(extra_w * 0.15)
    rev_h = int(mid_h * 0.72)
    rev_y = top_mid + (mid_h - rev_h) / 2
    boxes, ribbons = [], []
    y = top_mid
    band_total = rev_h * 0.78
    ty = rev_y + (rev_h - band_total) / 2
    for i, s in enumerate(segs):
        if n <= 3:  # 부문이 적으면 매출 비중대로 (최소 80px)
            h = 80 + (mid_h - (n - 1) * gap - 80 * n) * s["revenue"] / total
        else:
            h = big_h if i == 0 else small_h
        bg, fg, rib = PALETTE[i % len(PALETTE)]
        trend = ""
        if s.get("prev_yoy") is not None and s.get("yoy") is not None:
            if s["yoy"] < s["prev_yoy"] - 2:
                trend = " · 둔화"
            elif s["yoy"] > s["prev_yoy"] + 5:
                trend = " · 가속 🔥"
        boxes.append({"x": pad, "y": y, "w": box_w, "h": h, "bg": bg, "fg": fg,
                      "icon": s.get("icon") or "", "name": s["name"], "value": won(s["revenue"], cur),
                      "sub": f"{_pct(s.get('yoy'))}{trend}", "big": i == 0})
        t = band_total * (s["revenue"] / (v.get("revenue") or total))
        st_h = min(h - 14, max(8, t))
        cy = y + h / 2
        ribbons.append(_ribbon(pad + box_w + 4, cy - st_h / 2, cy + st_h / 2, rev_x, ty, ty + t, rib))
        ty += t
        y += h + gap
    ribbon_svg = (f'<svg class="ribbons" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
                  + "".join(ribbons) + "</svg>")

    # ---- 매출 상자 ----
    m = last["m"]
    rev_box = {"x": rev_x, "y": rev_y, "w": rev_w, "h": rev_h,
               "value": won(v.get("revenue"), cur), "yoy": _pct(m.get("revenue_yoy")),
               "op": won(v.get("operating_income"), cur),
               "opm": f"{m['opm']:.1f}%" if m.get("opm") is not None else None}

    # ---- 한눈에 보기 ----
    sum_x = rev_x + rev_w + 66
    summary = {"x": sum_x, "y": top_mid, "w": W - pad - sum_x, "h": mid_h,
               "items": [{"icon": TONE_ICON.get(it.get("tone"), "•"), "html": bold(it["text"])}
                         for it in st.get("summary", [])],
               "sticker": st.get("sticker")}
    arrow = {"x0": rev_x + rev_w + 10, "x1": sum_x - 12, "y": rev_y + rev_h / 2}

    # ---- 성장률 비교 차트 ----
    tr = st.get("trend") or {}
    nq = int(tr.get("quarters", 4))
    qs = data["quarters"][-nq:]
    sy = data.get("series_yoy", {})
    series, legend = [], []
    for j, s in enumerate(tr.get("series", [])):
        vals = [sy.get(s["name"], {}).get(r["calendar_quarter"]) for r in qs]
        series.append({"values": vals, "color": s.get("color", "#2B6BE6"),
                       "pos": "above" if j == 0 else "below"})
        legend.append({"label": s.get("label", s["name"]), "color": s.get("color", "#2B6BE6")})
    half_w = (W - 2 * pad - 24) / 2
    chart_w, chart_h = int(half_w - 40), int(bot_h - 150)
    trend_svg = charts.line_chart(chart_w, chart_h, [short_label(r) for r in qs], series, _pct, arrow=False)

    # ---- 주가 반응 ----
    rc = st.get("reaction") or {}
    pr = data.get("price_reaction")
    move = None
    if pr and pr.get("close") and pr.get("after"):
        move = (pr["after"] / pr["close"] - 1) * 100
    reaction = {"title": rc.get("title", "그런데 주가는?"), "reasons_title": rc.get("reasons_title"),
                "move": f"{move:+.1f}%".replace("-", "−") if move is not None else None,
                "move_down": move is not None and move < 0,
                "when": pr.get("when") if pr else None,
                "price": (f"종가 {pr['close']:,.2f}$ → {pr['after']:,.2f}$" if pr else None),
                "reasons": rc.get("reasons", [])}
    mascot = ROOT / "assets" / "mascot.png"

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    return env.get_template("story.html").render(
        W=W, H=H, pad=pad, font_dir=render_font_url(),
        accent=st.get("title_accent", name), accent_color=color, title=st.get("title", ""),
        subtitle=st.get("subtitle", ""), boxes=boxes, ribbon_svg=ribbon_svg, rev=rev_box,
        summary=summary, arrow=arrow, top_bot=top_bot, bot_h=bot_h, half_w=half_w,
        trend_title=tr.get("title", ""), trend_sticker=tr.get("sticker"), legend=legend,
        trend_svg=trend_svg, reaction=reaction,
        mascot=mascot.as_uri() if mascot.exists() else None,
        source=st.get("sources") or data.get("manual_source", ""),
        status=last.get("status"))
