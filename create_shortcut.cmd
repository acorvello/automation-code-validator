@echo off
setlocal enabledelayedexpansion

call "%~dp0server\create_shortcut.cmd"
exit /b %errorlevel%