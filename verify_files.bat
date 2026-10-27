@echo off
title Verificar Arquivos do Dashboard
color 0a

echo ========================================
echo  Cypress LangGraph Validator
echo   Arquivos Necessários
echo ========================================
echo.

cd /d "%~dp0"

echo Verificando arquivos...
echo.

REM Verificar Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ Python NÃO encontrado!
    echo   Instale em: https://www.python.org/downloads/
) else (
    echo ✅ Python encontrado!
    where python | findstr /i "python.exe"
)

echo.

REM Verificar Flask
python -c "import flask; print('✅ Flask instalado!')" 2>nul || (
    echo ❌ Flask NÃO instalado!
    echo   Execute: pip install flask
)

echo.

REM Verificar arquivos do projeto
if exist web_ui\app.py (
    echo ✅ web_ui\app.py encontrado
) else (
    echo ❌ web_ui\app.py não encontrado!
)

if exist "web_ui\templates\index.html" (
    echo ✅ web_ui\templates\index.html encontrado
) else (
    echo ❌ web_ui\templates\index.html não encontrado!
)

if exist logs (
    echo ✅ Pasta /logs existe
) else (
    echo ℹ️  Pasta /logs não criada ainda
)

echo.
echo ========================================
REM Se tudo ok, sugerir execução do servidor
where python >nul 2>nul
if %errorlevel% equ 0 (
    if exist "web_ui\app.py" (
        set ALL_OK=1
        echo.
        echo 🚀 Para iniciar o servidor:
        echo    - Execute: start_server.bat
        echo    - Ou digite na pasta do projeto
        echo.
    ) else (
        echo ⚠️  Arquivo app.py não encontrado!
    )
)

pause