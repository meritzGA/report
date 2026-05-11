@echo off
REM 5월 데이터 갱신 스크립트 (Windows)
REM 사용법: D:\raw\prizebase_202605.xlsx 를 새 파일로 교체한 뒤 이 .bat 를 더블클릭
REM        → data\prizebase_202605.parquet 가 다시 생성되고, Streamlit이 자동 반영

cd /d %~dp0
echo [update] 5월 데이터 재처리 중...
python scripts\preprocess.py 202605
if errorlevel 1 (
    echo.
    echo [error] 처리 실패. python 환경과 prizebase_202605.xlsx 파일을 확인하세요.
    pause
    exit /b 1
)
echo.
echo [done] data\prizebase_202605.parquet 갱신 완료.
echo Streamlit 앱은 캐시 무효화로 자동 새로고침됩니다.
pause
