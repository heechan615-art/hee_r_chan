"""
yfinance 공통 세션 — curl_cffi 브라우저 지문 위장.
=================================================
야후파이낸스는 클라우드(Render 등) IP의 .info 호출을 자주 차단한다.
curl_cffi(impersonate="chrome") 세션을 yfinance에 주입하면 브라우저처럼
보여 차단을 우회한다. 세션 생성 실패 시 기본 yfinance로 폴백.
"""
import yfinance as yf

_SESSION = None
_TRIED = False


def _session():
    global _SESSION, _TRIED
    if _TRIED:
        return _SESSION
    _TRIED = True
    try:
        from curl_cffi import requests as creq
        _SESSION = creq.Session(impersonate="chrome")
    except Exception:
        _SESSION = None
    return _SESSION


def ticker(tk):
    """세션 주입된 yf.Ticker. 세션 없으면 기본."""
    s = _session()
    try:
        return yf.Ticker(tk, session=s) if s is not None else yf.Ticker(tk)
    except Exception:
        return yf.Ticker(tk)
