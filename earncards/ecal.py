"""실적 발표 달력 — 한 주(월~금) 날짜별로 실적 발표 기업.

- 미국: 나스닥 실적 달력 API(api.nasdaq.com/api/calendar/earnings?date=), 시가총액 순. 시각은 장 전·장 후(미국 동부)
- 한국 발표 예정: DART '기업설명회(IR) 개최' 공시 본문의 일시·목적·내용에 '실적'이 있는 행사
- 한국 발표 완료: DART '영업(잠정)실적' 공시가 나온 날
week("2026-10-26") → {"start", "days": [{"date", "us": [...], "kr": [...]}]}
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import requests

from collectors import dart

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)
US_MIN_CAP = 10e9          # 미국은 시가총액 100억 달러 이상만 (하루 수백 곳이라)
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
_NAMES = None


def _ko_names() -> dict:
    """config/brands.yaml 의 한국어 이름 (대표 기업)"""
    global _NAMES
    if _NAMES is None:
        import yaml
        cfg = yaml.safe_load((ROOT / "config" / "brands.yaml").read_text()) or {}
        _NAMES = {k: v.get("name") for k, v in cfg.items() if isinstance(v, dict)}
    return _NAMES


_KO_US = None


def _ko_us(syms: list[str]) -> dict:
    """미국 티커 → 네이버 증권 한글 이름(코카콜라·보잉·로빈후드). 한글 이름이 없는 종목은 빈 값(영문 유지).
    이름은 거의 안 바뀌어서 cache/ko_names_us.json 에 계속 쌓고, 못 찾은 것만 30일 뒤 다시 찾는다."""
    global _KO_US
    path = CACHE / "ko_names_us.json"
    if _KO_US is None:
        _KO_US = json.loads(path.read_text()) if path.exists() else {}
    now = time.time()
    todo = [s for s in set(syms) if s and (s not in _KO_US or (not _KO_US[s][0] and now - _KO_US[s][1] > 30 * 86400))]

    def one(sym):
        want = sym.replace("-", " ").replace(".", " ").upper()
        try:
            r = requests.get("https://ac.stock.naver.com/ac", params={"q": want, "target": "stock"}, headers=UA, timeout=8)   # BRK-B → "BRK B"(네이버 표기)
            for it in r.json().get("items", []):
                if it.get("nationCode") == "USA" and (it.get("code") or "").replace(".", " ").upper() == want:
                    nm = re.sub(r"\s*(Class [A-Z]|보통주|ADR)$", "", it.get("name") or "").strip()
                    return sym, (nm if re.search(r"[가-힣]", nm) else "")
            return sym, ""
        except Exception:
            return sym, None            # 네트워크 오류는 저장하지 않음(다음에 다시)
    if todo:
        with ThreadPoolExecutor(8) as ex:
            for sym, nm in ex.map(one, todo):
                if nm is not None:
                    _KO_US[sym] = [nm, now]
        path.write_text(json.dumps(_KO_US, ensure_ascii=False))
    return {s: _KO_US[s][0] for s in syms if s in _KO_US and _KO_US[s][0]}


def _short(name: str) -> str:
    return re.sub(r",?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Holdings?|Company|Co\.|plc|p\.l\.c\.|PLC|Ltd\.?|Limited|N\.V\.|S\.A\.|AG|SE|Class [A-C].*)$",
                  "", name or "").strip()


# ---------- 미국 ----------

def us_day(d: date) -> list[dict]:
    path = CACHE / f"cal_us_{d.isoformat()}.json"
    fresh = 6 * 3600 if d >= date.today() - timedelta(days=1) else 30 * 86400
    if path.exists() and time.time() - path.stat().st_mtime < fresh:
        return json.loads(path.read_text())
    try:
        r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": d.isoformat()},
                         headers=UA, timeout=20)
        rows = (r.json().get("data") or {}).get("rows") or []
    except Exception:
        return []
    out = []
    for x in rows:
        try:
            cap = float(re.sub(r"[^\d.]", "", x.get("marketCap") or "") or 0)
        except ValueError:
            cap = 0
        if cap < US_MIN_CAP:
            continue
        sym = (x.get("symbol") or "").strip()
        t = x.get("time") or ""
        out.append({"code": sym, "name": _ko_names().get(sym) or _short(x.get("name")), "en": _short(x.get("name")), "cap": cap,
                    "when": "장 전" if "pre" in t else ("장 후" if "after" in t else "시간 미정"),
                    "eps_est": (x.get("epsForecast") or "").strip() or None,
                    "fq": x.get("fiscalQuarterEnding")})
    out.sort(key=lambda z: -z["cap"])
    seen, uniq = set(), []
    # 같은 회사 여러 주식 거르기는 영문 이름으로(한글 이름은 아래에서 붙임)
    for z in out:  # GOOG·GOOGL, BRK-A·BRK-B 같은 같은 회사 여러 주식
        k = re.sub(r"\s*\(.*?\)|\s*Class.*$", "", z["en"]).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(z)
    out = uniq
    ko = _ko_us([z["code"] for z in out if z["name"] == z["en"]])
    for z in out:
        if z["code"] in ko:
            z["name"] = ko[z["code"]]
    path.write_text(json.dumps(out, ensure_ascii=False))
    return out


# ---------- 한국 ----------

def _dart_list(bgn: date, end: date, detail: str) -> list[dict]:
    # 기업설명회 안내공시가 수시공시·공정공시 어느 쪽으로든 나와서 거래소 공시(I) 전체를 본다
    key = f"cal_kr_list_I_{bgn:%Y%m%d}_{end:%Y%m%d}.json"
    path = CACHE / key
    if path.exists() and (end < date.today() or time.time() - path.stat().st_mtime < 3 * 3600):
        return json.loads(path.read_text())
    k = dart._key()

    def page(n):
        return requests.get("https://opendart.fss.or.kr/api/list.json",
                            params={"crtfc_key": k, "bgn_de": f"{bgn:%Y%m%d}", "end_de": f"{end:%Y%m%d}",
                                    "pblntf_ty": "I", "page_no": n, "page_count": 100}, timeout=30).json()
    first = page(1)
    if first.get("status") != "000":
        return []
    rows = list(first.get("list", []))
    with ThreadPoolExecutor(6) as ex:
        for d in ex.map(page, range(2, int(first.get("total_page", 1)) + 1)):
            rows += d.get("list", []) if d.get("status") == "000" else []
    keep = [r for r in rows if r.get("stock_code") and r.get("corp_cls") in ("Y", "K")
            and ("기업설명회" in r["report_nm"] or ("잠정" in r["report_nm"] and "실적" in r["report_nm"]))]
    path.write_text(json.dumps(keep, ensure_ascii=False))
    return keep


def _ir_doc(rcept_no: str) -> dict | None:
    """IR 개최 공시 본문 → {date, time, text} (공시는 바뀌지 않으니 계속 보관)"""
    path = CACHE / f"cal_kr_ir_{rcept_no}.json"
    if path.exists():
        return json.loads(path.read_text())
    try:
        r = requests.get("https://opendart.fss.or.kr/api/document.xml",
                         params={"crtfc_key": dart._key(), "rcept_no": rcept_no}, timeout=30)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        raw = z.read(z.namelist()[0])
        for enc in ("utf-8", "euc-kr", "cp949"):
            try:
                s = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        s = re.sub(r"<[^>]+>", " ", s)
        s = re.sub(r"\s+", " ", s)
    except Exception:
        return None
    m = re.search(r"일시.{0,80}?(\d{4}-\d{2}-\d{2})", s)
    tm = re.search(r"(\d{4}-\d{2}-\d{2})\D{0,40}?(\d{1,2}:\d{2})", s[m.start():] if m else s)
    # 형식이 두 가지: '개최목적·주요 설명회내용(요약)' / '실시목적·주요내용'
    parts = re.findall(r"(?:개최목적|실시목적|주요\s*(?:설명회)?\s*내용(?:\(요약\))?)\s*(.{0,90}?)\s*(?=\d{1,2}\.\s|$)", s)
    meth = re.search(r"(?:개최|실시)방법\s*(.{0,30}?)\s*(?=\d{1,2}\.\s)", s)
    out = {"date": m.group(1) if m else None, "time": tm.group(2) if tm else None,
           "text": " / ".join(p.strip() for p in parts if p.strip())[:160],
           "method": meth.group(1).strip() if meth else None}
    path.write_text(json.dumps(out, ensure_ascii=False))
    return out


def kr_week(start: date, end: date) -> dict:
    """{날짜: [기업]} — 예정(IR)·완료(잠정실적)"""
    today = date.today()
    out: dict = {}
    seen = set()
    # 완료: 그 주의 잠정실적 공시
    if start <= today:
        for r in _dart_list(start, min(end, today), "I"):
            if "잠정" not in r["report_nm"] or "정정" in r["report_nm"]:
                continue
            d = f"{r['rcept_dt'][:4]}-{r['rcept_dt'][4:6]}-{r['rcept_dt'][6:]}"
            if (r["stock_code"], d) in seen:
                continue
            seen.add((r["stock_code"], d))
            out.setdefault(d, []).append({"code": r["stock_code"], "name": r["corp_name"], "when": "잠정실적 공시",
                                          "kospi": r.get("corp_cls") == "Y",
                                          "done": True, "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}"})
    # 예정: 3주 전부터 나온 IR 개최 공시 중 그 주에 열리고 '실적'을 다루는 것
    irs = [r for r in _dart_list(start - timedelta(days=21), min(end, today), "I") if "기업설명회" in r["report_nm"]]
    with ThreadPoolExecutor(8) as ex:
        docs = list(ex.map(lambda r: _ir_doc(r["rcept_no"]), irs))
    for r, doc in zip(irs, docs):
        if not doc or not doc.get("date") or not (start.isoformat() <= doc["date"] <= end.isoformat()):
            continue
        if "실적" not in (doc.get("text") or ""):
            continue
        key = (r["stock_code"], doc["date"])
        if key in seen:
            continue
        seen.add(key)
        tx = (doc.get("text") or "") + " " + (doc.get("method") or "")
        ndr = "NDR" in tx or "Non-Deal" in tx or "1:1" in tx or "One-on-one" in tx
        out.setdefault(doc["date"], []).append({
            "code": r["stock_code"], "name": r["corp_name"], "kospi": r.get("corp_cls") == "Y",
            "when": ("실적 설명 IR(투자자 미팅)" if ndr else ("컨퍼런스콜" if "컨퍼런스" in tx else "실적발표 IR"))
                    + (f" {doc['time']}" if doc.get("time") and not ndr else ""),
            "done": doc["date"] < today.isoformat(), "ndr": ndr,
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}"})
    for d in out.values():
        d.sort(key=lambda z: (z.get("ndr", False), not z.get("kospi"), z["name"]))  # 실적발표 행사 → 코스피 → 이름
    return out


def week(start_s: str | None = None) -> dict:
    t = date.fromisoformat(start_s) if start_s else date.today()
    start = t - timedelta(days=t.weekday())
    end = start + timedelta(days=4)
    days = [start + timedelta(days=i) for i in range(5)]
    with ThreadPoolExecutor(5) as ex:
        us = list(ex.map(us_day, days))
    try:
        kr = kr_week(start, end) if os.environ.get("DART_API_KEY") else {}
    except Exception:
        kr = {}
    today = date.today().isoformat()
    return {"start": start.isoformat(), "today": today, "us_min_cap": US_MIN_CAP,
            "days": [{"date": d.isoformat(), "us": [dict(x, done=d.isoformat() < today) for x in u],
                      "kr": kr.get(d.isoformat(), [])} for d, u in zip(days, us)]}
