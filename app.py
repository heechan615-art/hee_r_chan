"""
가치평가 웹앱 — valuate.py 분석 로직을 브라우저에서 사용.

실행:
    ./venv/bin/python app.py
그다음 브라우저에서 http://127.0.0.1:8000 접속.
(5000 포트는 macOS AirPlay 수신기와 충돌하므로 8000 사용. PORT 환경변수로 변경 가능.)
"""
import os
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

from valuate import analyze_data
import auth

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.permanent_session_lifetime = timedelta(days=30)

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
    try:
        out = clean(analyze_data(ticker))
    except ValueError as e:          # 종목 못 찾음 등 사용자 안내 메시지는 그대로 노출
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"분석 실패: {repr(e)[:150]}"}), 500
    if left is not None:             # 분석에 성공했을 때만 차감
        session["guest_uses"] = _guest_uses() + 1
        session.permanent = True
        out["guest_left"] = _guest_left()
        out["guest_limit"] = GUEST_LIMIT
    return jsonify(out)


@app.route("/api/snp")
def api_snp():
    """S&P500 밸류에이션 대시보드 — PER σ밴드·EPS·공포탐욕·VIX. (snp.py에서 6시간 캐시)"""
    import snp
    try:
        return jsonify(clean(snp.overview(force=bool(request.args.get("force")))))
    except Exception as e:
        return jsonify({"error": f"S&P500 데이터 실패: {repr(e)[:150]}"}), 500


@app.route("/api/briefing")
def api_briefing():
    """일일 증시 브리핑. day 파라미터 있으면 과거 브리핑 불러오기, list=1이면 날짜 목록."""
    import briefing
    market = "US" if (request.args.get("market") or "").upper() == "US" else "KR"
    member = _is_member()
    try:
        if request.args.get("list"):
            return jsonify({"days": briefing.list_briefings(market)})
        day = request.args.get("day")
        if day:
            if not member:           # 지난 날짜 조회는 회원 전용
                return jsonify({"error": "지난 브리핑은 회원만 볼 수 있습니다.", "locked": True}), 402
            data = briefing.load_briefing(day, market)
            return jsonify(clean(data) if data else {"error": "해당 날짜 브리핑이 없습니다."})
        out = clean(briefing.daily_briefing(market))
        if not member:               # 맛보기: 지수·매크로·급등락만, AI 파트는 잠금
            out = dict(out, ai=None, bignews=None, locked=True)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": f"브리핑 실패: {repr(e)[:150]}"}), 500


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
