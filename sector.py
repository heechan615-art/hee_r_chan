"""
주도 섹터 · 순환매 찾기
=======================
'상대적으로 누가 더 세고, 그 힘이 이익으로 뒷받침되는가'를 여러 각도에서 본다.

1. 경기 국면 지도 + 매크로(장단기 금리차·10년 금리·달러·ISM)  → 어디를 볼지
2. 상대강도(RS = 섹터 ÷ 시장): 1주·1개월·3개월·6개월 시장 대비 수익률, RS선, RRG(상대회전그래프)
3. 이익 추정치: S&P500 종목의 최근 30일 올해 EPS 추정 상향·하향 건수(야후 애널리스트) — 미국만
4. 확산: 섹터 안 200일선 위 종목 비율·52주 신고가 종목 수(S&P500 구성 종목) — 미국만 / 거래대금 변화(섹터 ETF)

미국은 SPDR 섹터 ETF 11개 vs SPY, 한국은 업종 ETF 18개 vs 코스피.
섹터 ETF 계산은 1시간 캐시, 500종목 확산·이익 추정은 뒤에서 계산해 6시간 캐시(data/sector_breadth.json).
모든 신호는 공부용 참고이며 매수·매도 권유가 아니다.
"""
import io
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

# (티커, 이름, 경기 국면 태그, 비고) — 국면: early 회복 초기 / mid 확장 중기 / late 확장 후기 / slow 둔화·침체
US = {
    "bench": ("SPY", "S&P500(SPY)"),
    "sectors": [
        ("XLK", "IT(기술)", ["mid"], "Information Technology"),
        ("XLC", "커뮤니케이션", ["mid"], "Communication Services"),
        ("XLY", "경기소비재", ["early"], "Consumer Discretionary"),
        ("XLF", "금융", ["early"], "Financials"),
        ("XLI", "산업재", ["early", "mid"], "Industrials"),
        ("XLB", "소재", ["late"], "Materials"),
        ("XLE", "에너지", ["late"], "Energy"),
        ("XLV", "헬스케어", ["late", "slow"], "Health Care"),
        ("XLP", "필수소비재", ["slow"], "Consumer Staples"),
        ("XLU", "유틸리티", ["slow"], "Utilities"),
        ("XLRE", "부동산", [], "Real Estate"),
    ],
}
KR = {
    "bench": ("^KS11", "코스피"),
    "sectors": [
        ("091160.KS", "반도체", ["mid"], "KODEX 반도체"),
        ("139260.KS", "IT", ["mid"], "TIGER 200 IT"),
        ("305720.KS", "2차전지", ["mid"], "KODEX 2차전지산업"),
        ("266360.KS", "미디어·콘텐츠", ["mid"], "KODEX K콘텐츠"),
        ("091180.KS", "자동차", ["early"], "KODEX 자동차"),
        ("139290.KS", "경기소비재", ["early"], "TIGER 200 경기소비재"),
        ("091170.KS", "은행", ["early"], "KODEX 은행"),
        ("102970.KS", "증권", ["early"], "KODEX 증권"),
        ("140700.KS", "보험", ["early"], "KODEX 보험"),
        ("102960.KS", "기계장비", ["early", "mid"], "KODEX 기계장비"),
        ("139230.KS", "중공업", ["early", "mid"], "TIGER 200 중공업"),
        ("466920.KS", "조선", ["early", "mid"], "SOL 조선TOP3플러스"),
        ("117700.KS", "건설", ["early"], "KODEX 건설"),
        ("140710.KS", "운송", ["early"], "KODEX 운송"),
        ("117460.KS", "에너지화학", ["late"], "KODEX 에너지화학"),
        ("117680.KS", "철강", ["late"], "KODEX 철강"),
        ("266420.KS", "헬스케어", ["late", "slow"], "KODEX 헬스케어"),
        ("227560.KS", "필수소비재", ["slow"], "TIGER 200 생활소비재"),
    ],
}
PHASES = [
    {"id": "early", "name": "회복 초기", "desc": "금리 인하 뒤 경기가 바닥을 지나는 때", "us": "금융 · 경기소비재 · 산업재"},
    {"id": "mid", "name": "확장 중기", "desc": "이익이 고르게 늘고 투자가 살아나는 때", "us": "IT · 산업재 · 커뮤니케이션"},
    {"id": "late", "name": "확장 후기", "desc": "물가·원자재가 오르고 금리가 높아지는 때", "us": "에너지 · 소재 · 헬스케어"},
    {"id": "slow", "name": "둔화 · 침체", "desc": "이익이 줄고 방어가 중요한 때", "us": "필수소비재 · 유틸리티 · 헬스케어"},
]

_CACHE = {}
_LOCK = threading.Lock()
TTL = 3600
BREADTH_TTL = 6 * 3600
BREADTH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sector_breadth.json")
_BREADTH = {"state": "idle", "data": None, "started": None, "error": None}


def _sess():
    from curl_cffi import requests as creq
    return creq.Session(impersonate="chrome")


def _chart(s, sym, rng="2y"):
    """야후 차트 API → 일별 종가·거래량 DataFrame(날짜 인덱스)"""
    r = s.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
              params={"range": rng, "interval": "1d"}, timeout=20)
    j = r.json()["chart"]["result"][0]
    ts = j.get("timestamp") or []
    q = j["indicators"]["quote"][0]
    adj = (j["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    close = adj if adj and len(adj) == len(ts) else q["close"]
    df = pd.DataFrame({"c": close, "v": q.get("volume") or [None] * len(ts)},
                      index=pd.to_datetime(ts, unit="s").normalize())
    df = df[~df.index.duplicated(keep="last")].dropna(subset=["c"])
    return df


def _f(x, n=2):
    try:
        x = float(x)
        return None if (math.isnan(x) or math.isinf(x)) else round(x, n)
    except Exception:
        return None


def _ret(c, n):
    return (c.iloc[-1] / c.iloc[-1 - n] - 1) * 100 if len(c) > n else np.nan


def _rrg(sec, bench, win=10, tail=8):
    """JdK RRG 근사: 주간 RS의 정규화(RS-Ratio)와 그 변화율의 정규화(RS-Momentum). 100이 기준"""
    s = sec.resample("W-FRI").last()
    b = bench.resample("W-FRI").last()
    rs = (s / b).dropna() * 100
    rsr = 100 + (rs - rs.rolling(win).mean()) / rs.rolling(win).std()
    roc = (rsr / rsr.shift(1) - 1) * 100
    rsm = 100 + (roc - roc.rolling(win).mean()) / roc.rolling(win).std()
    d = pd.DataFrame({"x": rsr, "y": rsm}).dropna().tail(tail)
    return [{"d": i.strftime("%m/%d"), "x": _f(r.x), "y": _f(r.y)} for i, r in d.iterrows()]


def _quad(x, y):
    if x is None or y is None:
        return None
    if x >= 100:
        return "선도" if y >= 100 else "약화"
    return "개선" if y >= 100 else "부진"


# ---------------- 매크로(경기 국면 판단 재료) ----------------
def _fred_csv(s, sid):
    r = s.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=15)
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["d", "v"]
    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    df = df.dropna()
    df["d"] = pd.to_datetime(df["d"])
    return df.set_index("d")["v"]


def _ism_from_econ():
    """경제지표 해석 탭 묶음(static/econ/bundle.json)에 ISM 제조업 수치가 있으면"""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "econ", "bundle.json")
        b = json.load(open(p, encoding="utf-8"))
        ind = next(i for i in b["indicators"] if i["id"] == "us-ism-mfg")
        s = (ind.get("series") or {}).get(ind.get("primary") or "pmi") or {}
        d = s.get("data") or {}
        if not d:
            return None
        ks = sorted(d)
        return {"v": d[ks[-1]], "prev": d[ks[-2]] if len(ks) > 1 else None, "m": ks[-1]}
    except Exception:
        return None


def macro(s, market):
    out = []
    try:
        t = _fred_csv(s, "T10Y2Y")
        prev = t[t.index <= t.index[-1] - pd.Timedelta(days=91)]
        out.append({"k": "장단기 금리차(10년−2년)", "v": _f(t.iloc[-1]), "u": "%p", "chg": _f(t.iloc[-1] - prev.iloc[-1]) if len(prev) else None,
                    "d": t.index[-1].strftime("%Y-%m-%d"), "src": "FRED T10Y2Y",
                    "hint": "플러스로 벌어지면 보통 회복 초기, 마이너스(역전)는 둔화 경고로 읽어요"})
    except Exception:
        pass
    for sym, nm, u, hint in [("^TNX", "미국 10년 금리", "%", "금리가 빠르게 오르면 확장 후기, 내려가면 둔화·회복 초기 쪽 신호로 읽어요"),
                             ("DX-Y.NYB", "달러 인덱스", "", "달러 강세는 보통 위험자산·신흥국에 부담이에요")] + \
                            ([("KRW=X", "원/달러 환율", "원", "환율이 오르면(원화 약세) 외국인 수급에 부담일 수 있어요")] if market == "KR" else []):
        try:
            c = _chart(s, sym, "1y")["c"]
            out.append({"k": nm, "v": _f(c.iloc[-1]), "u": u, "chg": _f(_ret(c, 63), 1), "chg_u": "%",
                        "d": c.index[-1].strftime("%Y-%m-%d"), "src": "야후 파이낸스", "hint": hint})
        except Exception:
            pass
    ism = _ism_from_econ()
    out.append({"k": "ISM 제조업 PMI", "v": ism["v"] if ism else None, "u": "", "chg": _f(ism["v"] - ism["prev"], 1) if ism and ism["prev"] is not None else None,
                "d": ism["m"] if ism else None, "src": "경제지표 해석 탭", "econ": True,
                "hint": "50 위면 제조업 확장, 아래면 위축. 바닥에서 50을 넘어서면 회복 초기 신호로 많이 봐요"})
    return out


# ---------------- 섹터 ETF 상대강도 ----------------
def _sector_rows(s, cfg):
    bsym, bname = cfg["bench"]
    syms = [bsym] + [x[0] for x in cfg["sectors"]]
    with ThreadPoolExecutor(8) as ex:
        dfs = dict(zip(syms, ex.map(lambda x: _safe_chart(s, x), syms)))
    B = dfs[bsym]
    if B is None or len(B) < 150:
        raise RuntimeError("시장 지수 데이터를 받지 못했어요")
    bc = B["c"]
    rows = []
    for sym, nm, ph, note in cfg["sectors"]:
        D = dfs.get(sym)
        if D is None or len(D) < 150:
            rows.append({"sym": sym, "name": nm, "phases": ph, "note": note, "error": "데이터 없음"})
            continue
        j = pd.concat([D["c"], bc], axis=1, keys=["s", "b"]).ffill().dropna()
        sc, b = j["s"], j["b"]
        rs = sc / b
        ma50 = rs.rolling(50).mean()
        r = {k: _f(_ret(sc, n) - _ret(b, n)) for k, n in [("x1w", 5), ("x1m", 21), ("x3m", 63), ("x6m", 126)]}
        a = {k: _f(_ret(sc, n)) for k, n in [("r1w", 5), ("r1m", 21), ("r3m", 63), ("r6m", 126)]}
        last252 = rs.tail(252)
        rs_high = bool(last252.tail(10).max() >= last252.max() * 0.999)
        # 하락일 방어: 최근 3개월 시장이 내린 날 섹터 평균 ÷ 시장 평균(1보다 작으면 덜 빠짐)
        dr = pd.concat([sc.pct_change(), b.pct_change()], axis=1, keys=["s", "b"]).tail(63).dropna()
        dn = dr[dr["b"] < 0]
        downcap = _f(dn["s"].mean() / dn["b"].mean()) if len(dn) >= 5 and dn["b"].mean() else None
        # 거래대금: 최근 20일 평균 ÷ 60일 평균
        tv = (D["c"] * D["v"]).dropna()
        turn = _f(tv.tail(20).mean() / tv.tail(60).mean()) if len(tv) >= 60 and tv.tail(60).mean() else None
        tail = _rrg(sc, b)
        x, y = (tail[-1]["x"], tail[-1]["y"]) if tail else (None, None)
        # RS선(최근 1년, 시작=100)
        rr = rs.tail(252)
        base = rr.iloc[0]
        line = [[i.strftime("%Y-%m-%d"), _f(v / base * 100)] for i, v in rr.items()]
        ma = [[i.strftime("%Y-%m-%d"), _f(v / base * 100)] for i, v in ma50.tail(252).items()]
        rows.append({"sym": sym, "name": nm, "phases": ph, "note": note, **r, **a,
                     "above50": bool(rs.iloc[-1] > ma50.iloc[-1]) if not math.isnan(ma50.iloc[-1]) else None,
                     "rs_high": rs_high, "downcap": downcap, "turn": turn,
                     "rrg": tail, "rx": x, "ry": y, "quad": _quad(x, y),
                     "rs_line": line, "rs_ma": ma, "last": D.index[-1].strftime("%Y-%m-%d")})
    return rows, bname, bc.index[-1].strftime("%Y-%m-%d")


def _safe_chart(s, sym):
    try:
        return _chart(s, sym)
    except Exception:
        return None


# ---------------- S&P500 구성 종목: 확산·이익 추정·세부 업종(뒤에서 계산) ----------------
PERIODS = [("x1w", 5), ("x1m", 21), ("x3m", 63), ("x6m", 126)]


def _breadth_compute():
    from sector_ko import SECTOR_KO, SUB_KO
    s = _sess()
    r = s.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", timeout=20)
    tb = pd.read_html(io.StringIO(r.text))[0]
    members = [(str(sym).replace(".", "-"), str(nm), sec, sub)
               for sym, nm, sec, sub in zip(tb["Symbol"], tb["Security"], tb["GICS Sector"], tb["GICS Sub-Industry"])]
    spy = _chart(s, "SPY", "1y")["c"]
    bret = {k: _ret(spy, n) for k, n in PERIODS}

    def px(sym):
        try:
            c = _chart(s, sym, "1y")["c"]
            if len(c) < 200:
                return None
            return {"a200": bool(c.iloc[-1] > c.tail(200).mean()), "hi": bool(c.tail(5).max() >= c.max() * 0.999),
                    **{k: _ret(c, n) for k, n in PERIODS}}
        except Exception:
            return None

    def info(sym):
        """올해 EPS 추정 상향·하향(최근 30일)과 시가총액"""
        out = {}
        try:
            import yfsess
            t = yfsess.ticker(sym)
            try:
                d = t.eps_revisions
                if d is not None and "0y" in d.index:
                    row = d.loc["0y"]
                    out["rev"] = (int(row.get("upLast30days") or 0), int(row.get("downLast30days") or 0))
            except Exception:
                pass
            try:
                out["mcap"] = float(t.fast_info["marketCap"])
            except Exception:
                pass
        except Exception:
            pass
        return out

    syms = [m[0] for m in members]
    with ThreadPoolExecutor(12) as ex:
        P = dict(zip(syms, ex.map(px, syms)))
    with ThreadPoolExecutor(10) as ex:
        I = dict(zip(syms, ex.map(info, syms)))

    def agg(group):
        """종목 묶음 → 시가총액 가중 수익률(시장 대비 %p)·200일선 위 비율·신고가·이익 추정"""
        o = {"n": len(group), "px": 0, "a200": 0, "hi": 0, "rev_n": 0, "up": 0, "down": 0, "mcap": 0.0}
        w = {k: [0.0, 0.0] for k, _ in PERIODS}
        mc = [I[m[0]].get("mcap") for m in group if I[m[0]].get("mcap")]
        fill = float(np.median(mc)) if mc else 1.0
        for m in group:
            p, i = P.get(m[0]), I.get(m[0]) or {}
            cap = i.get("mcap") or fill
            o["mcap"] += cap
            if p:
                o["px"] += 1
                o["a200"] += p["a200"]
                o["hi"] += p["hi"]
                for k, _ in PERIODS:
                    if p[k] is not None and not math.isnan(p[k]):
                        w[k][0] += p[k] * cap
                        w[k][1] += cap
            if i.get("rev"):
                o["rev_n"] += 1
                o["up"] += i["rev"][0]
                o["down"] += i["rev"][1]
        for k, _ in PERIODS:
            o[k] = _f(w[k][0] / w[k][1] - bret[k]) if w[k][1] else None
        o["pct200"] = _f(o["a200"] / o["px"] * 100, 0) if o["px"] else None
        o["rev_ratio"] = _f(o["up"] / (o["up"] + o["down"]) * 100, 0) if (o["up"] + o["down"]) else None
        o["mcap"] = _f(o["mcap"] / 1e9, 1)        # 십억 달러
        return o

    by_sec, by_sub = {}, {}
    for m in members:
        by_sec.setdefault(m[2], []).append(m)
        by_sub.setdefault((m[2], m[3]), []).append(m)
    sectors = {sec: agg(g) for sec, g in by_sec.items()}
    subs = []
    for (sec, sub), g in by_sub.items():
        o = agg(g)
        stocks = []
        for m in sorted(g, key=lambda m: -((I.get(m[0]) or {}).get("mcap") or 0))[:12]:
            p = P.get(m[0]) or {}
            stocks.append({"sym": m[0], "name": m[1], "mcap": _f(((I.get(m[0]) or {}).get("mcap") or 0) / 1e9, 1),
                           **{k: _f(p[k] - bret[k]) if p.get(k) is not None else None for k, _ in PERIODS}})
        subs.append({"sector": sec, "sector_ko": SECTOR_KO.get(sec, sec), "sub": sub, "sub_ko": SUB_KO.get(sub, sub), **o, "stocks": stocks})
    return {"at": time.time(), "updated": time.strftime("%Y-%m-%d %H:%M"), "ver": 2, "sectors": sectors, "subs": subs,
            "n_px": sum(1 for v in P.values() if v), "n_rev": sum(1 for v in I.values() if v.get("rev")),
            "n_cap": sum(1 for v in I.values() if v.get("mcap")), "n": len(members)}


def _breadth_job():
    try:
        d = _breadth_compute()
        if d["n_px"] < 300:
            raise RuntimeError(f"종목 가격을 {d['n_px']}개밖에 못 받았어요")
        _BREADTH.update(state="ready", data=d, error=None)
        try:
            os.makedirs(os.path.dirname(BREADTH_FILE), exist_ok=True)
            json.dump(d, open(BREADTH_FILE, "w"), ensure_ascii=False)
        except Exception:
            pass
    except Exception as e:
        _BREADTH.update(state="failed", error=repr(e)[:150])


def breadth():
    """준비됐으면 결과, 아니면 뒤에서 계산 시작하고 상태만"""
    with _LOCK:
        d = _BREADTH["data"]
        if d is None and os.path.exists(BREADTH_FILE):
            try:
                d = json.load(open(BREADTH_FILE))
                _BREADTH["data"] = d
            except Exception:
                d = None
        fresh = d is not None and d.get("ver") == 2 and time.time() - d.get("at", 0) < BREADTH_TTL
        busy = _BREADTH["state"] == "running" and time.time() - (_BREADTH["started"] or 0) < 600
        if not fresh and not busy:
            _BREADTH.update(state="running", started=time.time())
            threading.Thread(target=_breadth_job, daemon=True).start()
            busy = True
    return {"state": "ready" if fresh else ("running" if busy else _BREADTH["state"]), "data": d, "error": _BREADTH["error"]}


# ---------------- 신호(참고용) ----------------
def _signals(row, b):
    ck = [
        ("rs36", "3·6개월 모두 시장보다 강함", (row["x3m"] or 0) > 0 and (row["x6m"] or 0) > 0),
        ("ma50", "RS선이 50일 평균 위", row["above50"]),
        ("high", "최근 2주 안 RS 52주 신고가", row["rs_high"]),
        ("def", "시장 하락일에 덜 빠짐", None if row["downcap"] is None else row["downcap"] < 1),
        ("turn", "거래대금 늘어나는 중", None if row["turn"] is None else row["turn"] > 1.05),
        ("brd", "섹터 종목 55% 이상 200일선 위", None if not b or b.get("pct200") is None else b["pct200"] >= 55),
        ("eps", "이익 추정 상향이 하향보다 많음", None if not b or b.get("rev_ratio") is None else b["rev_ratio"] >= 55),
    ]
    have = [c for c in ck if c[2] is not None]
    score = sum(1 for c in have if c[2])
    frac = score / len(have) if have else 0
    q = row["quad"]
    if frac >= 0.7 and ck[0][2] and q in ("선도", "약화"):
        lab = ("주도 후보", "lead")
    elif ((row["x1m"] or 0) >= 3 or (row["x1w"] or 0) >= 2) and ((row["x3m"] or 0) <= 0 or (row["x6m"] or 0) <= 0) and frac < 0.6:
        # 짧게 튀었지만 3·6개월 힘이나 체크리스트가 받쳐 주지 않음
        lab = ("순환매 가능성", "rot")
    elif q == "개선":
        lab = ("개선 중 · 다음 후보", "imp")
    elif q == "선도":
        lab = ("강세 유지", "strong")
    elif q == "약화":
        lab = ("힘 빠지는 중", "weak")
    else:
        lab = ("부진", "lag")
    return {"checks": [{"k": k, "t": t, "v": v} for k, t, v in ck], "score": score, "of": len(have),
            "label": lab[0], "cls": lab[1]}


def overview(market="US", force=False):
    market = "KR" if str(market).upper() == "KR" else "US"
    key = "sector:" + market
    hit = _CACHE.get(key)
    if hit and not force and time.time() - hit[0] < TTL:
        out = hit[1]
    else:
        s = _sess()
        cfg = US if market == "US" else KR
        rows, bname, last = _sector_rows(s, cfg)
        out = {"market": market, "bench": bname, "last": last, "updated": time.strftime("%Y-%m-%d %H:%M"),
               "phases": PHASES, "macro": macro(s, market), "rows": rows}
        _CACHE[key] = (time.time(), out)
    out = dict(out)
    br = breadth() if market == "US" else {"state": "na", "data": None}
    bsec = (br.get("data") or {}).get("sectors") or {}
    rows = []
    for r in out["rows"]:
        if r.get("error"):
            rows.append(r)
            continue
        b = bsec.get(r["note"]) if market == "US" else None
        rows.append({**r, "breadth": b, **_signals(r, b)})
    out["rows"] = rows
    bd = br.get("data") or {}
    out["subs"] = bd.get("subs") if market == "US" and bd.get("ver") == 2 else None
    out["breadth"] = {"state": br["state"], "updated": (br.get("data") or {}).get("updated"),
                      "n_px": (br.get("data") or {}).get("n_px"), "n_rev": (br.get("data") or {}).get("n_rev"),
                      "n": (br.get("data") or {}).get("n"), "error": br.get("error")}
    return out
