@echo off
setlocal
title Automation Code Validator Server

echo ==============================================
echo   Automation Code Validator Server
echo ==============================================

:: Ir para a raiz do projeto (um nível acima da pasta 'server')
cd /d "%~dp0.."

:: Verificar se o Python esta instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python nao encontrado!
    echo Certifique-se de que o Python esta instalado e no PATH do sistema.
    pause
    exit /b 1
)

:: Verificar se o Flask esta instalado
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Flask nao instalado!
    echo   Execute: pip install flask
    pause
    exit /b 1
)

:: Verificar se a porta 5000 esta livre
netstat -ano | findstr /r ":5000 " | findstr /i "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [ERRO] A porta 5000 ja esta em uso.
    echo   Encerre o processo antigo ou feche outra aba do dashboard.
    pause
    exit /b 1
)

echo Iniciando servidor Flask em http://127.0.0.1:5000 ...
echo.

:: Executar a aplicacao em uma nova janela
:: O uso do "start" permite que o script continue para abrir o navegador
start "Flask_Server_Log" python web_ui\app.py

:: Aguardar o boot (max. 15s) para abrir o navegador
set /a WAIT=0
:wait_loop
set /a WAIT+=1
if %WAIT% GTR 15 goto boot_timeout
timeout /t 1 /nobreak >nul
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000', timeout=1)" >nul 2>&1
if %errorlevel% equ 0 goto browser_open
goto wait_loop

:boot_timeout
echo [AVISO] Servidor nao respondeu em 15s. Tente abrir http://127.0.0.1:5000 manualmente.
pause
exit /b 1

:browser_open
echo Servidor no ar! Abrindo navegador...
start "" "http://127.0.0.1:5000"
echo.
echo Servidor iniciado com sucesso.
echo Pressione qualquer tecla para fechar esta janela de aviso.
pause
