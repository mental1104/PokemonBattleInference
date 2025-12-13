@echo off
pushd "%~dp0" >nul
py -3 dev %*
set EXITCODE=%ERRORLEVEL%
popd >nul
exit /b %EXITCODE%
