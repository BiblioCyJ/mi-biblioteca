@echo off
echo =========================================
echo  Actualizando biblioteca en la nube...
echo =========================================
cd /d "%~dp0"
git add .
git commit -m "Actualizacion de base de datos"
git push origin main
echo.
echo =========================================
echo  ¡Actualizacion completada con exito!
echo =========================================
pause