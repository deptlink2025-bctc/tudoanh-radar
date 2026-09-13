@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Chay job sau phien tren may nay (khong gui thong bao). Ket qua: site\data\latest.json
venv\Scripts\python -m job.run_daily --force --no-push
pause
