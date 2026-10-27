@echo off
setlocal enabledelayedexpansion

REM Criar atalho para o Cypress LangGraph Validator Server
cd /d "%~dp0"

SET SCRIPT_PATH=%CD%\start_server.bat
SET SHORTCUT_NAME="Cypress Dashboard"
SET TARGET_FILE=script: %SCRIPT_PATH%

echo ========================================
echo   Criando atalhos do Cypress Dashboard
echo ========================================
echo.

REM Criar arquivo INI para o Windows 10/11
set WIN_USER_DIR=%USERPROFILE%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs
if exist "%WIN_USER_DIR%" (
    echo Criando atalho no menu Iniciar...
    
    REM Adicionar ao menu Programas
    echo [%WIN_USER_DIR%\Cypress Dashboard.lnk]=%SCRIPT_PATH%
)

echo.
REM Criar comando para executar o script via rundll32
powershell -Command "$shell = New-Object -ComObject WScript.Shell; $shortcut = $shell.CreateShortcut('%TEMP%\CypressDashboard.lnk'); $shortcut.TargetPath='%SCRIPT_PATH%'; $shortcut.WorkingDirectory='%CD%'; $shortcut.Description='Cypress LangGraph Validator Server'; $shortcut.Save()"

if ($LASTEXITCODE) -eq 0 (
    echo ✅ Atalho criado em %TEMP%\CypressDashboard.lnk
    echo.
    echo Para abrir, arraste este arquivo para o Desktop ou execute diretamente.
) else (
    echo ⚠️  Não foi possível criar atalho automaticamente.
    echo Use start_server.bat manualmente.
)

echo.
echo ========================================
REM Abre o script de qualquer caso
start "%SCRIPT_PATH%"

pause