@echo off
chcp 65001 >nul
setlocal
rem ===========================================================================
rem prepare_factory.cmd — подготовка проекта к запуску Code Factory (Windows).
rem
rem Использование: prepare_factory.cmd <путь-к-проекту>
rem
rem Git Bash не нужен: файл запускается двойным кликом в Проводнике либо из
rem cmd/PowerShell. Всю работу делает prepare_factory.ps1 (PowerShell входит в
rem состав Windows), этот файл только передаёт ему аргументы и его код возврата.
rem ===========================================================================

rem --- 1. PowerShell ----------------------------------------------------------
where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo PowerShell не найден ^(powershell.exe^). Подготовка проекта выполняется
    echo скриптом prepare_factory.ps1 и требует PowerShell — он входит в состав
    echo Windows 10/11; при необходимости включите его в компонентах Windows.
    echo.
    echo Использование: prepare_factory.cmd ^<путь-к-проекту^>
    set "EXITCODE=1"
    goto :finish
)

rem --- 2. Скрипт развёртывания ------------------------------------------------
if not exist "%~dp0prepare_factory.ps1" (
    echo Не найден скрипт развёртывания prepare_factory.ps1 — он должен лежать
    echo рядом с этим файлом ^(%~dp0^). Проверьте, что репозиторий фабрики скопирован
    echo целиком.
    echo.
    echo Использование: prepare_factory.cmd ^<путь-к-проекту^>
    set "EXITCODE=1"
    goto :finish
)

rem --- 3. Запуск развёртывания (аргументы передаются без изменений) ------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_factory.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

:finish
rem --- Пауза только при двойном клике ----------------------------------------
rem При двойном клике окно консоли закрывается сразу после выхода, поэтому ждём
rem нажатия клавиши. Запуск из консоли, из другого скрипта и из автотеста не
rem блокируем. Два условия двойного клика:
rem   1) имя файла есть в командной строке cmd.exe. Ищем через findstr, а не
rem      через find: find может подменяться одноимённой утилитой из PATH
rem      (например, из Git Bash) и печатать ошибки;
rem   2) ввод идёт с консоли окна: timeout.exe отказывается работать при
rem      перенаправленном вводе (файл или канал) и возвращает код 1 — иначе пауза
rem      заблокировала бы скрипт или автотест. Путь к timeout.exe указан явно,
rem      чтобы не поймать одноимённую утилиту из PATH.
echo %cmdcmdline% | findstr /i /c:"%~nx0" >nul
if errorlevel 1 goto :no_pause
"%SystemRoot%\System32\timeout.exe" /t 0 /nobreak >nul 2>&1
if errorlevel 1 goto :no_pause
pause

:no_pause
exit /b %EXITCODE%
