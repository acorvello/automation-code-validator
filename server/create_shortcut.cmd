@echo off
setlocal
title Create Shortcut - Automation Code Validator

REM ============================================================
REM  Cria atalhos (Menu Iniciar e Desktop) para o servidor.
REM  O atalho aponta para server\start_server.cmd, com a raiz
REM  do projeto como working directory.
REM ============================================================

echo ========================================
echo   Criando Atalhos do Cypress Dashboard
echo ========================================
echo.

REM Raiz do projeto (o script fica em server\)
set "PROJECT_ROOT=%~dp0.."
set "TARGET=%PROJECT_ROOT%\server\start_server.cmd"
set "ICON=%PROJECT_ROOT%\dashboard.ico"
set "SHORTCUT_NAME=Automation Code Validator"

if not exist "%TARGET%" (
    echo [ERRO] start_server.cmd nao encontrado em: %TARGET%
    pause
    exit /b 1
)

echo Script alvo: %TARGET%
echo.

REM ---------- Atalho no Menu Iniciar ----------
set "START_MENU=%USERPROFILE%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
if exist "%START_MENU%" (
    echo Criando atalho no Menu Iniciar...
    powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%START_MENU%\%SHORTCUT_NAME%.lnk'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = '%PROJECT_ROOT%'; $s.Description = 'Automation Code Validator Server'; $s.IconLocation = '%ICON%,0'; $s.Save()"
    if %errorlevel% equ 0 (
        echo [OK] Atalho criado no Menu Iniciar
    ) else (
        echo [AVISO] Nao foi possivel criar o atalho no Menu Iniciar.
    )
) else (
    echo [AVISO] Pasta do Menu Iniciar nao encontrada.
)

REM ---------- Atalho no Desktop ----------
if exist "%USERPROFILE%\Desktop" (
    echo Criando atalho no Desktop...
    powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%USERPROFILE%\Desktop\%SHORTCUT_NAME%.lnk'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = '%PROJECT_ROOT%'; $s.Description = 'Automation Code Validator Server'; $s.IconLocation = '%ICON%,0'; $s.Save()"
    if %errorlevel% equ 0 (
        echo [OK] Atalho criado no Desktop
    ) else (
        echo [AVISO] Nao foi possivel criar o atalho no Desktop.
    )
) else (
    echo [AVISO] Desktop nao encontrado.
)

echo.
echo ========================================
echo  Resumo:
echo    Alvo:        %TARGET%
echo    Working dir: %PROJECT_ROOT%
echo    Icone:       %ICON%
echo ========================================

pause