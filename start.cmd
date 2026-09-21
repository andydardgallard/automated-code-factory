@echo off
chcp 65001 >nul
setlocal
rem Launcher Code Factory для Windows — создан prepare_factory.
rem   start.cmd          — интерактивно (в чате: /skill:code-factory)
rem   start.cmd --auto   — полностью автономно
cd /d "%~dp0"
rem Разделение моделей сабагентов (primary/secondary) включается здесь автоматически.
set KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1
where kimi >nul 2>&1
if errorlevel 1 (
    echo Команда kimi не найдена. Установите Kimi Code CLI и повторите запуск.
    pause
    exit /b 1
)
kimi %*
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo Фабрика завершилась с кодом %EXITCODE%.
    pause
)
exit /b %EXITCODE%
