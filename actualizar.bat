@echo off
echo Actualizando la biblioteca en GitHub...
git add .
git commit -m "Actualizacion automatica de libros"
git push origin main
echo ¡Proceso completado con exito!
pause