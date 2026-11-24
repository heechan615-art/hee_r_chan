"""💳 신용 스프레드 (밸류AI 경제지표 탭 · 원본 ~/projects/경제지표/spreads.py — 고치면 둘 다) — FRED의 ICE BofA 회사채 OAS(국채 대비 가산금리) 6개를 받아 감시 경계선·등급 간 전이를 판정
+ 같은 지수의 실제 금리(유효 수익률, Effective Yield) 6개 — 금리 = 국채 몫 + OAS

data/spreads.json: {"updated", "source", "series": {id: {"name", "short", "grade", "data": {날짜: 값(%)}}}, "watch": [...], "summary": {...},
                    "yields": {id: {...같은 형식}}, "ylatest": {id: {...latest와 같은 형식}}}
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
YIELDS = [   # 실제 금리(유효 수익률) — (FRED id, 이름, 짧은 이름, 묶음), 짧은 이름은 OAS와 같게
    ("BAMLC0A4CBBBEY", "BBB 등급 금리", "BBB", "IG"),
    ("BAMLH0A1HYBBEY", "BB 등급 금리", "BB", "HY"),
    ("BAMLH0A2HYBEY", "B 등급 금리", "B", "HY"),
    ("BAMLH0A3HYCEY", "CCC 이하 금리", "CCC", "HY"),
    ("BAMLH0A0HYM2EY", "하이일드 전체 금리", "하이일드", "HY"),
    ("BAMLC0A0CMEY", "투자등급 전체 금리", "투자등급", "IG"),
]
UST = [   # 미국 국채 금리(만기 일정 수익률) — 회사채 금리와 같은 기간(최근 3년)만 남김
    ("DGS2", "미국 국채 2년", "국채 2년", "UST"),
    ("DGS10", "미국 국채 10년", "국채 10년", "UST"),
]
# 감시 경계선(판단 기준) — 히르찬 매크로 리서치 2026-11-14 리포트 표 3
WATCH = [
    {"id": "BAMLH0A0HYM2", "line": 3.5, "days": 10, "why": "11/5 일별 고점(3.48%)을 넘어 10월 재평가가 되돌림 없이 이어진다는 뜻(2주 = 영업일 10일)"},
    {"id": "BAMLC0A0CM", "line": 1.0, "days": 1, "why": "최근 1년 월평균 범위(0.75~0.88%)를 벗어남 — 우량 회사채 소화력이 꺾인다는 신호"},
]
# 전이 판정(판단 기준): 최근 1개월(약 21영업일) 변화 — CCC가 크게 벌어진 뒤 BB·BBB가 따라 벌어지면 '위로 번짐'
SPREAD_STEP = {"CCC": 1.0, "B": 0.5, "BB": 0.3, "BBB": 0.15}


def fetch(series=SERIES):
    ids = ",".join(s[0] for s in series)
    try:
        raw = urllib.request.urlopen(URL + ids, timeout=30).read().decode()
    except Exception:       # 클라우드(Render)에서 막히면 브라우저처럼 한 번 더
        import requests
        raw = requests.get(URL + ids, timeout=30, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
                                                          "Accept": "text/csv,*/*"}).text
    rows = list(csv.reader(io.StringIO(raw)))
    head, data = rows[0], {s[0]: {} for s in series}
    for r in rows[1:]:
        for i, sid in enumerate(head[1:], 1):
            if sid in data and i < len(r) and r[i] not in ("", "."):
                data[sid][r[0]] = float(r[i])
    if not all(len(v) > 100 for v in data.values()):
        raise RuntimeError("FRED에서 받은 자료가 비어 있어요.")
    return data


def _pct_rank(vals, x):
    return round(sum(v <= x for v in vals) / len(vals) * 100)


def stats(data, series):
    out, meta = {}, {s[0]: s for s in series}
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
    return out


def analyze(data):
    out, meta = stats(data, SERIES), {s[0]: s for s in SERIES}
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


# BB−BBB 수준 구간(판단 기준) — 지난 3년 사건 고점: 2024-08-05 엔캐리 청산 1.12, 2025-04-07 관세 충격 1.58
GAP_BANDS = [(0.7, "g", "조용함"), (1.0, "g", "보통"), (1.3, "y", "경계 — 2024년 8월 엔캐리 청산 고점(1.12) 근처"), (99, "r", "스트레스 — 2025년 4월 관세 충격(고점 1.58) 쪽")]


def gap_read(res):
    """↔️ 등급 간 차이 해석(규칙) — {head, level, paras, watch, legs}. BB−BBB가 왜 움직였는지 두 다리(BB·BBB)와 국채로 나눠 봄"""
    S = {v["short"]: v["data"] for v in res["series"].values()}
    Y = {v["short"]: v["data"] for v in (res.get("yields") or {}).values()}
    U = (res.get("ust") or {}).get("DGS10", {}).get("data", {})
    dates = [d for d in sorted(S["BB"]) if d in S["BBB"]]
    g = [round(S["BB"][d] - S["BBB"][d], 2) for d in dates]
    c = [round(S["CCC"][d] - S["BB"][d], 2) for d in dates if d in S["CCC"]]
    if len(g) < 30:
        return None
    now, ld = g[-1], dates[-1]
    w, m = 5, 21
    d1w, d1m = round(now - g[-1 - w], 2), round(now - g[-1 - m], 2)
    lo_i = min(range(len(g) - m - 1, len(g)), key=lambda i: g[i])   # 최근 1달 안의 바닥
    lo, lo_d = g[lo_i], dates[lo_i]
    pct = round(sum(v <= now for v in g) / len(g) * 100)
    yr = [(dates[i], g[i]) for i in range(len(g)) if dates[i] >= dates[-1][:4] + "-01-01" or i >= len(g) - 252]
    y_hi = max(yr[:-1], key=lambda x: x[1]) if len(yr) > 1 else (ld, now)
    hi3 = max(zip(dates, g), key=lambda x: x[1])
    lv, band = next((l, t) for cut, l, t in GAP_BANDS if now < cut)
    # 다리 나누기: 바닥 이후 BB·BBB 가산금리 변화, 같은 기간 실제 금리와 10년 국채
    ch = lambda D, a, b: round(D[b] - D[a], 2) if D and a in D and b in D else None
    bb, bbb = ch(S["BB"], lo_d, ld), ch(S["BBB"], lo_d, ld)
    ybb, ybbb, u10 = ch(Y.get("BB"), lo_d, ld), ch(Y.get("BBB"), lo_d, ld), ch(U, lo_d, max([d for d in U if d <= ld] or [ld]))
    prev = dates[-2]
    t_bb, t_bbb, t_g = ch(S["BB"], prev, ld), ch(S["BBB"], prev, ld), round(now - g[-2], 2)
    t_ybb, t_ybbb = ch(Y.get("BB"), prev, ld), ch(Y.get("BBB"), prev, ld)
    t_u = ch(U, max([d for d in U if d < ld] or [ld]), ld) if ld in U else None
    sg = lambda v: "-" if v is None else f"{v:+.2f}"
    paras = [f"지금 BB−BBB는 {now:.2f}%p예요. 최근 1달 바닥({lo_d[5:].replace('-', '/')} {lo:.2f}) 뒤 {now - lo:+.2f}%p, 1주 {sg(d1w)} · 1달 {sg(d1m)}. 최근 3년 중 {pct}% 위치이고, 1년 안에서는 {'가장 높아요' if now >= y_hi[1] else f'{y_hi[0]} {y_hi[1]:.2f}가 더 높았어요'}. 구간: {band}."]
    if bb is not None and bbb is not None and now - lo >= 0.15:
        share = bb / (bb - bbb) * 100 if bb - bbb else 0
        paras.append(f"왜 벌어졌나 — 두 다리로 나누면 같은 기간 BB 가산금리는 {sg(bb)}%p, BBB는 {sg(bbb)}%p 움직였어요. "
                     + ("차이가 벌어진 건 거의 BB(하이일드 맨 위) 쪽이 혼자 오른 결과예요 — 투자등급은 덜 움직이고 하이일드만 값을 다시 매긴 것." if bbb <= 0.15 or bb >= 3 * bbb else "BB와 BBB가 같이 올랐지만 BB가 더 많이 — 신용 전반이 나빠지는 가운데 하이일드가 더 크게."))
    if ybb is not None and ybbb is not None and u10 is not None:
        if u10 < 0 and ybbb <= 0.05 and ybb > 0:
            paras.append(f"실제 금리로 보면 더 분명해요 — 같은 기간 10년 국채 {sg(u10)}%p, BBB 금리 {sg(ybbb)}%p(국채 따라 내림/그대로), BB 금리 {sg(ybb)}%p(거꾸로 오름). 투자등급은 '국채처럼', BB는 '주식처럼' 움직인 거예요. 주식이 빠지고 안전자산(국채)으로 돈이 몰리는 위험 회피 날의 전형적인 모습이에요.")
        else:
            paras.append(f"실제 금리: 같은 기간 10년 국채 {sg(u10)}%p, BBB 금리 {sg(ybbb)}%p, BB 금리 {sg(ybb)}%p.")
    if t_g is not None and abs(t_g) >= 0.08:
        paras.append(f"마지막 날({ld[5:].replace('-', '/')}) 하루에만 {t_g:+.2f}%p — BB {sg(t_bb)} · BBB {sg(t_bbb)}, 실제 금리 BB {sg(t_ybb)} · BBB {sg(t_ybbb)}, 10년 국채 {sg(t_u)}. 하루 움직임이라 사건(주가 급락·실적 등) 영향이 커요 — 아래 '사건 메모'를 같이 보세요.")
    cnow = c[-1] if c else None
    cpct = round(sum(v <= cnow for v in c) / len(c) * 100) if c else None
    if cnow is not None:
        paras.append(f"CCC−BB는 {cnow:.2f}%p(3년 중 {cpct}%) — " + ("바닥(CCC) 스트레스는 이미 높고, 이제 BB−BBB까지 올라와 하이일드 위쪽으로 번지는 단계예요. 다음 관문은 BBB·투자등급 가산금리가 따라 오르는지예요." if cpct >= 90 and now >= 0.9 else "바닥 스트레스와 위쪽 번짐을 같이 봐요."))
    head = (f"BB−BBB {now:.2f}%p — " + ("1년 최고, 하이일드 위쪽까지 위험 회피가 번지는 중" if now >= y_hi[1] and now - lo >= 0.2 else
            "빠르게 벌어지는 중" if now - lo >= 0.2 else "큰 변화 없음"))
    if now >= y_hi[1] and now - lo >= 0.2 and lv == "g":
        lv = "y"
    watch = [f"BB−BBB가 1.12(2024년 8월 엔캐리 청산 고점)를 넘는지 → 넘으면 그때보다 센 위험 회피, 1.3 위면 '스트레스' 구간 (지금 {now:.2f})",
             f"BBB·투자등급 가산금리가 따라 오르는지 — 투자등급 1.0% 경계선(감시 중)을 넘으면 '전이' 단계 (지금 BBB {S['BBB'][ld]:.2f} · 투자등급 {S['IG'][ld] if 'IG' in S else S['투자등급'][ld]:.2f})",
             "며칠 안에 되돌아가는지: 하루 급등이 이틀 안에 절반 이상 되돌아가면 사건성, 계속 쌓이면 추세",
             f"3년 최고는 {hi3[0]} {hi3[1]:.2f}(2025년 4월 관세 충격) — 지금 위험 회피가 그때의 몇 % 강도인지 견줘 봐요 (지금 {now / hi3[1] * 100:.0f}%)"]
    return {"head": head, "level": lv, "paras": paras, "watch": watch}


def update():
    data = fetch()
    res = {"updated": time.strftime("%Y-%m-%d %H:%M"), "source": "ICE Data Indices via FRED (최근 3년만 공개)",
           "series": {s[0]: {"name": s[1], "short": s[2], "grade": s[3], "data": data[s[0]]} for s in SERIES}, **analyze(data)}
    try:   # 실제 금리는 덤 — 못 받아도 OAS는 그대로 저장(지난 금리 자료는 남김)
        y = fetch(YIELDS)
        res["yields"] = {s[0]: {"name": s[1], "short": s[2], "grade": s[3], "data": y[s[0]]} for s in YIELDS}
        res["ylatest"] = stats(y, YIELDS)
    except Exception as e:
        old = load() or {}
        if old.get("yields"):
            res["yields"], res["ylatest"] = old["yields"], old.get("ylatest")
        print("[spreads] 실제 금리 받기 실패:", repr(e)[:200])
    try:   # 국채 2년·10년 — FRED는 1962년부터 주므로 OAS 첫날부터만
        first = min(min(v["data"]) for v in res["series"].values())
        u = {k: {d: x for d, x in v.items() if d >= first} for k, v in fetch(UST).items()}
        res["ust"] = {s_[0]: {"name": s_[1], "short": s_[2], "data": u[s_[0]]} for s_ in UST}
        res["ustlatest"] = stats(u, UST)
    except Exception as e:
        old = load() or {}
        if old.get("ust"):
            res["ust"], res["ustlatest"] = old["ust"], old.get("ustlatest")
        print("[spreads] 국채 금리 받기 실패:", repr(e)[:200])
    try:
        res["gap_read"] = gap_read(res)
    except Exception as e:
        print("[spreads] 등급 간 차이 해석 실패:", repr(e)[:200])
    before = ((load() or {}).get("latest") or {}).get("BAMLH0A0HYM2", {}).get("date")
    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return "same" if before == res["latest"]["BAMLH0A0HYM2"]["date"] else "updated"


SEED = ROOT / "econ_spreads_seed.json"   # 맥(경제지표 노트)이 받아 둔 최신본 — 사이트 서버가 FRED에서 못 받을 때 대신 보여 줌
NOTES = ROOT / "econ_spreads_notes.json"   # 📌 사건 메모 — 노트 data/spreads_notes.json을 export_valueai가 복사


def load():
    try:
        r = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        r["notes"] = json.loads(NOTES.read_text(encoding="utf-8")).get("notes", [])
    except Exception:
        r["notes"] = []
    return r


if __name__ == "__main__":
    print(update())
    r = load()
    for sid, x in r["latest"].items():
        print(f"{x['short']:6} {x['last']:.2f}%  1주 {x['chg_1w']:+.2f}  1달 {x['chg_1m']:+.2f}  3년 백분위 {x['pct_3y']}  ({x['date']})")
    for sid, x in (r.get("ustlatest") or {}).items():
        print(f"{x['short']:6} {x['last']:.2f}%  1달 {x['chg_1m']:+.2f}  3년 백분위 {x['pct_3y']}")
    for sid, x in (r.get("ylatest") or {}).items():
        print(f"금리 {x['short']:6} {x['last']:.2f}%  1달 {x['chg_1m']:+.2f}  3년 백분위 {x['pct_3y']}")
    print(json.dumps(r.get("gap_read"), ensure_ascii=False, indent=1))
    print(r["transfer"]); print(r["gaps"]); print([(w["short"], w["hit"], w["streak"], w["gap"]) for w in r["watch"]])
