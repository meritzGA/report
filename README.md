# 대리점 진도 대시보드

대리점별 (영업가족명 / 대리점지사명) **4월 동영업일수 누계 vs 5월 누계** 진도(G/R), 매출 Gap, 가동인원을 실시간으로 보여주는 Streamlit 대시보드.

- 본부(GA1본부 ~ 호남GA본부 등 8개) / 지점(117개) 필터로 드릴다운
- 5월 parquet 파일이 갱신되면 앱이 캐시를 자동 무효화해 즉시 반영
- 외부에서도 항상 같은 화면을 볼 수 있게 Streamlit Cloud 배포 가이드 포함

---

## 폴더 구조

```
D:\raw\
├─ prizebase_202604.xlsx        # 4월 원본 (고정 — 깃에 안 올림)
├─ prizebase_202605.xlsx        # 5월 원본 (수시 교체 — 깃에 안 올림)
└─ ga_dashboard\
   ├─ app.py                    # Streamlit 메인 앱
   ├─ data_logic.py             # 비즈니스 로직 (집계 / 동영업일 / G·R)
   ├─ scripts\
   │  └─ preprocess.py          # xlsx → parquet 변환
   ├─ data\
   │  ├─ prizebase_202604.parquet   # 4월 슬림본 (~2.4 MB)
   │  └─ prizebase_202605.parquet   # 5월 슬림본 (~0.3 MB)
   ├─ update_may.bat            # 5월 갱신 더블클릭용 배치
   ├─ requirements.txt
   ├─ .gitignore
   └─ README.md  ← 이 파일
```

raw 엑셀은 약 80 MB / 5 MB 인 데 반해 parquet 슬림본은 22컬럼만 추려 **2.4 MB / 0.3 MB**로 압축되어 깃·Streamlit Cloud에 그대로 올려도 충분합니다.

---

## 1) 로컬 실행 (먼저 동작 확인)

### 1-1. 가상환경 + 의존성

```powershell
cd D:\raw\ga_dashboard
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 1-2. (이미 완료됨) parquet 슬림본 생성

이미 `data\prizebase_202604.parquet` / `data\prizebase_202605.parquet` 가 들어 있습니다. 만약 다시 만들려면:

```powershell
python scripts\preprocess.py
```

> raw xlsx는 기본적으로 `D:\raw\` 에서 찾습니다(`scripts\preprocess.py` 참조). 다른 경로면 `python scripts\preprocess.py --raw "경로"` 로 지정.

### 1-3. 실행

```powershell
streamlit run app.py
```

브라우저가 자동으로 열리며 [http://localhost:8501](http://localhost:8501) 에서 대시보드를 볼 수 있습니다.

---

## 2) 5월 데이터 자동 갱신

운영 흐름은 매일 다음과 같습니다.

1. 회사 시스템에서 최신 `prizebase_202605.xlsx` 파일을 받아 **`D:\raw\` 에 덮어쓰기**.
2. `D:\raw\ga_dashboard\update_may.bat` **더블클릭** (또는 터미널에서 `python scripts\preprocess.py 202605`).
3. `data\prizebase_202605.parquet` 가 갱신됨.
4. 열려있는 Streamlit 앱은 **새로고침(F5) 한 번만 누르면** 자동 반영(파일 mtime 캐시키 사용).
5. (외부 배포까지 동기화 하려면) git push:
   ```powershell
   git add data\prizebase_202605.parquet
   git commit -m "update: 5월 데이터 갱신 (YYYY-MM-DD)"
   git push
   ```
   → Streamlit Cloud가 자동 재배포합니다 (보통 1~2분).

> 4월 parquet은 한 번 만들어진 뒤로는 건드리지 않습니다(고정 baseline).

---

## 3) GitHub + Streamlit Cloud 배포

### 3-1. GitHub 저장소 생성

```powershell
cd D:\raw\ga_dashboard
git init
git add .
git commit -m "initial: 대리점 진도 대시보드"
# GitHub에서 새 private repo 생성 후
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

`.gitignore` 가 raw xlsx를 자동 제외하므로 **`prizebase_*.xlsx`는 푸시되지 않습니다.** parquet 슬림본만 올라갑니다.

> 만약 raw xlsx도 같은 폴더 안에 있다면 `D:\raw\ga_dashboard\` **밖**에 두는 것이 안전합니다(현재 구조처럼 `D:\raw\` 직속).

### 3-2. Streamlit Cloud 연결

1. [https://share.streamlit.io](https://share.streamlit.io) 접속 → GitHub로 로그인
2. **New app** → 저장소 / 브랜치 / `app.py` 지정 → Deploy
3. 1~2분 후 `https://<app-name>.streamlit.app` 주소 발급
4. 외부에서 언제든 같은 URL로 같은 데이터 확인 가능

### 3-3. 접근 제한 (선택)

- 사내 인원만 보여주려면 Streamlit Cloud 설정에서 **Viewer access**를 "Only specific users"로 설정하고 이메일 화이트리스트 등록.
- 또는 `st.secrets` + 비밀번호 입력 방식의 게이트를 추가하는 것도 한 줄 코드로 가능합니다(원하시면 알려주세요).

---

## 4) 핵심 비즈니스 로직 (요약)

- **영업일** = 해당 월 데이터에 실제로 입력일자가 존재하는 모든 일자(주말/공휴일 포함, 데이터-드리븐)
- **N영업일째** = 5월의 첫 영업일부터 사용자가 선택한 기준일까지의 unique 입력일자 개수
- **5월 누계 매출** = 입력일자 ≤ 기준일 인 5월 데이터의 `월납환산보험료` 합
- **4월 동영업일수 누계** = 4월의 첫 N개 입력일자에 해당하는 `월납환산보험료` 합
- **G/R(%)** = 5월 누계 / 4월 동기간 × 100
- **가동인원** = `상품구분 == '인보험'` & `월납환산보험료 > 0` 인 **설계사(`대리점설계사조직코드`) unique count**

집계 단위는 사이드바에서 다음 네 가지 중 선택:
- 영업가족명 (예: `(주)에이플러스에셋어드바이저`, `인카금융서비스(주)` 등 175개)
- 대리점지사명 (예: `(주)에이플러스에셋어드바이저(강남지사)` 등 3,799개)
- 본부 (지역단조직명, 9개)
- 지점 (지점조직명, 118개)

---

## 5) 화면 구성

- **사이드바**: 기준일 슬라이더, 본부 multiselect, 지점 multiselect(본부 선택에 따라 옵션 동적 갱신), 대리점 단위 토글, 인보험 only 체크박스.
- **상단 KPI**: 4월 동기간 매출 / 5월 누계 / G/R / 가동인원 / 가동인원 G/R.
- **탭1 대리점별**: 검색창 + 매출·건수·가동인원 4월/5월/Gap/G·R% (G/R 색상 그라데이션). CSV 다운로드 가능.
- **탭2 본부별 / 탭3 지점별**: 동일 컬럼 구조의 비교표.
- **탭4 일별 추이**: 영업일 N일째 누계 매출 라인차트(4월 vs 5월) + 데이터 테이블.

---

## 6) 트러블슈팅

| 증상 | 해결 |
| --- | --- |
| `FileNotFoundError: data/prizebase_202604.parquet` | `python scripts/preprocess.py` 먼저 실행 |
| 5월 갱신 후에도 화면이 그대로 | 브라우저에서 F5 / Ctrl+F5. Streamlit Cloud는 1~2분 후 자동 반영 |
| `'.style' accessor requires jinja2` | `pip install --upgrade "jinja2>=3.1.2"` |
| raw xlsx 경로가 다른 PC라 깨짐 | `python scripts/preprocess.py --raw "C:/your/path"` |

---

## 7) 다음 단계 아이디어

- 청약일자 / 입력일자 토글 (당일자 vs 마감자 기준)
- 자기계약 / 취급자 계약 제외 토글
- 추세 분석 (3·4·5월 비교, 작년 동월 비교 — 5월 마감 후)
- Slack / 이메일로 매일 아침 진도 요약 자동 전송
