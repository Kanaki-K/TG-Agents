@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  Запуск аналитика канала (@AnalystAG_bot)
echo  Не закрывай это окно, пока пользуешься ботом.
echo ============================================
echo.
".venv\Scripts\python.exe" run_analyst.py
echo.
echo Бот остановлен.
pause
