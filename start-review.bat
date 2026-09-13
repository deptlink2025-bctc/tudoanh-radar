@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (echo Chua cai. Chay install.bat truoc. & pause & exit /b 1)
echo Mo man hinh duyet BCTC tai http://localhost:8100  (dong cua so nay de tat)
start "" http://localhost:8100
venv\Scripts\python -m uvicorn ingest.review_server:app --port 8100
