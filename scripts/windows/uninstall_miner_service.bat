@echo off
rem Remove o minerador do autostart do usuario e encerra o processo.
setlocal
set "HERE=%~dp0"
set "REGKEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "VALUE=KuramaMiner"
set "PIDFILE=%HERE%..\..\data\miner_service.pid"

reg delete "%REGKEY%" /v "%VALUE%" /f >nul 2>&1
if errorlevel 1 (
  echo [AVISO] Nao havia minerador no autostart.
) else (
  echo [OK] Autostart removido.
)

if exist "%PIDFILE%" (
  for /f "usebackq delims=" %%P in ("%PIDFILE%") do taskkill /PID %%P /F >nul 2>&1
  del "%PIDFILE%" >nul 2>&1
  echo [OK] Minerador parado.
)

echo Pronto. O minerador nao inicia mais com o Windows.
