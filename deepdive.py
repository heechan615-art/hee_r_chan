"""
기업 심층 분석 모듈
====================
1) company_analysis(ticker, name) — 기업 비즈니스모델·핵심기술·사업성·시장기대/우려 (AI 지식 기반)
2) report_analysis(files)         — 증권사 리포트 PDF N개 교차분석
   (각 리포트 요약 + 공통 의견/이견/긍정·부정 근거/종합)

Gemini(gemini-flash-lite-latest) 사용. 리포트 PDF는 pypdf로 텍스트 추출,
추출이 빈약하면 Gemini에 PDF 원본(inline)을 넘겨 직접 읽힘(스캔본 대비).
"""
import os
import io
import json
import base64
import requests

MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
MAX_REPORTS = 5


def _parse_json_loose(txt):
    if not txt:
        return None
    t = txt.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t.strip("`")
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    try:
        return json.loads(t)
    except Exception:
        pass
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except Exception:
            pass
    return None


def _gemini_json(prompt, pdf_parts=None, max_tokens=8192, temp=0.4, tries=3):
    """Gemini에 JSON 응답 요청. pdf_parts: [(mime, bytes)] 있으면 멀티모달로 첨부. 실패 시 None."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    parts = [{"text": prompt}]
    for mime, raw in (pdf_parts or []):
        parts.append({"inline_data": {"mime_type": mime,
                                      "data": base64.b64encode(raw).decode()}})
    for attempt in range(tries):
        try:
            r = requests.post(
                _URL, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"contents": [{"parts": parts}],
                      "generationConfig": {"maxOutputTokens": max_tokens,
                                           "temperature": temp + attempt * 0.05,
                                           "responseMimeType": "application/json",
                                           "thinkingConfig": {"thinkingLevel": "low"}}},
                timeout=90)
            if r.status_code == 200:
                ps = (r.json()["candidates"][0]["content"].get("parts") or [])
                obj = _parse_json_loose("".join(p.get("text", "") for p in ps))
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass
    return None


# ----------------------------- 1) 기업 개요 분석 -----------------------------
def company_analysis(ticker, name=None):
    """기업 비즈니스모델·기술·사업성·시장기대 분석 (AI 지식 기반)."""
    who = f"{name}({ticker})" if name and name != ticker else ticker
    prompt = (
        f"너는 증권사 리서치센터 애널리스트야. '{who}' 기업을 처음 보는 투자자에게 "
        "이 기업이 무엇을 하는 회사인지 깊이 있게 설명해줘. 아는 범위에서 사실 기반으로 쓰고, "
        "불확실하면 '추정'임을 밝혀. 아래 JSON 스키마로만 답해(마크다운 없이 순수 JSON):\n"
        "{\n"
        '  "name": "정식 회사명",\n'
        '  "oneliner": "이 회사를 한 문장으로",\n'
        '  "business": "비즈니스 모델 — 무엇을 팔아 어떻게 돈을 버는지 3~5문장",\n'
        '  "segments": [ {"name":"사업부문명", "desc":"설명·매출비중 추정 한 줄"} ],\n'
        '  "tech": "핵심 기술·경쟁력·진입장벽(해자) 3~4문장",\n'
        '  "market_expectation": "시장(투자자)이 이 기업에 기대하는 성장 스토리 3~4문장",\n'
        '  "risks": [ "우려·리스크 요인 (2~4개)" ],\n'
        '  "catalysts": [ "주가 상승 촉매·관전 포인트 (2~4개)" ],\n'
        '  "summary": "투자 관점 종합 3~4문장"\n'
        "}\n"
        "규칙: 존댓말. 특정 회사를 확신 못 하면 oneliner에 '해당 티커 정보가 부족합니다'라고 밝혀. "
        "매수·매도 권유 금지. 반드시 유효한 JSON.")
    return _gemini_json(prompt, max_tokens=4096, temp=0.45, tries=3)


# ----------------------------- 1-b) 최근 이슈 & 분석 -----------------------------
def analyze_news(name, headlines):
    """최근 뉴스 헤드라인 → 핵심 이슈 정리 + 분석. headlines: [str]."""
    headlines = [h for h in (headlines or []) if h][:14]
    if not headlines:
        return {"issues": [], "analysis": None, "headlines": []}
    hs = "\n".join(f"- {h}" for h in headlines)
    prompt = (
        f"너는 증권사 애널리스트야. '{name}' 관련 최근 뉴스 헤드라인이야:\n{hs}\n\n"
        "이 헤드라인들을 근거로 최근 이 기업을 둘러싼 핵심 이슈를 정리하고 분석해줘. "
        "회사와 직접 관련 없는 일반 시장 뉴스는 제외해. 아래 JSON으로만 답해:\n"
        "{\n"
        '  "issues": [ {"title":"이슈 제목(구체적으로)", "detail":"무슨 내용이고 왜 중요한지 2~3문장", "tone":"긍정|부정|중립"} ],\n'
        '  "analysis": "이 이슈들을 종합하면 현재 이 기업의 상황과 시장 투자심리를 어떻게 볼 수 있는지 3~5문장(추정 전제)"\n'
        "}\n"
        "규칙: 헤드라인에 없는 사실을 지어내지 마. 이슈는 2~5개. 존댓말. 매수·매도 권유 금지. 반드시 유효한 JSON.")
    rep = _gemini_json(prompt, max_tokens=3072, temp=0.4, tries=3)
    if isinstance(rep, dict):
        rep["headlines"] = headlines
        return rep
    return {"issues": [], "analysis": None, "headlines": headlines}


# ----------------------------- 2) 리포트 교차분석 -----------------------------
def extract_pdf_text(raw, max_chars=18000):
    """PDF 바이트 → 텍스트. 실패/빈약하면 빈 문자열."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        out = []
        for pg in reader.pages:
            try:
                out.append(pg.extract_text() or "")
            except Exception:
                continue
            if sum(len(x) for x in out) > max_chars:
                break
        return "\n".join(out).strip()[:max_chars]
    except Exception:
        return ""


def report_analysis(files):
    """files: [(filename, bytes)] (최대 MAX_REPORTS). 교차분석 JSON 반환."""
    files = files[:MAX_REPORTS]
    docs, pdf_parts = [], []
    for i, (fname, raw) in enumerate(files):
        txt = extract_pdf_text(raw)
        if len(txt) >= 300:                       # 텍스트 추출 성공
            docs.append(f"### [리포트 {i+1}] 파일명: {fname}\n{txt}")
        else:                                     # 스캔본 등 → PDF 원본을 Gemini에 첨부
            pdf_parts.append(("application/pdf", raw))
            docs.append(f"### [리포트 {i+1}] 파일명: {fname}\n(본문 텍스트 추출 실패 — 첨부된 PDF 파일 {len(pdf_parts)}번을 직접 읽어줘)")
    if not docs:
        return {"error": "리포트에서 내용을 읽지 못했습니다."}
    n = len(files)
    body = "\n\n".join(docs)
    multi = n > 1
    cross = ("" if not multi else
             '  "consensus": [ "여러 리포트가 공통으로 말하는 핵심 (2~5개)" ],\n'
             '  "disagreement": [ {"topic":"엇갈리는 쟁점", "views":"리포트별로 어떻게 다르게 보는지"} ],\n')
    prompt = (
        f"너는 증권사 리서치를 교차검증하는 애널리스트야. 아래 증권사 리포트 {n}개를 읽고 분석해줘. "
        "각 리포트 본문 근거로만 판단하고, 없는 내용은 지어내지 마.\n\n"
        f"=== 리포트 원문 ===\n{body}\n\n"
        "아래 JSON 스키마로만 답해(마크다운 없이 순수 JSON):\n"
        "{\n"
        '  "reports": [ {"idx":1, "house":"증권사명(파일명·본문에서 추정, 모르면 리포트1)", '
        '"rating":"투자의견(매수/중립 등, 있으면)", "target":"목표주가(있으면)", '
        '"summary":"이 리포트 핵심 3~4문장", "points":["핵심 논거 2~4개"]} ],\n'
        + cross +
        '  "bull": [ "이 기업을 긍정적으로 보는 근거 (리포트 종합, 3~6개)" ],\n'
        '  "bear": [ "부정적으로 보거나 우려하는 근거 (3~6개)" ],\n'
        '  "verdict": "종합 코멘트 — 리포트들을 종합하면 시장은 이 기업을 어떻게 보는지 4~6문장"\n'
        "}\n"
        "규칙: 존댓말. bull/bear는 어느 리포트 근거인지 자연스럽게 녹여. "
        + ("리포트가 1개면 consensus·disagreement는 넣지 마. " if not multi else
           "consensus는 '공통된 의견', disagreement는 '서로 다르게 보는 지점'을 명확히 구분해. ") +
        "매수·매도 권유 금지. 반드시 유효한 JSON.")
    rep = _gemini_json(prompt, pdf_parts=pdf_parts or None, max_tokens=8192, temp=0.4, tries=3)
    if not rep:
        return {"error": "AI 분석에 실패했습니다. 리포트 용량이 크거나 형식이 특수할 수 있어요. 잠시 후 다시 시도해 주세요."}
    rep["count"] = n
    return rep
