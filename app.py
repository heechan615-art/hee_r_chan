"""
가치평가 웹앱 — valuate.py 분석 로직을 브라우저에서 사용.

실행:
    ./venv/bin/python app.py
그다음 브라우저에서 http://127.0.0.1:8000 접속.
(5000 포트는 macOS AirPlay 수신기와 충돌하므로 8000 사용. PORT 환경변수로 변경 가능.)
"""
import os
import re
import math
import time
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify, session

# 로컬 실행 편의 — .env가 있으면 환경변수로 읽어들임 (배포에선 Render 환경변수를 그대로 사용).
# valuate·auth가 import 시점에 환경변수를 읽으므로 반드시 그 전에 실행해야 함.
_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_FILE):
    try:
        with open(_ENV_FILE, encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _ek, _ev = _line.split("=", 1)
                    os.environ.setdefault(_ek.strip(), _ev.strip().strip('"').strip("'"))
    except Exception:
        pass

import auth
import kr_data
# valuate(=pandas/numpy/yfinance/bs4/curl_cffi, ~80MB)는 부팅을 가볍게 하려고 지연 로딩.
# → 무료 512MB 인스턴스가 빠르고 가볍게 깨어나 정적 페이지를 즉시 응답(콜드 웨이크 OOM 방지).

import valuate
from valuate import analyze_data   # 부팅 시 로드(측정상 분석 peak 122MB로 512MB에 여유). 안정성 우선.

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.permanent_session_lifetime = timedelta(days=30)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024   # 리포트 PDF 업로드 상한 30MB

# 비회원 맛보기 — 가치평가 하루 5회 무료(한국시간 00시 리셋), 브리핑은 AI 파트만 잠금.
GUEST_LIMIT = int(os.environ.get("GUEST_LIMIT", "5"))
KST = timezone(timedelta(hours=9))   # 배포 서버(Render)는 UTC라 날짜 기준을 한국시간으로 고정

# 무료 Gemini Flash-Lite — 가볍고 과부하가 덜해 안정적(뉴스 2~3문장 분류엔 충분).
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

# 키를 환경변수 또는 로컬 파일(gemini_key.txt)에서 읽음 → 매번 export 안 해도 됨.
_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_key.txt")
if not os.environ.get("GEMINI_API_KEY") and os.path.exists(_KEY_FILE):
    try:
        with open(_KEY_FILE, encoding="utf-8") as _f:
            _k = _f.read().strip()
        if _k:
            os.environ["GEMINI_API_KEY"] = _k
    except Exception:
        pass


@app.errorhandler(500)
@app.errorhandler(Exception)
def _json_500(e):
    """라우트 try/except를 우회한 예외도 JSON으로 반환(진단용)."""
    import traceback
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException) and e.code != 500:
        return e
    return jsonify({"error": f"서버 오류: {repr(e)[:150]}",
                    "trace": traceback.format_exc()[-800:]}), 500


# ------- 간단 TTL 캐시 (여러 명이 같은 종목 조회 시 계산 1번으로) -------
_CACHE = {}   # key -> (ts, value)


def _cache_get(key, ttl):
    v = _CACHE.get(key)
    if v and time.time() - v[0] < ttl:
        return v[1]
    return None


def _cache_put(key, value):
    if len(_CACHE) > 800:            # 폭주 방지용 상한(수업 규모엔 넉넉)
        _CACHE.clear()
    _CACHE[key] = (time.time(), value)


def clean(o):
    """JSON은 NaN/Infinity를 허용 안 함 → None으로 치환(재귀)."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


@app.route("/")
def index():
    return render_template("index.html")


# ----------------------------- 회원 인증 -----------------------------
def _is_member():
    """회원 여부. 인증 미설정(Supabase 없음)이면 전원 회원 취급 → 기존처럼 동작."""
    return (not auth.auth_enabled()) or bool(session.get("user"))


def _guest_uses():
    """비회원의 오늘 사용 횟수. 날짜(한국시간)가 바뀌었으면 0으로 리셋."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if session.get("guest_day") != today:
        session["guest_day"] = today
        session["guest_uses"] = 0
        session.permanent = True
    return int(session.get("guest_uses", 0))


def _guest_left():
    """비회원에게 오늘 남은 가치평가 횟수. 회원이면 None(무제한)."""
    if _is_member():
        return None
    return max(0, GUEST_LIMIT - _guest_uses())


@app.route("/api/auth/me")
def auth_me():
    """로그인 상태 확인. auth_enabled=False면 로그인 없이 앱 사용(미설정 시)."""
    if not auth.auth_enabled():
        return jsonify({"enabled": False})
    return jsonify({"enabled": True, "user": session.get("user"),
                    "guest_left": _guest_left(), "guest_limit": GUEST_LIMIT})


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    d = request.get_json(silent=True) or {}
    ok, msg = auth.register(d.get("username"), d.get("password"), d.get("realname"))
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    d = request.get_json(silent=True) or {}
    ok, msg, u = auth.login(d.get("username"), d.get("password"))
    if ok:
        session["user"] = u
        session.permanent = True
    return jsonify({"ok": ok, "message": msg, "user": u})


@app.route("/api/auth/find_id", methods=["POST"])
def auth_find_id():
    """본명으로 아이디 찾기 — 일치 아이디를 일부 가려서 반환."""
    d = request.get_json(silent=True) or {}
    if not auth.auth_enabled():
        return jsonify({"ids": []})
    ids = auth.find_usernames(d.get("realname"))
    return jsonify({"ids": ids})


@app.route("/api/auth/reset_password", methods=["POST"])
def auth_reset_password():
    """셀프 비밀번호 재설정 — 아이디+본명 확인 후 변경."""
    d = request.get_json(silent=True) or {}
    ok, msg = auth.reset_password(d.get("username"), d.get("realname"), d.get("password"))
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.pop("user", None)
    return jsonify({"ok": True})


def _require_admin():
    u = session.get("user")
    return bool(u and u.get("is_admin"))


@app.route("/api/admin/members")
def admin_members():
    if not _require_admin():
        return jsonify({"error": "관리자 권한이 필요합니다."}), 403
    return jsonify({"members": auth.list_members()})


@app.route("/api/admin/action", methods=["POST"])
def admin_action():
    """관리자: 승인/강퇴/삭제."""
    if not _require_admin():
        return jsonify({"error": "관리자 권한이 필요합니다."}), 403
    d = request.get_json(silent=True) or {}
    uid, act = d.get("id"), d.get("action")
    try:
        if act == "approve":
            auth.approve(uid)
        elif act == "kick":
            auth.kick(uid)
        elif act == "delete":
            auth.delete_member(uid)
        else:
            return jsonify({"error": "알 수 없는 동작"}), 400
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": repr(e)[:120]}), 500


@app.route("/api/analyze")
def api_analyze():
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "종목 코드를 입력하세요."}), 400
    # 비회원 하루 체험 횟수 소진 → 잠금 (프론트에서 가입 안내 표시)
    left = _guest_left()
    if left == 0:
        return jsonify({"error": f"오늘의 무료 체험 {GUEST_LIMIT}회를 모두 사용했습니다. "
                                 "내일 0시에 다시 채워집니다. 회원가입하시면 제한 없이 이용할 수 있어요.",
                        "locked": True}), 402
    ck = "analyze:" + ticker.lower()
    out = _cache_get(ck, 300)        # 5분 캐시 — 여러 명이 같은 종목 조회 시 계산 1회
    if out is None:
        try:
            out = clean(analyze_data(ticker))
        except ValueError as e:      # 종목 못 찾음 등 사용자 안내 메시지는 그대로 노출
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": f"분석 실패: {repr(e)[:150]}"}), 500
        _cache_put(ck, out)
    out = dict(out)                  # 캐시 원본 보존 — 요청별 필드는 복사본에만
    if left is not None:             # 분석에 성공했을 때만 차감
        session["guest_uses"] = _guest_uses() + 1
        session.permanent = True
        out["guest_left"] = _guest_left()
        out["guest_limit"] = GUEST_LIMIT
    return jsonify(out)


@app.route("/api/diagnose", methods=["POST"])
def api_diagnose():
    """사용자가 수정한 재무 숫자로 재무제표 진단 재계산 (순수 함수 diagnose)."""
    import diagnose
    d = request.get_json(silent=True) or {}
    fin = d.get("financials")
    if not fin or not fin.get("years"):
        return jsonify({"error": "재무 데이터가 없습니다."}), 400
    try:
        g = diagnose.diagnose({
            "ticker": d.get("ticker"), "companyName": d.get("name") or d.get("ticker"),
            "sector": d.get("sector") or "",
            "isCyclical": d.get("isCyclical"), "isFinancial": d.get("isFinancial"),
            "financials": fin,
        })
        if g is not None:
            g["waterfall"] = (fin or {}).get("breakdown")
        return jsonify(clean(g))
    except Exception as e:
        return jsonify({"error": f"진단 실패: {repr(e)[:150]}"}), 500


@app.route("/api/per_history")
def api_per_history():
    """미국 개별주 장기 과거 PER (EDGAR EPS ÷ 야후 주가). 공개·6시간 캐시. 미국만."""
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "종목 코드를 입력하세요."}), 400
    ck = "perhist:" + ticker.lower()
    out = _cache_get(ck, 6 * 3600)
    if out is None:
        try:
            import per_hist
            out = per_hist.per_history(ticker)
        except Exception as e:
            return jsonify({"error": f"PER 이력 조회 실패: {repr(e)[:120]}"}), 500
        if not out:
            return jsonify({"empty": True}), 200      # 미국 아님/EDGAR 없음 → 프론트 폴백
        out = clean(out)
        _cache_put(ck, out)
    return jsonify(out)


@app.route("/api/psr_history")
def api_psr_history():
    """개별주 장기 과거 PSR (미국 EDGAR 매출·주식수 / 한국 DART ÷ 야후 주가). 공개·6시간 캐시."""
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "종목 코드를 입력하세요."}), 400
    ck = "psrhist:" + ticker.lower()
    out = _cache_get(ck, 6 * 3600)
    if out is None:
        try:
            import per_hist
            out = per_hist.psr_history(ticker)
        except Exception as e:
            return jsonify({"error": f"PSR 이력 조회 실패: {repr(e)[:120]}"}), 500
        if not out:
            return jsonify({"empty": True}), 200
        out = clean(out)
        _cache_put(ck, out)
    return jsonify(out)


@app.route("/api/eps_history")
def api_eps_history():
    """개별 종목 분기/연간 EPS 이력 + 성장률 + 미래 EPS 추정.
    기업 밸류 탭 기본정보 카드 하단 패널용. 공개(비회원도 조회) — 분석 성공
    후 보조로 불러오므로 무료 횟수 차감 안 함. 6시간 캐시로 부하 최소화."""
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "종목 코드를 입력하세요."}), 400
    ck = "epshist:" + ticker.lower()
    out = _cache_get(ck, 6 * 3600)
    if out is None:
        try:
            d = valuate.eps_history(ticker)
        except Exception as e:
            return jsonify({"error": f"EPS 이력 조회 실패: {repr(e)[:120]}"}), 500
        if not d:
            return jsonify({"error": "EPS 이력 데이터가 부족합니다.", "empty": True}), 200
        out = clean(d)
        _cache_put(ck, out)
    return jsonify(out)


@app.route("/api/related")
def api_related():
    """관련주 찾기 — 키워드/테마 → 한국·미국 관련 상장사 각 10개+ (특징·비즈니스모델).
    공개(비회원도 조회). 키워드 기반이라 24시간 서버 캐시로 Gemini 호출 최소화."""
    kw = (request.args.get("keyword") or "").strip()
    if not kw:
        return jsonify({"error": "키워드를 입력하세요."}), 400
    if len(kw) > 40:
        return jsonify({"error": "키워드가 너무 깁니다."}), 400
    ck = "related:" + kw.lower()
    out = _cache_get(ck, 24 * 3600)
    if out is None:
        try:
            import deepdive
            d = deepdive.related_stocks(kw)
        except Exception as e:
            return jsonify({"error": f"검색 실패: {repr(e)[:150]}"}), 500
        if not d or (not d.get("kr") and not d.get("us")):
            return jsonify({"error": "관련 기업을 찾지 못했습니다. 다른 키워드로 시도해 보세요.",
                            "empty": True}), 200
        out = clean(d)
        _cache_put(ck, out)
    return jsonify(out)


@app.route("/api/company_analysis")
def api_company_analysis():
    """기업 심층 분석(비즈니스모델·기술·시장기대) — 회원 전용."""
    if not _is_member():
        return jsonify({"error": "회원 전용 기능입니다. 로그인해 주세요.", "locked": True}), 402
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "기업 이름 또는 티커를 입력하세요."}), 400
    ck = "company:" + ticker.lower()
    cached = _cache_get(ck, 1800)    # 30분 캐시(AI 지식 기반이라 안정적)
    if cached is not None:
        return jsonify(cached)
    try:
        import kr_data
        import deepdive
        yf_ticker, kr_code6, kr_name = kr_data.resolve_query(ticker)
        name = kr_name or ticker
        out = deepdive.company_analysis(kr_code6 or yf_ticker or ticker, name)
        if not out:
            return jsonify({"error": "AI 분석에 실패했습니다. 잠시 후 다시 시도해 주세요."}), 500
        out = clean(out)
        _cache_put(ck, out)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": f"분석 실패: {repr(e)[:150]}"}), 500


@app.route("/api/company_news")
def api_company_news():
    """기업 최근 뉴스 이슈 정리 + 분석 — 회원 전용."""
    if not _is_member():
        return jsonify({"error": "회원 전용 기능입니다.", "locked": True}), 402
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "기업 이름 또는 티커를 입력하세요."}), 400
    ck = "news:" + ticker.lower()
    cached = _cache_get(ck, 900)     # 15분 캐시(뉴스는 천천히 바뀜)
    if cached is not None:
        return jsonify(cached)
    try:
        import kr_data
        import briefing
        import deepdive
        yf_ticker, kr_code6, kr_name = kr_data.resolve_query(ticker)
        name = kr_name or ticker
        if kr_code6:
            heads = briefing._stock_news(kr_code6, 10)
        else:
            sym = (yf_ticker or ticker).split(".")[0]
            heads = briefing._us_stock_news(sym, 10)
        out = clean(deepdive.analyze_news(name, heads))
        if out and out.get("issues"):   # 성공한 것만 캐시(빈 결과는 재시도 여지)
            _cache_put(ck, out)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": f"분석 실패: {repr(e)[:150]}"}), 500


@app.route("/api/report_analysis", methods=["POST"])
def api_report_analysis():
    """증권사 리포트 PDF 교차분석(최대 5개) — 회원 전용."""
    if not _is_member():
        return jsonify({"error": "회원 전용 기능입니다. 로그인해 주세요.", "locked": True}), 402
    import deepdive
    files = request.files.getlist("files")
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({"error": "PDF 파일을 첨부하세요."}), 400
    if len(files) > deepdive.MAX_REPORTS:
        return jsonify({"error": f"리포트는 최대 {deepdive.MAX_REPORTS}개까지 올릴 수 있습니다."}), 400
    payload = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            return jsonify({"error": f"PDF 파일만 지원합니다: {f.filename}"}), 400
        payload.append((f.filename, f.read()))
    try:
        out = deepdive.report_analysis(payload)
        code = 500 if out.get("error") else 200
        return jsonify(clean(out)), code
    except Exception as e:
        return jsonify({"error": f"분석 실패: {repr(e)[:150]}"}), 500


@app.route("/api/fin_outlook", methods=["POST"])
def api_fin_outlook():
    """재무제표(과거) + 업로드한 리포트·실적보고서(미래) 종합 전망 — 회원 전용."""
    if not _is_member():
        return jsonify({"error": "회원 전용 기능입니다. 로그인해 주세요.", "locked": True}), 402
    import deepdive
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        return jsonify({"error": "PDF 파일을 첨부하세요."}), 400
    if len(files) > deepdive.MAX_REPORTS:
        return jsonify({"error": f"리포트·보고서는 최대 {deepdive.MAX_REPORTS}개까지 올릴 수 있습니다."}), 400
    payload = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            return jsonify({"error": f"PDF 파일만 지원합니다: {f.filename}"}), 400
        payload.append((f.filename, f.read()))
    try:
        out = deepdive.fin_outlook(request.form.get("company", ""),
                                   request.form.get("fin", ""),
                                   request.form.get("overall", ""), payload)
        if not out or out.get("error"):
            return jsonify({"error": (out or {}).get("error")
                            or "AI 전망 생성에 실패했습니다. (Gemini 키/과부하를 확인해 주세요.)"}), 502
        return jsonify(clean(out))
    except Exception as e:
        return jsonify({"error": f"분석 실패: {repr(e)[:150]}"}), 500


@app.route("/api/final_verdict", methods=["POST"])
def api_final_verdict():
    """기업 개요+뉴스+리포트 통합 종합 총평 — 회원 전용."""
    if not _is_member():
        return jsonify({"error": "회원 전용 기능입니다.", "locked": True}), 402
    import deepdive
    d = request.get_json(silent=True) or {}
    if not d.get("report"):
        return jsonify({"error": "리포트 분석 결과가 필요합니다."}), 400
    try:
        out = deepdive.final_verdict(d.get("company"), d.get("news"), d.get("report"))
        if not out:
            return jsonify({"error": "종합 총평 생성에 실패했습니다."}), 500
        return jsonify(clean(out))
    except Exception as e:
        return jsonify({"error": f"분석 실패: {repr(e)[:150]}"}), 500


@app.route("/api/snp")
def api_snp():
    """S&P500 밸류에이션 대시보드 — PER σ밴드·EPS·공포탐욕·VIX·매크로/컨센서스 밸류."""
    import snp
    try:
        return jsonify(clean(snp.overview(force=bool(request.args.get("force")),
                                          period=request.args.get("period", "2020"))))
    except Exception as e:
        return jsonify({"error": f"S&P500 데이터 실패: {repr(e)[:150]}"}), 500


@app.route("/api/snp/upload_factset", methods=["POST"])
def api_snp_upload_factset():
    """FactSet Earnings Insight PDF 수동 업로드 → 컨센서스 EPS 갱신."""
    import snp
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "PDF 파일을 첨부해 주세요."}), 400
    try:
        parsed = snp.apply_factset_upload(f.read())
    except Exception as e:
        return jsonify({"error": f"PDF 파싱 실패: {repr(e)[:120]}"}), 400
    if not parsed:
        return jsonify({"error": "FactSet 리포트에서 값을 찾지 못했습니다. "
                                 "정식 Earnings Insight PDF인지 확인해 주세요."}), 400
    return jsonify(clean(snp.overview(period=request.args.get("period", "2020"))))


def _preview_briefing(out):
    """비회원 맛보기 — 지수·수급·급등락은 그대로, 보고서는 헤드라인+수급해설+첫 테마 1개까지만.
    빅뉴스·나머지 테마·총평은 잘라내고 locked 플래그로 가입 유도."""
    out = dict(out)
    rep = out.get("report")
    if isinstance(rep, dict):
        themes = rep.get("themes") or []
        out["report"] = {
            "headline": rep.get("headline"),
            "supply_comment": rep.get("supply_comment"),
            "themes": themes[:1],                 # 첫 테마만 공개
            "locked_bignews": len(rep.get("bignews") or []),
            "locked_themes": max(0, len(themes) - 1),
        }
    out["locked"] = True
    return out


@app.route("/api/briefing")
def api_briefing():
    """일일 증시 브리핑. day 파라미터 있으면 과거 브리핑 불러오기, list=1이면 날짜 목록."""
    try:
        import briefing
        market = "US" if (request.args.get("market") or "").upper() == "US" else "KR"
        member = _is_member()
        if request.args.get("list"):
            return jsonify({"days": briefing.list_briefings(market)})
        day = request.args.get("day")
        if day:
            if not member:           # 지난 날짜 조회는 회원 전용
                return jsonify({"error": "지난 브리핑은 회원만 볼 수 있습니다.", "locked": True}), 402
            data = briefing.load_briefing(day, market)
            return jsonify(clean(data) if data else {"error": "해당 날짜 브리핑이 없습니다."})
        out = clean(briefing.daily_briefing(market))
        if not member:               # 맛보기: 헤드라인·수급·첫 테마까지만, 나머지 회원 전용
            out = _preview_briefing(out)
        return jsonify(out)
    except Exception as e:
        import traceback
        return jsonify({"error": f"브리핑 실패: {repr(e)[:150]}",
                        "trace": traceback.format_exc()[-800:]}), 500


# ----------------------------- 실적 카드 -----------------------------
# 카드는 히르찬 컴퓨터의 earnings-cards(09번)에서 만들어 static/earnings/ 로 보냄(publish.py).
# 목록은 static/earnings/manifest.json, 여기서는 한 묶음을 zip으로 묶어 주기만 한다.
EARN_DIR = os.path.join(app.root_path, "static", "earnings")


EARNCARDS = os.path.join(app.root_path, "earncards")   # 카드 코드 복사본(원본 ~/projects/earnings-cards)


@app.route("/api/earnings")
def api_earnings():
    """검색한 기업의 실적 카드(HTML)·해석 — 최근 분기와 그 전 분기. 미발표면 banner 로 안내.
    PNG는 브라우저에서 만든다(서버에 크롬 엔진 없음). 30분 캐시."""
    import sys
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "기업 이름이나 종목 코드를 입력하세요."}), 400
    yf_ticker, code6, _name = kr_data.resolve_query(q)
    if not yf_ticker:  # '애플'·'엔비디아'처럼 미국 종목 한글 이름 → 네이버 자동완성의 미국 상장 종목 (히르찬 차트와 같은 방식)
        try:
            items = requests.get("https://ac.stock.naver.com/ac", params={"q": q, "target": "stock"},
                                 headers={"User-Agent": "Mozilla/5.0"}, timeout=6).json().get("items", [])
        except Exception:
            items = []
        us = [it for it in items if it.get("nationCode") == "USA" and it.get("code")
              and it.get("typeCode") in ("NASDAQ", "NYSE", "AMEX", "NYSEARCA", "BATS")]
        if us:
            yf_ticker, code6 = us[0]["code"].replace(".", "-"), None
    if not yf_ticker:
        return jsonify({"error": f"'{q}' 종목을 찾지 못했어요. 이름이나 코드를 확인해 주세요."}), 404
    code = code6 or yf_ticker.upper()
    ck = "earn:" + code
    out = _cache_get(ck, 1800)
    if out is None:
        if EARNCARDS not in sys.path:
            sys.path.insert(0, EARNCARDS)
        import webcards
        from collectors import sec as ec_sec, dart as ec_dart
        try:
            out = clean(webcards.build(code))
        except (ec_sec.SecError, ec_dart.DartError) as e:
            return jsonify({"error": str(e)}), 404
        _cache_put(ck, out)
    return jsonify(out)


@app.route("/api/earnings/calendar")
def api_earnings_calendar():
    """실적 발표 달력 한 주(월~금): 미국 나스닥 달력(시총 100억$ 이상) + 한국 DART IR 개최·잠정실적 공시. 3시간 캐시"""
    import sys
    import re as _re
    w = (request.args.get("week") or "").strip()
    if w and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", w):
        return jsonify({"error": "잘못된 날짜예요."}), 400
    if EARNCARDS not in sys.path:
        sys.path.insert(0, EARNCARDS)
    import ecal
    from datetime import date as _d, timedelta as _td
    t = _d.fromisoformat(w) if w else datetime.now(KST).date()
    start = (t - _td(days=t.weekday())).isoformat()
    ck = "ecal:" + start
    out = _cache_get(ck, 3 * 3600)
    if out is None:
        out = clean(ecal.week(start))
        out["today"] = datetime.now(KST).date().isoformat()
        _cache_put(ck, out)
    return jsonify(out)


EXTRA_LIMIT = int(os.environ.get("EARN_EXTRA_LIMIT", "10"))  # 방문자 1명이 하루에 AI로 새로 만들 수 있는 횟수(넘으면 숫자 규칙판)


@app.route("/api/earnings/extra")
def api_earnings_extra():
    """검색하면 자동으로 만드는 이슈·어닝콜 카드. Gemini가 원문(미국 8-K 보도자료)을 읽고 쓰고,
    earncards/aiwrite.py가 숫자·인용·금지 표현을 검증해 통과한 문장만 씀. AI 실패 시 숫자 규칙 기본판.
    같은 기업·분기는 24시간 캐시(누가 만들든 모두가 같이 봄). AI 새로 만들기는 1인 하루 EARN_EXTRA_LIMIT회,
    넘으면 AI 없이 숫자 규칙판(별도 캐시)으로 보여 줌."""
    import sys
    import re as _re
    q = (request.args.get("q") or "").strip()
    quarter = (request.args.get("quarter") or "").strip().upper()
    if not q or not _re.fullmatch(r"\d{4}Q[1-4]", quarter):
        return jsonify({"error": "잘못된 요청이에요."}), 400
    yf_ticker, code6, _name = kr_data.resolve_query(q)
    if not yf_ticker:
        try:
            items = requests.get("https://ac.stock.naver.com/ac", params={"q": q, "target": "stock"},
                                 headers={"User-Agent": "Mozilla/5.0"}, timeout=6).json().get("items", [])
        except Exception:
            items = []
        us = [it for it in items if it.get("nationCode") == "USA" and it.get("code")]
        if us:
            yf_ticker, code6 = us[0]["code"].replace(".", "-"), None
    if not yf_ticker:
        return jsonify({"error": f"'{q}' 종목을 찾지 못했어요."}), 404
    code = code6 or yf_ticker.upper()
    ck = f"earnx:{code}:{quarter}"
    out = _cache_get(ck, 86400)
    if out is not None:
        return jsonify(out)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if session.get("earnx_day") != today:
        session["earnx_day"], session["earnx_uses"] = today, 0
        session.permanent = True
    use_ai = session.get("earnx_uses", 0) < EXTRA_LIMIT
    if not use_ai:
        out = _cache_get(ck + ":rule", 86400)
        if out is not None:
            return jsonify(out)
    if EARNCARDS not in sys.path:
        sys.path.insert(0, EARNCARDS)
    import webcards
    import deepdive
    from collectors import sec as ec_sec, dart as ec_dart
    symbol = yf_ticker if code6 is None else yf_ticker   # 국내는 005930.KS 같은 야후 표기 그대로
    try:
        out = clean(webcards.build_extra(code, quarter, symbol, deepdive._gemini_json if use_ai else None))
    except (ec_sec.SecError, ec_dart.DartError, ValueError) as e:
        return jsonify({"error": str(e)}), 404
    if use_ai:
        session["earnx_uses"] = session.get("earnx_uses", 0) + 1
        _cache_put(ck if out.get("ai") else ck + ":rule", out)
    else:
        out["limited"] = True
        _cache_put(ck + ":rule", out)
    return jsonify(out)


# ---------- 내 계좌 비중 탭 ----------
# 계좌·매매 기록은 방문자 브라우저에만 저장. 서버는 종목 찾기·현재가·배당/실적 일정·이슈만 준다.
PF_ISSUE_LIMIT = int(os.environ.get("PF_ISSUE_LIMIT", "30"))   # 1인 하루 AI 이슈 정리 횟수(넘으면 기사 목록만)


@app.route("/api/pf/resolve")
def api_pf_resolve():
    import portfolio
    q = (request.args.get("q") or "").strip()[:40]
    if not q:
        return jsonify({"error": "종목 이름이나 티커를 입력해 주세요."}), 400
    ck = "pfres:" + q.lower()
    out = _cache_get(ck, 3600)
    if out is None:
        out = portfolio.resolve(q)
        if not out:
            return jsonify({"error": f"'{q}' 종목을 찾지 못했어요. 이름이나 티커를 확인해 주세요."}), 404
        _cache_put(ck, out)
    return jsonify(out)


@app.route("/api/pf/quotes")
def api_pf_quotes():
    import portfolio
    syms = [s for s in (request.args.get("s") or "").split(",") if re.fullmatch(r"[A-Za-z0-9.\-=^]{1,15}", s)]
    return jsonify(clean(portfolio.quotes(syms)))


@app.route("/api/pf/fx")
def api_pf_fx():
    """매수일의 원/달러 환율(달러 종목 환차손익 계산용)"""
    import portfolio
    d = (request.args.get("d") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        return jsonify({"error": "날짜 형식이 잘못됐어요."}), 400
    v = portfolio.fx_on(d)
    return jsonify({"date": d, "fx": v}) if v else (jsonify({"error": "그날 환율을 찾지 못했어요."}), 404)


@app.route("/api/pf/info")
def api_pf_info():
    import portfolio
    sym = (request.args.get("s") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,15}", sym):
        return jsonify({"error": "잘못된 요청이에요."}), 400
    ck = "pfinfo:" + sym.upper()
    out = _cache_get(ck, 6 * 3600)
    if out is None:
        out = clean(portfolio.info(sym))
        _cache_put(ck, out)
    return jsonify(out)


@app.route("/api/pf/issues")
def api_pf_issues():
    import portfolio
    import deepdive
    sym = (request.args.get("s") or "").strip()
    name = (request.args.get("n") or sym).strip()[:40]
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,15}", sym):
        return jsonify({"error": "잘못된 요청이에요."}), 400
    ck = "pfiss:" + sym.upper()
    out = _cache_get(ck, 6 * 3600)
    if out is not None:
        return jsonify(out)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if session.get("pfiss_day") != today:
        session["pfiss_day"], session["pfiss_uses"] = today, 0
        session.permanent = True
    use_ai = session.get("pfiss_uses", 0) < PF_ISSUE_LIMIT
    out = clean(portfolio.issues(sym, name, deepdive._gemini_json if use_ai else None))
    if out.get("ai"):
        session["pfiss_uses"] = session.get("pfiss_uses", 0) + 1
        _cache_put(ck, out)
    elif not use_ai:
        out["limited"] = True
    return jsonify(out)


@app.route("/api/earnings_cards/zip")
def earnings_cards_zip():
    import io
    import json
    import re
    import zipfile
    from flask import send_file
    bid = request.args.get("id", "")
    size = request.args.get("size", "1080x1080")
    if not re.fullmatch(r"[A-Za-z0-9.\-]+_\d{4}Q[1-4]", bid) or not re.fullmatch(r"\d{3,4}x\d{3,4}", size):
        return jsonify({"error": "잘못된 요청이에요."}), 400
    try:
        with open(os.path.join(EARN_DIR, "manifest.json"), encoding="utf-8") as f:
            item = next(b for b in json.load(f)["items"] if b["id"] == bid)
    except (OSError, StopIteration, ValueError, KeyError):
        return jsonify({"error": "카드를 찾지 못했어요."}), 404
    buf, n = io.BytesIO(), 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:   # PNG는 이미 압축돼 있어 그대로 담음
        for c in item["cards"]:
            rel = c["sizes"].get(size)
            path = os.path.join(EARN_DIR, rel) if rel else None
            if path and os.path.isfile(path):
                n += 1
                z.write(path, f"{n}_{c['title']}.png")
    if not n:
        return jsonify({"error": "이 크기의 카드가 없어요."}), 404
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{item['name']}_{item['quarter']}_실적카드_{size}.zip")


@app.route("/api/peers")
def api_peers():
    """동종업계 비교 — 자동 피어 그룹 + 수동 추가(extra) 종목 지표. (무거워서 별도 호출)"""
    import peers
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "종목 코드를 입력하세요."}), 400
    extra = [e for e in (request.args.get("extra") or "").split(",") if e.strip()]
    try:
        return jsonify(clean(peers.compare(ticker, extra)))
    except Exception as e:
        return jsonify({"error": f"비교 실패: {repr(e)[:150]}"}), 500


@app.route("/api/ai_factor", methods=["POST"])
def api_ai_factor():
    """멀티플(PER) 변화가 외부요인인지 내부요인인지 무료 Gemini로 추정.
    GEMINI_API_KEY가 없으면 안내 메시지 반환(기능 비활성)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return jsonify({"error": "AI 추정 기능은 무료 Gemini API 키가 필요합니다. "
                                 "aistudio.google.com/apikey 에서 무료로 발급(신용카드 불필요)한 뒤 "
                                 "'export GEMINI_API_KEY=...' 하고 앱을 재시작하세요."}), 400

    d = request.get_json(silent=True) or {}
    name = d.get("name", "해당 종목")
    if d.get("driver") != "멀티플":
        return jsonify({"note": "이 종목은 실적 주도라 멀티플 요인 추정이 필요 없습니다."})

    news = [str(t) for t in (d.get("news") or [])][:6]
    headlines = "\n".join(f"- {t}" for t in news) or "(수집된 뉴스 없음)"
    prompt = (
        f"종목: {name}\n"
        f"최근 약 1년간 주가 흐름은 '멀티플(PER) 재평가'가 주도했고, "
        f"PER 변화율은 약 {d.get('per_chg')}%입니다.\n"
        f"최근 뉴스 헤드라인:\n{headlines}\n\n"
        "이 멀티플(PER) 변화가 (A) 외부요인 — 거시경제·금리·환율·섹터 전반·시장 심리 — 때문인지, "
        "(B) 내부요인 — 이 기업 고유의 실적 기대·신제품·수주·지배구조·개별 이슈 — 때문인지 추정해줘.\n\n"
        "규칙:\n"
        "- 한국어로 2~3문장만. 군더더기·서론 없이 결론부터.\n"
        "- 확정이 아니라 '추정'임을 전제로.\n"
        "- 뉴스가 부족하면 '뉴스가 부족해 단정 어려움'이라고 밝혀줘.\n"
        "- 외부/내부 중 어느 쪽 비중이 커 보이는지 한 단어로 먼저 언급."
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        # thinkingLevel low = '생각' 최소화 → 더 빠르고 빈 응답 방지.
        # (구 thinkingBudget:0은 flash-lite-latest에서 400 INVALID_ARGUMENT로 거부됨)
        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.4,
                             "thinkingConfig": {"thinkingLevel": "low"}},
    }
    last = "알 수 없음"
    for _attempt in range(3):  # 과부하(429/503)·타임아웃 시 자동 재시도
        try:
            r = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json=payload, timeout=60)
            if r.status_code == 200:
                data = r.json()
                cands = data.get("candidates") or []
                if not cands:
                    return jsonify({"error": f"응답 없음(안전 필터 차단 가능): {data.get('promptFeedback', {})}"}), 502
                parts = (cands[0].get("content") or {}).get("parts") or []
                text = "".join(p.get("text", "") for p in parts).strip()
                if text:
                    return jsonify({"text": text})
                last = "빈 응답"
            elif r.status_code in (429, 503):
                last = f"모델 과부하({r.status_code})"
                time.sleep(2)
                continue
            else:
                return jsonify({"error": f"Gemini 오류 {r.status_code}: {r.text[:160]}"}), 502
        except requests.exceptions.Timeout:
            last = "응답 지연(타임아웃)"
            continue
        except Exception as e:
            return jsonify({"error": f"AI 호출 실패: {repr(e)[:160]}"}), 500
    return jsonify({"error": f"AI가 지금 붐빕니다({last}). 잠시 후 버튼을 다시 눌러주세요."}), 503


if __name__ == "__main__":
    # 로컬 실행용. 배포(Render 등)에서는 gunicorn이 app 객체를 직접 구동하므로 이 블록은 안 탐.
    # DEBUG 환경변수가 "0"이 아니면 로컬 디버그 모드.
    debug = os.environ.get("DEBUG", "1") != "0"
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=int(os.environ.get("PORT", 8000)), debug=debug)
