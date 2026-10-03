@echo off
cd /d "%~dp0"

:: Arranca los dos servidores minimizados en la barra de tareas
start /min "Servidor Administrador" python -m streamlit run app.py --server.port 8501 --server.headless true
start /min "Servidor Consulta Movil" python -m streamlit run consulta.py --server.port 8510 --server.headless true

:: Espera 2 segundos a que inicien los motores y abre la web de administración
timeout /t 2 >nul
start http://localhost:8501