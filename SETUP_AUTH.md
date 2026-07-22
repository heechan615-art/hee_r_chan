# 회원제(로그인) 셋업 가이드 — Supabase

회원가입·승인·강퇴 기능을 쓰려면 회원 정보를 저장할 **무료 데이터베이스(Supabase)** 가 필요해요.
(Render 무료 서버는 재배포 때 파일이 초기화돼서, 회원 정보는 외부 DB에 둬야 안 날아갑니다.)

아래 순서대로 5~10분이면 끝나요.

---

## 1단계: Supabase 프로젝트 만들기

1. https://supabase.com 접속 → **Start your project** → GitHub 계정으로 로그인 (무료)
2. **New project** 클릭
   - Name: `hee-valuation` (아무거나)
   - Database Password: **아무 비번 정하고 어딘가 적어두기** (나중에 안 써도 됨)
   - Region: **Northeast Asia (Seoul)** 선택 (한국이라 빠름)
3. **Create new project** → 1~2분 대기 (DB 생성 중)

---

## 2단계: 회원 테이블 만들기

1. 왼쪽 메뉴 **SQL Editor** → **New query**
2. 아래 SQL을 통째로 붙여넣고 **Run** (▶️):

```sql
create table members (
  id          bigint generated always as identity primary key,
  username    text unique not null,        -- 로그인 아이디
  pw_hash     text not null,               -- 비밀번호(암호화 저장)
  realname    text not null,               -- 본명 (필수)
  status      text not null default 'pending',  -- pending | approved | kicked
  is_admin    boolean not null default false,
  created_at  timestamptz not null default now(),  -- 가입일
  last_seen   timestamptz,                 -- 마지막 사용일
  approved_at timestamptz                  -- 승인일
);
```

3. "Success. No rows returned" 이 뜨면 완료.

---

## 3단계: 연결 정보 복사해서 알려주기

1. 왼쪽 메뉴 **Project Settings**(⚙️) → **API**
2. 아래 두 개를 복사해서 **저(클로드)에게 알려주세요**:
   - **Project URL** (예: `https://abcd1234.supabase.co`)
   - **service_role** 키 (secret) — `Project API keys` 섹션의 `service_role` 옆 `Reveal`  눌러서 복사

⚠️ **service_role 키는 비밀번호급이에요.** 채팅에 붙이기 꺼려지면, 알려주실 때 "곧 새 키로 교체하겠다"는 전제로 주세요. 붙인 뒤 Supabase에서 키를 재발급(rotate)하면 노출된 키는 무효화됩니다.

---

## 그다음은 제가 합니다

연결 정보를 주시면:
- 회원가입(본명 필수)·로그인 화면
- **승인 대기 → 관리자 승인 → 가입 완료** 흐름
- 관리자 페이지 (당신만): 회원명·가입일·마지막 사용일·사용 기간 + [승인] [강퇴] 버튼

을 붙이고, Render 환경변수에 연결 정보를 넣어 배포까지 이어갈게요.

**관리자(당신) 계정**: 가장 먼저 가입하는 아이디를 관리자로 지정할 거예요 (또는 원하는 아이디를 말씀하시면 그걸로).
