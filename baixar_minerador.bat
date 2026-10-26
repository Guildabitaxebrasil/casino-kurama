@echo off
setlocal EnableExtensions
chcp 65001 >nul
title KuramaChain - Minerador

REM ================================================================
REM  Baixa o minerador da KuramaChain do GitHub e ja comeca a minerar.
REM  Nao precisa clonar o projeto: baixa so o miner.py para
REM  %USERPROFILE%\KuramaMiner e cria o ambiente Python dele.
REM
REM  Uso (duplo clique tambem funciona):
REM    baixar_minerador.bat
REM    baixar_minerador.bat http://meu-no:5000
REM    baixar_minerador.bat http://meu-no:5000 15ZK...
REM ================================================================

set "RAW_URL=https://raw.githubusercontent.com/Guildabitaxebrasil/casino-kurama/main/miner.py"
set "NODE_URL=%~1"
set "MINER_ADDRESS=%~2"
if "%NODE_URL%"=="" set "NODE_URL=http://127.0.0.1:5000"

set "INSTALL_DIR=%USERPROFILE%\KuramaMiner"
set "MINER_FILE=%INSTALL_DIR%\miner.py"
set "VENV_PY=%INSTALL_DIR%\.venv\Scripts\python.exe"

echo.
echo  KuramaChain - baixar minerador
echo  ------------------------------

REM --- Python 3.10+ (python ou py -3) ------------------------------
set "PY="
python -c "import sys;sys.exit(sys.version_info[0]*100+sys.version_info[1] < 310)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :py_ok
py -3 -c "import sys;sys.exit(sys.version_info[0]*100+sys.version_info[1] < 310)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
:py_ok
if not defined PY goto :erro_python

REM --- pasta de instalacao -----------------------------------------
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%" >nul 2>nul
if not exist "%INSTALL_DIR%" goto :erro_pasta

REM --- 1/3 download ------------------------------------------------
echo [1/3] Baixando o minerador...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Uri '%RAW_URL%' -OutFile '%MINER_FILE%'; exit 0 } catch { Write-Host ('[ERRO] ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 goto :erro_download
findstr /C:"KuramaChain" "%MINER_FILE%" >nul 2>nul
if errorlevel 1 goto :erro_download

REM --- 2/3 ambiente Python -----------------------------------------
if exist "%VENV_PY%" goto :venv_ok
echo [2/3] Criando o ambiente Python (so na primeira vez)...
%PY% -m venv "%INSTALL_DIR%\.venv"
if errorlevel 1 goto :erro_venv
:venv_ok

REM --- 3/3 dependencia ---------------------------------------------
echo [3/3] Verificando dependencias...
"%VENV_PY%" -c "import requests" >nul 2>nul
if not errorlevel 1 goto :deps_ok
"%VENV_PY%" -m pip install --quiet --disable-pip-version-check requests
if errorlevel 1 goto :erro_pip
:deps_ok

REM --- minerar -----------------------------------------------------
set "EXTRA="
if not "%MINER_ADDRESS%"=="" set "EXTRA=--address %MINER_ADDRESS%"

echo.
echo   No:        %NODE_URL%
echo   Minerador: %MINER_FILE%
echo.
"%VENV_PY%" "%MINER_FILE%" --url "%NODE_URL%" %EXTRA%

echo.
if errorlevel 2 echo  [AVISO] O minerador nao conseguiu falar com o no em %NODE_URL%.
echo  Minerador encerrado. Para minerar de novo, rode este script outra vez.
pause
exit /b 0

:erro_python
echo.
echo  [ERRO] Python 3.10 ou superior nao encontrado.
echo         Instale em https://www.python.org/downloads/ marcando a opcao
echo         "Add python.exe to PATH" e rode este script de novo.
goto :fim_com_erro

:erro_pasta
echo.
echo  [ERRO] Nao foi possivel criar a pasta %INSTALL_DIR%.
goto :fim_com_erro

:erro_download
echo.
echo  [ERRO] Falha ao baixar o minerador de:
echo         %RAW_URL%
echo         Confira a conexao com a internet e tente de novo.
goto :fim_com_erro

:erro_venv
echo.
echo  [ERRO] Falha ao criar o ambiente Python em %INSTALL_DIR%\.venv
goto :fim_com_erro

:erro_pip
echo.
echo  [ERRO] Falha ao instalar a dependencia "requests".
echo         Rode manualmente: "%VENV_PY%" -m pip install requests
goto :fim_com_erro

:fim_com_erro
pause
exit /b 1
