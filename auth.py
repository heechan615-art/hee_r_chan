"""
회원 인증 모듈 — Supabase(PostgREST) 백엔드
============================================
- 회원가입: 본명 필수, status='pending'(승인 대기)로 저장
- 로그인: status='approved'만 허용, last_seen 갱신
- 관리자: 회원 목록·승인·강퇴
- 비밀번호는 werkzeug로 해싱 저장(평문 저장 안 함)

환경변수:
  SUPABASE_URL         — 프로젝트 URL
  SUPABASE_SERVICE_KEY — service_role 키 (서버 전용, RLS 우회)
  ADMIN_USER           — 관리자 아이디(이 아이디로 가입하면 자동 승인+관리자)
연결 정보 없으면 auth_enabled()=False → 앱은 로그인 없이 동작(개발/미설정 시).
"""
import os
import re
import time
import requests
from werkzeug.security import generate_password_hash, check_password_hash

# scrypt(werkzeug 기본)은 LibreSSL로 빌드된 파이썬에서 hashlib.scrypt가 없어 실패한다.
# pbkdf2는 어디서나 되므로 명시적으로 고정 — 검증(check_password_hash)은 해시 접두어로 자동 판별.
_PW_METHOD = "pbkdf2:sha256"

_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
_ADMIN = os.environ.get("ADMIN_USER", "")


def auth_enabled():
    return bool(_URL and _KEY)


def _headers():
    return {"apikey": _KEY, "Authorization": f"Bearer {_KEY}",
            "Content-Type": "application/json"}


def _rest(method, path, **kw):
    r = requests.request(method, f"{_URL}/rest/v1/{path}", headers=_headers(), timeout=10, **kw)
    r.raise_for_status()
    return r.json() if r.text else []


def _find(username):
    rows = _rest("GET", f"members?username=eq.{requests.utils.quote(username)}&select=*")
    return rows[0] if rows else None


def register(username, password, realname):
    """회원가입. 반환 (ok, message)."""
    username = (username or "").strip()
    realname = (realname or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
        return False, "아이디는 영문·숫자·_ 3~20자여야 합니다."
    if len(password or "") < 6:
        return False, "비밀번호는 6자 이상이어야 합니다."
    if len(realname) < 2:
        return False, "본명을 정확히 입력해 주세요."
    if _find(username):
        return False, "이미 사용 중인 아이디입니다."
    is_admin = bool(_ADMIN) and username == _ADMIN
    row = {"username": username, "pw_hash": generate_password_hash(password, method=_PW_METHOD),
           "realname": realname, "status": "approved" if is_admin else "pending",
           "is_admin": is_admin}
    if is_admin:
        row["approved_at"] = "now()"
    try:
        _rest("POST", "members", json=row)
    except Exception as e:
        return False, f"가입 처리 실패: {repr(e)[:80]}"
    if is_admin:
        return True, "관리자 계정으로 가입 완료. 바로 로그인하세요."
    return True, "가입 신청 완료. 관리자 승인 후 이용할 수 있습니다."


def login(username, password):
    """로그인. 반환 (ok, message, user_dict|None)."""
    u = _find((username or "").strip())
    if not u or not check_password_hash(u["pw_hash"], password or ""):
        return False, "아이디 또는 비밀번호가 올바르지 않습니다.", None
    if u["status"] == "pending":
        return False, "아직 관리자 승인 대기 중입니다.", None
    if u["status"] == "kicked":
        return False, "이용이 정지된 계정입니다.", None
    # 마지막 사용일 갱신
    try:
        _rest("PATCH", f"members?id=eq.{u['id']}",
              json={"last_seen": time.strftime("%Y-%m-%dT%H:%M:%S")})
    except Exception:
        pass
    return True, "로그인 성공", {"id": u["id"], "username": u["username"],
                              "realname": u["realname"], "is_admin": u["is_admin"]}


def touch(uid):
    """활동 시각 갱신 (세션 유지 중 주기적)."""
    try:
        _rest("PATCH", f"members?id=eq.{uid}",
              json={"last_seen": time.strftime("%Y-%m-%dT%H:%M:%S")})
    except Exception:
        pass


# ----------------------------- 관리자 -----------------------------
def list_members():
    """전체 회원 목록 (관리자용). 가입일 최신순."""
    rows = _rest("GET", "members?select=id,username,realname,status,is_admin,"
                        "created_at,last_seen,approved_at&order=created_at.desc")
    return rows


def approve(uid):
    _rest("PATCH", f"members?id=eq.{uid}",
          json={"status": "approved", "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return True


def kick(uid):
    """강퇴 — 삭제 대신 status='kicked' (기록 보존)."""
    _rest("PATCH", f"members?id=eq.{uid}", json={"status": "kicked"})
    return True


def delete_member(uid):
    """완전 삭제."""
    _rest("DELETE", f"members?id=eq.{uid}")
    return True
