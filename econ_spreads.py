"""💳 신용 스프레드 (밸류AI 경제지표 탭 · 원본 ~/projects/경제지표/spreads.py — 고치면 둘 다) — FRED의 ICE BofA 회사채 OAS(국채 대비 가산금리) 6개를 받아 감시 경계선·등급 간 전이를 판정

data/spreads.json: {"updated", "source", "series": {id: {"name", "short", "grade", "data": {날짜: 값(%)}}}, "watch": [...], "summary": {...}}
FRED는 ICE 데이터를 최근 3년치만 공개한다(라이선스) — 백분위는 '최근 3년 안'에서만 계산한다.
"""
import csv
import io
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "econ_spreads.json"   # 밸류AI: 서버가 스스로 받아 둠
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
SERIES = [   # (FRED id, 이름, 짧은 이름, 묶음)
    ("BAMLH0A0HYM2", "하이일드 전체", "하이일드", "HY"),
    ("BAMLC0A0CM", "투자등급 전체", "투자등급", "IG"),
    ("BAMLC0A4CBBB", "BBB 등급(투자등급 맨 아래)", "BBB", "IG"),
    ("BAMLH0A1HYBB", "BB 등급(하이일드 맨 위)", "BB", "HY"),
    ("BAMLH0A2HYB", "B 등급", "B", "HY"),
    ("BAMLH0A3HYC", "CCC 이하", "CCC", "HY"),
]
# 감시 경계선(판단 기준) — 히르찬 매크로 리서치 2026-11-14 리포트 표 3
WATCH = [
    {"id": "BAMLH0A0HYM2", "line": 3.5, "days": 10, "why": "11/5 일별 고점(3.48%)을 넘어 10월 재평가가 되돌림 없이 이어진다는 뜻(2주 = 영업일 10일)"},
    {"id": "BAMLC0A0CM", "line": 1.0, "days": 1, "why": "최근 1년 월평균 범위(0.75~0.88%)를 벗어남 — 우량 회사채 소화력이 꺾인다는 신호"},
]
# 전이 판정(판단 기준): 최근 1개월(약 21영업일) 변화 — CCC가 크게 벌어진 뒤 BB·BBB가 따라 벌어지면 '위로 번짐'
SPREAD_STEP = {"CCC": 1.0, "B": 0.5, "BB": 0.3, "BBB": 0.15}


def fetch():
    ids = ",".join(s[0] for s in SERIES)
    raw = urllib.request.urlopen(URL + ids, timeout=60).read().decode()
    rows = list(csv.reader(io.StringIO(raw)))
    head, data = rows[0], {s[0]: {} for s in SERIES}
    for r in rows[1:]:
        for i, sid in enumerate(head[1:], 1):
            if sid in data and i < len(r) and r[i] not in ("", "."):
                data[sid][r[0]] = float(r[i])
    if not all(len(v) > 100 for v in data.values()):
        raise RuntimeError("FRED에서 받은 자료가 비어 있어요.")
    return data


def _pct_rank(vals, x):
    return round(sum(v <= x for v in vals) / len(vals) * 100)


def analyze(data):
    out, meta = {}, {s[0]: s for s in SERIES}
    for sid, d in data.items():
        dates = sorted(d)
        vals = [d[k] for k in dates]
        last, ld = vals[-1], dates[-1]
        ago = lambda n: vals[-1 - n] if len(vals) > n else None
        out[sid] = {"short": meta[sid][2], "last": last, "date": ld,
                    "chg_1w": round(last - ago(5), 2) if ago(5) is not None else None,
                    "chg_1m": round(last - ago(21), 2) if ago(21) is not None else None,
                    "chg_3m": round(last - ago(63), 2) if ago(63) is not None else None,
                    "pct_3y": _pct_rank(vals, last), "min_3y": min(vals), "max_3y": max(vals),
                    "first": dates[0]}
    watch = []
    for w in WATCH:
        d = data[w["id"]]
        dates = sorted(d)
        recent = [d[k] for k in dates[-w["days"]:]]
        hit = all(v > w["line"] for v in recent)
        streak = 0
        for k in reversed(dates):
            if d[k] > w["line"]:
                streak += 1
            else:
                break
        watch.append({**w, "short": meta[w["id"]][2], "last": d[dates[-1]], "hit": hit, "streak": streak,
                      "gap": round(w["line"] - d[dates[-1]], 2), "rule": f"{w['line']}% 위 {'영업일 ' + str(w['days']) + '일 연속' if w['days'] > 1 else ''}".strip()})
    by = {out[s[0]]["short"]: out[s[0]] for s in SERIES}
    # 벌어짐 = 1개월 확대 폭이 기준 이상이거나, 3개월 확대 폭이 기준의 1.5배 이상이거나, 최근 3년 백분위 90 이상(이미 높은 수준)
    moved = {g: (by[g]["chg_1m"] or 0) >= step or (by[g]["chg_3m"] or 0) >= step * 1.5 or by[g]["pct_3y"] >= 90 for g, step in SPREAD_STEP.items()}
    if moved["CCC"] and moved["BB"] and moved["BBB"]:
        stage, text = "전이", "CCC부터 BB·BBB까지 한 달 사이 함께 벌어졌어요 — 스트레스가 위 등급으로 번지는 중"
    elif moved["CCC"] and (moved["B"] or moved["BB"]):
        stage, text = "번지는 중", "CCC와 B·BB가 함께 벌어졌어요 — 하이일드 안에서 위로 올라오는 중, BBB는 아직"
    elif moved["CCC"]:
        stage, text = "바닥 스트레스", "CCC만 벌어졌거나 높은 수준이에요 — 가장 약한 차입자에 한정된 스트레스, BB·BBB는 아직 조용함"
    else:
        stage, text = "조용함", "등급 전반에서 한 달 사이 큰 확대가 없어요"
    gaps = {"CCC−BB": round(by["CCC"]["last"] - by["BB"]["last"], 2), "BB−BBB": round(by["BB"]["last"] - by["BBB"]["last"], 2),
            "하이일드−투자등급": round(by["하이일드"]["last"] - by["투자등급"]["last"], 2)}
    return {"latest": out, "watch": watch, "transfer": {"stage": stage, "text": text, "rule": "등급별로 1개월 확대 폭(CCC 1.0·B 0.5·BB 0.3·BBB 0.15%p 이상) 또는 3개월 확대 폭(그 1.5배 이상) 또는 최근 3년 백분위 90 이상이면 '벌어짐'으로 본다 (판단 기준)"},
            "gaps": gaps}


def update():
    data = fetch()
    res = {"updated": time.strftime("%Y-%m-%d %H:%M"), "source": "ICE Data Indices via FRED (최근 3년만 공개)",
           "series": {s[0]: {"name": s[1], "short": s[2], "grade": s[3], "data": data[s[0]]} for s in SERIES}, **analyze(data)}
    before = ((load() or {}).get("latest") or {}).get("BAMLH0A0HYM2", {}).get("date")
    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return "same" if before == res["latest"]["BAMLH0A0HYM2"]["date"] else "updated"


def load():
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return None


if __name__ == "__main__":
    print(update())
    r = load()
    for sid, x in r["latest"].items():
        print(f"{x['short']:6} {x['last']:.2f}%  1주 {x['chg_1w']:+.2f}  1달 {x['chg_1m']:+.2f}  3년 백분위 {x['pct_3y']}  ({x['date']})")
    print(r["transfer"]); print(r["gaps"]); print([(w["short"], w["hit"], w["streak"], w["gap"]) for w in r["watch"]])
