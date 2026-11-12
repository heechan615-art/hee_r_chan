-- 🧠 AI 종합 해석 영구 보관용 표 (Supabase → SQL Editor에 붙여 넣고 Run, 한 번만)
-- key: 종목 티커(소문자) 또는 'spend:YYYY-MM'(그 달 AI 비용 누적), data: 해석 결과 JSON
create table if not exists public.val_ai (
  key        text primary key,
  data       jsonb not null,
  updated_at timestamptz not null default now()
);
-- 외부(anon 키)에서는 읽기·쓰기 불가. 서버는 service_role 키라 그대로 사용 가능.
alter table public.val_ai enable row level security;
