@echo off
echo synthetic release Git warning 1>&2
if "%~3"=="nonzero" exit /b 37
echo synthetic release Git output
exit /b 0
