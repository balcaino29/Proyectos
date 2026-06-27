@echo off
echo ================================
echo  OT6021 - Control Documental
echo ================================
echo.

cd /d "%~dp0"

echo Verificando dependencias...
pip install -r requirements.txt -q

echo.
echo Intentando puerto 8080...
python -m uvicorn main:app --host 127.0.0.1 --port 8080 --reload
if %ERRORLEVEL% NEQ 0 (
  echo Puerto 8080 ocupado, intentando 5000...
  python -m uvicorn main:app --host 127.0.0.1 --port 5000 --reload
)
if %ERRORLEVEL% NEQ 0 (
  echo Puerto 5000 ocupado, intentando 3000...
  python -m uvicorn main:app --host 127.0.0.1 --port 3000 --reload
)
pause
