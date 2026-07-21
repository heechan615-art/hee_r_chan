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
from flask import Flask, render_template, request, jsonify

from valuate import analyze_data

app = Flask(__name__)

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


@app.route("/api/analyze")
def api_analyze():
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "종목 코드를 입력하세요."}), 400
    try:
        return jsonify(clean(analyze_data(ticker)))
    except ValueError as e:          # 종목 못 찾음 등 사용자 안내 메시지는 그대로 노출
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"분석 실패: {repr(e)[:150]}"}), 500


@app.route("/api/briefing")
def api_briefing():
    """일일 증시 브리핑. day 파라미터 있으면 과거 브리핑 불러오기, list=1이면 날짜 목록."""
    import briefing
    market = "US" if (request.args.get("market") or "").upper() == "US" else "KR"
    try:
        if request.args.get("list"):
            return jsonify({"days": briefing.list_briefings(market)})
        day = request.args.get("day")
        if day:
            data = briefing.load_briefing(day, market)
            return jsonify(clean(data) if data else {"error": "해당 날짜 브리핑이 없습니다."})
        return jsonify(clean(briefing.daily_briefing(market)))
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
        # thinkingBudget 0 = '생각' 끔 → 더 빠르고 빈 응답 방지.
        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.4,
                             "thinkingConfig": {"thinkingBudget": 0}},
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
