"""어닝콜 핵심 카드 — 말풍선 포인트 3~4개 + 경영진 발언 인용 (설계서 5장).

calls/{ticker}_{quarter}.json 은 Claude가 원문(calls/{ticker}_{quarter}.txt 어닝콜·기사, 또는
calls/{ticker}_{quarter}_release.txt 보도자료)을 읽고 작성한다. 외부 AI API는 쓰지 않는다.

검증(렌더링 전): 인용이 원문에 그대로 있는지(따옴표 모양·띄어쓰기 무시), 15단어 이내인지,
포인트 3~4개에 좋은 점·나쁜 점이 모두 있는지. 어기면 경고 → 파일 이름에 _CHECK.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from render import font_url as render_font_url, SIZES, brand, layout, qtitle

ROOT = Path(__file__).resolve().parent
TONE = {"positive": ("ok", "✓"), "negative": ("bad", "✓"), "neutral": ("mid", "•")}


def path_for(ticker: str, quarter: str) -> Path:
    return ROOT / "calls" / f"{ticker}_{quarter}.json"


def load(ticker: str, quarter: str) -> dict | None:
    p = path_for(ticker, quarter)
    return json.loads(p.read_text()) if p.exists() else None


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def originals(ticker: str, quarter: str) -> list[Path]:
    c = ROOT / "calls"
    return [p for p in (c / f"{ticker}_{quarter}.txt", c / f"{ticker}_{quarter}_release.txt") if p.exists()]


def validate(card: dict, ticker: str, quarter: str) -> list[tuple[str, str]]:
    issues = []
    srcs = originals(ticker, quarter)
    text = _norm(" ".join(p.read_text() for p in srcs))
    pts = card.get("points", [])
    if not 3 <= len(pts) <= 4:
        issues.append(("포인트 수", f"{len(pts)}개 (3~4개여야 해요)"))
    tones = {p.get("tone") for p in pts}
    if "positive" not in tones or "negative" not in tones:
        issues.append(("균형", "좋은 점(positive)과 나쁜 점(negative)이 모두 있어야 해요"))
    for p in pts:
        q = p.get("quote")
        if not q:
            continue
        if len(q.split()) > 15:
            issues.append(("인용 길이", f"{len(q.split())}단어: {q[:30]}…"))
        if not srcs:
            issues.append(("원문 없음", "calls/ 에 원문 파일이 없어 인용을 확인할 수 없어요"))
        elif _norm(q) not in text:
            issues.append(("원문에 없는 인용", q[:40]))
    return issues


def build_html(data: dict, card: dict, size: str = "1080x1080") -> str:
    W, H = SIZES[size]
    last = data["quarters"][-1]
    name, color = brand(data)
    points = []
    for p in card.get("points", []):
        cls, mark = TONE.get(p.get("tone"), TONE["neutral"])
        points.append({**p, "cls": cls, "mark": mark})
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    css = env.get_template("base.css").render(W=W, H=H, L=layout(W, H),
                                              font_dir=render_font_url())
    # 출처: 원문 파일 첫 줄의 '# 제출일/게시일' 을 읽어 문서 이름과 날짜로
    parts = []
    for p in originals(data["ticker"], data["requested_quarter"]):
        head = dict(re.findall(r"^# (\S+): (.+)$", p.read_text()[:500], re.M))
        when = head.get("제출일") or head.get("게시일", "").split(" ")[0]
        if p.name.endswith("_release.txt"):
            doc = "실적 발표 보도자료(SEC 8-K)" if data["market"] == "US" else "실적 발표문(뉴스룸)"
        else:
            doc = "어닝콜 원문·기사"
        parts.append(f"{name} {doc}" + (f" {when}" if when else ""))
    kind = card.get("source_kind", "어닝콜")
    source = " · ".join(parts) or f"{name} {kind}"
    source += " · 숫자: " + ("SEC EDGAR·실적 발표 자료" if data["market"] == "US" else "OpenDART·실적 발표 자료")
    return env.get_template("call.html").render(
        css=css, W=W, H=H, name=name, color=color, ticker=data["ticker"], qtitle=qtitle(last),
        status=last.get("status"), kind=kind, points=points, one_liner=card.get("one_liner"),
        source=source, translated=any(p.get("quote_ko") for p in points))
