"""미국 기업 실적 발표 보도자료(8-K Item 2.02, Exhibit 99.1) 받기 → 읽기 쉬운 텍스트.

    calls/{ticker}_{분기}_release.txt 로 저장 (Claude가 읽고 이슈·어닝콜 카드 문구를 쓸 때 사용)

분기 매칭: 분기 말일 이후 첫 Item 2.02 8-K (보통 3~6주 뒤).
"""
from __future__ import annotations

import html
import re
from datetime import date, timedelta
from pathlib import Path

from collectors import sec

ROOT = Path(__file__).resolve().parent.parent


def _quarter_end(q: str) -> date:
    y, n = int(q[:4]), int(q[-1])
    m = n * 3
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)


def html_to_text(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
    s = re.sub(r"</(p|div|tr|br|li|h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<td[^>]*>", " | ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"(\s*\|\s*)+", " | ", s)
    s = re.sub(r"\$ \| ", "$", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def fetch(ticker: str, quarter: str, refresh: bool = False, period_end: str | None = None) -> Path:
    """period_end: 실제 분기 말일(52/53주·비12월 결산 기업). 없으면 달력 분기 말일."""
    cik, _ = sec.ticker_to_cik(ticker)
    out = ROOT / "calls" / f"{ticker.upper()}_{quarter}_release.txt"
    if out.exists() and not refresh:
        return out
    subs = sec.recent_filings(cik, refresh)
    r = subs["filings"]["recent"]
    qe = date.fromisoformat(period_end) if period_end else _quarter_end(quarter)
    hits = [(r["filingDate"][i], r["accessionNumber"][i]) for i, f in enumerate(r["form"])
            if f == "8-K" and "2.02" in (r["items"][i] or "")
            and qe < date.fromisoformat(r["filingDate"][i]) <= qe + timedelta(days=75)]
    # 인도량 발표처럼 실적이 아닌 Item 2.02도 있어 → 순이익·영업이익이 나오는 보도자료만
    for filed, acc in sorted(hits):
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
        items = sec._get(base + "index.json").json()["directory"]["item"]
        prim = r["primaryDocument"][r["accessionNumber"].index(acc)] if "primaryDocument" in r else ""
        htm = [i["name"] for i in items if i["name"].lower().endswith((".htm", ".html"))
               and i["name"] != prim and not re.fullmatch(r"R\d+\.htm", i["name"])
               and "index" not in i["name"].lower()]
        # 보도자료 이름은 회사마다 다름(ex99-1, googexhibit991, q1fy27pr …) → 이름 힌트 순으로 열어 봄
        htm.sort(key=lambda n: (0 if re.search(r"ex[-_]?99|exhibit[-_]?99|991|pr\.htm|press", n, re.I) else 1, n))
        found = False
        for name in htm[:4]:
            url = base + name
            text = html_to_text(sec._get(url).text)
            low = text.lower()
            if ("net income" in low or "operating income" in low or "income from operations" in low) and "revenue" in low:
                found = True
                break
        if found:
            break
    else:
        raise sec.SecError(f"{ticker} {quarter} 실적 발표 보도자료(8-K)를 찾지 못했어요.")
    out.parent.mkdir(exist_ok=True)
    out.write_text(f"# 출처: {url}\n# 제출일: {filed}\n\n{text}\n")
    return out
