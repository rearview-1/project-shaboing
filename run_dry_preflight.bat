@echo off
cd /d "%~dp0"
call scripts\windows\run_dry_preflight.bat %*
