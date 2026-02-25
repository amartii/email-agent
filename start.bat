@echo off
echo Activando entorno virtual...
call venv\Scripts\activate

echo Iniciando Email Agent en http://localhost:5000
python run.py
pause
