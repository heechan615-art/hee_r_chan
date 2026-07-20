# 배포 가이드 — Render.com (무료)

이 앱을 인터넷에 올려서 남들이 URL로 접속하게 하는 방법입니다.
프론트(HTML)만으로는 데이터 수집이 안 되므로, **Flask 서버 통째로** 클라우드에 올립니다.

---

## 준비된 것 (이미 완료)

- `requirements.txt` — 필요한 파이썬 패키지 목록
- `Procfile` / `render.yaml` — 서버 실행 설정 (gunicorn)
- `.gitignore` — API 키 파일(.env, gemini_key.txt)을 깃허브에서 제외

---

## 1단계: GitHub에 코드 올리기

⚠️ **API 키는 절대 올라가면 안 됩니다** (.gitignore가 막아주지만 재확인).

```bash
cd ~/stock-valuation
git init
git add .
git status          # .env, gemini_key.txt 가 목록에 없는지 반드시 확인!
git commit -m "가치평가 웹앱"
```

그다음 github.com 에서 새 저장소(New repository)를 만들고, 안내에 따라:

```bash
git remote add origin https://github.com/<본인아이디>/stock-valuation.git
git branch -M main
git push -u origin main
```

---

## 2단계: Render에 배포

1. https://render.com 가입 (GitHub 계정으로 로그인하면 편함)
2. **New +** → **Web Service**
3. 방금 만든 GitHub 저장소 선택 → **Connect**
4. 설정값 (render.yaml이 있으면 대부분 자동으로 채워짐):
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`
   - **Instance Type**: Free
5. **Environment** 탭에서 API 키를 환경변수로 추가 (코드엔 넣지 않음):

   | Key | Value |
   |-----|-------|
   | `GEMINI_API_KEY` | (본인 Gemini 키) |
   | `FRED_API_KEY` | 3a622090884b4a283f574dfdd9d31dfe |
   | `ECOS_API_KEY` | FTFZ657MG2Y0LUOBUZFN |
   | `FINNHUB_API_KEY` | (본인 Finnhub 키) |

6. **Create Web Service** → 몇 분 뒤 `https://stock-valuation-xxxx.onrender.com` 주소가 생성됩니다.

---

## 알아둘 점 (무료 티어의 한계)

1. **첫 접속이 느림 (콜드 스타트)**: 15분간 아무도 안 쓰면 서버가 잠들고, 다음 접속 시 깨어나는 데 ~30초 걸립니다. (유료 $7/월로 항상 켜둘 수 있음)

2. **데이터 소스 리스크**: yfinance(야후)·네이버·인베스팅은 클라우드 IP를 가끔 차단합니다. 로컬(집)에선 잘 되던 게 서버에선 간헐적으로 실패할 수 있어요. 실패 시 해당 기능만 빠지고 앱은 계속 동작하도록 이미 방어돼 있습니다.

3. **키 보안**: `.env`와 `gemini_key.txt`는 절대 GitHub에 올리지 마세요. 서버에선 Render 환경변수로만 관리합니다.

---

## 로컬에서 계속 쓰기

배포와 별개로, 집에서는 지금처럼 씁니다:
- 데스크탑의 **"가치평가앱 실행.command"** 더블클릭 (기존과 동일)
- 또는 터미널: `./venv/bin/python app.py`
