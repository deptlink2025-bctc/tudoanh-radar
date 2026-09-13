@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === TuDoanh Radar: cai dat lan dau ===
if not exist venv (
  python -m venv venv || (echo Khong tim thay Python 3.12. Cai tu python.org roi chay lai. & pause & exit /b 1)
)
call venv\Scripts\activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt || (echo Cai thu vien loi & pause & exit /b 1)
if not exist .env (
  copy .env.example .env >nul
  echo Da tao .env — mo file nay, dien ANTHROPIC_API_KEY roi luu (UTF-8).
)
python -m pytest tests -q
echo.
echo Xong. Chay start-review.bat de mo man hinh duyet BCTC.
pause
