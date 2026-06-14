@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  Установка библиотек для ботов (один раз)
echo ============================================
echo.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo ============================================
echo  Готово. Можно закрывать это окно.
echo  Дальше запусти start_analyst.bat
echo ============================================
pause
