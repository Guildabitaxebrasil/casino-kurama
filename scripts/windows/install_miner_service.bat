@echo off
rem Instala o minerador da KuramaChain no autostart do usuario (sem admin).
rem Ele roda miner_service.py com pythonw (sem janela) e reinicia sozinho.
setlocal
set "HERE=%~dp0"
set "SERVICE=%HERE%..\..\miner_service.py"
set "REGKEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "VALUE=KuramaMiner"

if not exist "%SERVICE%" (
  echo [ERRO] miner_service.py nao encontrado em %HERE%..\..
  exit /b 1
)
for %%I in ("%SERVICE%") do set "SERVICE=%%~fI"

rem pythonw.exe ao lado do Python usado agora (sem console).
for /f "delims=" %%P in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%P"
if not exist "%PYW%" for /f "delims=" %%P in ('where pythonw 2^>nul') do set "PYW=%%P"
if not exist "%PYW%" (
  echo [ERRO] pythonw.exe nao encontrado. Instale o Python no PATH e tente de novo.
  exit /b 1
)
for %%I in ("%PYW%") do set "PYW=%%~fI"

echo Instalando o minerador no autostart do usuario...
reg add "%REGKEY%" /v "%VALUE%" /t REG_SZ /d "\"%PYW%\" \"%SERVICE%\"" /f
if errorlevel 1 (
  echo.
  echo [ERRO] Falha ao gravar em %REGKEY%.
  exit /b 1
)

rem Inicia agora, sem esperar o proximo logon.
start "" "%PYW%" "%SERVICE%"

echo.
echo [OK] Minerador instalado. Ele inicia junto com o Windows e reinicia sozinho.
echo      Log:         data\miner_service.log
echo      Desinstalar: "%HERE%uninstall_miner_service.bat"
echo.
echo Lembrete: o minerador precisa do no rodando (python run.py --load).
