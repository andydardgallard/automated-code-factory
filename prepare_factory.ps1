param(
    [Parameter(Position = 0)]
    [string]$ProjectDir
)

# =============================================================================
# prepare_factory.ps1 — подготовка проекта к запуску Code Factory одним действием
# (Windows-версия prepare_factory.sh: тот же результат, без Git Bash).
#
# Назначение: скопировать фабрику (.agents/) в проект, завести память ИМЕННО этого
# проекта (`memory/` — долгосрочная память целевого проекта: журнал
# `memory/change-log.md` + сводка `memory/summary.md`), настроить .gitignore, при
# необходимости инициализировать git-репозиторий, создать launcher'ы `start.cmd`
# (Windows) и `start.sh` (Git Bash/Linux) и проверить готовность.
#
# Где живёт память и как называется проект:
#   * `memory/` создаётся В КОРНЕ РАЗВЁРТЫВАНИЯ — в том каталоге, который передан этому
#     скрипту; базовое имя проекта при развёртывании = basename этого каталога.
#   * Если `repo_path` задачи указывает на ПОДКАТАЛОГ корня развёртывания, главный агент
#     заводит память явно, назвав проект:
#       memory_project.py init --repo <корень развёртывания> --project <basename repo_path>
# Существующая память проекта НИКОГДА не перезаписывается: недостающие файлы
# создаются, а уже имеющиеся (история прогонов проекта) остаются нетронутыми. Если
# память объявлена за ДРУГОЙ проект или смешивает проекты — только предупреждение
# (скрипт всё равно завершается с exit 0).
#
# Python нужен только для скриптов фабрики (память проекта) и может отсутствовать —
# развёртывание в этом случае продолжается и завершается успешно.
#
# Использование:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File prepare_factory.ps1 <путь-к-проекту>
#
# Пример:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File prepare_factory.ps1 C:\work\my-project
#
# После подготовки достаточно одного действия:
#   cd <путь-к-проекту>
#   start.cmd            # интерактивно (в чате: /skill:code-factory)
#   start.cmd --auto     # полностью автономно
#
# Скрипт НЕ коммитит ничего. Все шаги безопасны и идемпотентны.
# =============================================================================

# Русский текст должен читаться и при перенаправлении вывода (пайп/файл).
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

# Дочерние процессы python тоже должны печатать UTF-8: в локальной кодировке (cp1251) имя
# проекта с кириллицей читается как мусор, а символы вне cp1251 (например CJK) вообще роняют
# печать (UnicodeEncodeError) — и память выглядела бы несозданной, хотя файлы созданы.
$env:PYTHONUTF8 = '1'

# --- Пути --------------------------------------------------------------------
$ScriptDir  = if ($PSScriptRoot) { (Resolve-Path -LiteralPath $PSScriptRoot).Path } else { (Get-Location).Path }
$FactorySrc = Join-Path $ScriptDir '.agents'          # готовая фабрика (этот репозиторий)
$EncNoBom   = New-Object System.Text.UTF8Encoding($false)

# Жёсткая ошибка — то же, что `set -e` в bash-версии: если фабрику скопировать не удалось или
# файл запуска не записался, развёртывание неполное и завершается кодом 1 (не «Готово»).
# Ожидаемые деградации (нет python, память не проверена) жёсткой ошибкой НЕ являются.
$HardError  = $false

function Info { param([string]$Message) Write-Host $Message }
function Warn { param([string]$Message) Write-Host $Message }
function Err  { param([string]$Message) [Console]::Error.WriteLine($Message) }

# --- Вспомогательные функции --------------------------------------------------
# Запуск внешней команды с захватом stdout+stderr и кода возврата.
function Invoke-Capture {
    param([string[]]$Command)
    $global:LASTEXITCODE = 1
    $out = @()
    $rc  = 1
    try {
        $exe  = $Command[0]
        $rest = @($Command | Select-Object -Skip 1)
        $out  = @(& $exe @rest 2>&1)
        $rc   = $LASTEXITCODE
    } catch {
        $out = @($_.Exception.Message)
        $rc  = 1
    }
    return New-Object psobject -Property @{ Output = $out; ExitCode = $rc }
}

# Копирование дерева фабрики: robocopy (сохраняет всё, включая скрытые элементы),
# при недоступности/сбое robocopy — рекурсивный Copy-Item.
function Copy-FactoryTree {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
        $null = New-Item -ItemType Directory -Force -Path $Destination
    }
    $robocopy = Get-Command robocopy.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($robocopy) {
        & $robocopy.Source $Source $Destination /E /NFL /NDL /NJH /NJS /NP | Out-Null
        # 0-7 — успех (в т.ч. «файлы скопированы»), 8+ — реальная ошибка.
        if ($LASTEXITCODE -lt 8) { return }
    }
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

# Запись файла развёртывания. Сбой записи (например, нет прав на каталог) в PowerShell не
# роняет скрипт, поэтому ловим его сами и помечаем прогон жёсткой ошибкой: без файла запуска
# проект нельзя считать подготовленным. Возвращает $true, если файл записан.
function Write-FileStrict {
    param([string]$Path, [string]$Text, [System.Text.Encoding]$Encoding, [switch]$Append)
    try {
        if ($Append) { [System.IO.File]::AppendAllText($Path, $Text, $Encoding) }
        else         { [System.IO.File]::WriteAllText($Path, $Text, $Encoding) }
        return $true
    } catch {
        $script:HardError = $true
        Err "    Не удалось записать файл: $Path"
        return $false
    }
}

# --- Интерпретатор Python -----------------------------------------------------
# Нужен для скриптов фабрики (память проекта). Может быть не найден — это не ошибка.
# Порядок кандидатов: py -3, py, python, python3. Стаб `python3` из Microsoft Store
# (Windows) существует как файл, но не работает, поэтому каждый кандидат проверяется
# реальным запуском и берётся первый РАБОЧИЙ.
$PyExe    = $null
$PyPrefix = @()
$PyCandidates = @(
    (New-Object psobject -Property @{ Name = 'py';      Prefix = @('-3') }),
    (New-Object psobject -Property @{ Name = 'py';      Prefix = @()     }),
    (New-Object psobject -Property @{ Name = 'python';  Prefix = @()     }),
    (New-Object psobject -Property @{ Name = 'python3'; Prefix = @()     })
)
foreach ($cand in $PyCandidates) {
    $exe = Get-Command $cand.Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $exe) { continue }
    $global:LASTEXITCODE = 1
    try {
        $null = @(& $exe.Source @($cand.Prefix) '-c' 'pass' 2>&1)
        if ($LASTEXITCODE -eq 0) { $PyExe = $exe.Source; $PyPrefix = @($cand.Prefix); break }
    } catch { }
}

# --- Проверка аргумента -------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    Err "Укажите путь к проекту:  prepare_factory.ps1 <путь-к-проекту>"
    exit 1
}
if (-not (Test-Path -LiteralPath $ProjectDir -PathType Container)) {
    Err "Папка проекта не найдена: $ProjectDir"
    exit 1
}
if (-not (Test-Path -LiteralPath $FactorySrc -PathType Container)) {
    Err "Не найдена фабрика: $FactorySrc (запускайте скрипт из корня репозитория фабрики)"
    exit 1
}

$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
Info "==> Подготовка проекта: $ProjectDir"

# --- 1. Git-репозиторий -------------------------------------------------------
$GitExe = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (Test-Path -LiteralPath (Join-Path $ProjectDir '.git') -PathType Container) {
    Info "    Git: репозиторий уже существует ✓"
} else {
    Warn "    Git: репозитория нет — создаю git init"
    if (-not $GitExe) {
        Err "    Git: команда git не найдена — установите Git и повторите запуск."
        exit 1
    }
    & $GitExe.Source -C $ProjectDir init -b main
    if ($LASTEXITCODE -ne 0) {
        Err "    Git: не удалось создать репозиторий (git init, код $LASTEXITCODE)."
        exit 1
    }
}

# --- 2. Копирование фабрики ---------------------------------------------------
$ProjectAgents = Join-Path $ProjectDir '.agents'
if ($ProjectDir -eq $ScriptDir) {
    Warn "    Проект — сам репозиторий фабрики: .agents/ уже на месте, пропускаю копирование."
} elseif (Test-Path -LiteralPath $ProjectAgents -PathType Container) {
    Info "    .agents/ уже существует — обновляю содержимое фабрики (фабрика — source of truth)"
    # Перезаписываем все файлы фабрики актуальными версиями. Пользовательские файлы,
    # которых нет в фабрике, остаются нетронутыми (копирование не удаляет лишнее).
    Copy-FactoryTree -Source $FactorySrc -Destination $ProjectAgents
} else {
    Info "    Фабрика: копирую .agents/ → $ProjectAgents"
    Copy-FactoryTree -Source $FactorySrc -Destination $ProjectAgents
}

# Проверка копирования: нет SKILL.md — фабрика в проект не попала (сбой robocopy/Copy-Item
# не роняет PowerShell, поэтому проверяем результат явно — как `set -e` в bash-версии).
$SkillMd = Join-Path $ProjectAgents 'skills\code-factory\SKILL.md'
if (-not (Test-Path -LiteralPath $SkillMd -PathType Leaf)) {
    $HardError = $true
    Err "    Фабрика: НЕ скопирована — в проекте нет $SkillMd"
}

# --- 3. Память проекта --------------------------------------------------------
# memory/ — долгосрочная память ТОГО проекта, над которым работает фабрика. Каталог
# памяти всегда лежит В КОРНЕ РАЗВЁРТЫВАНИЯ ($ProjectDir), а базовое имя проекта при
# развёртывании = basename этого каталога. Единственный писатель журнала — главный агент
# фабрики, поэтому здесь только создаются ОТСУТСТВУЮЩИЕ файлы: существующая память
# (история прогонов проекта) никогда не перезаписывается — проверяется лишь её
# принадлежность.
$MemoryDir   = Join-Path $ProjectDir 'memory'
$MemScript   = Join-Path $ProjectDir '.agents\skills\code-factory\scripts\memory_project.py'
$MemState    = 'absent'          # created | ok | mixed | other | unavailable
$MemProject  = ''                # имя проекта (состояние created)
$MemOwner    = ''                # владелец памяти по данным memory_project.py check
$MemCheckOut = ''
$HasPython   = [bool]$PyExe
$HasHelper   = Test-Path -LiteralPath $MemScript -PathType Leaf

function New-MemoryCommand {
    param([string]$Mode)
    return @($PyExe) + @($PyPrefix) + @($MemScript, $Mode, '--repo', $ProjectDir)
}

# Ожидаемое имя проекта = basename корня развёртывания (ошибка интерпретатора не должна
# прерывать развёртывание).
$MemNameExpect = ''
if ($HasPython -and $HasHelper) {
    $nameRes = Invoke-Capture -Command (New-MemoryCommand -Mode 'name')
    $first   = @($nameRes.Output) | Select-Object -First 1
    if ($nameRes.ExitCode -eq 0 -and $first) { $MemNameExpect = "$first".Trim() }
}

$HasChangeLog = Test-Path -LiteralPath (Join-Path $MemoryDir 'change-log.md') -PathType Leaf
$HasSummary   = Test-Path -LiteralPath (Join-Path $MemoryDir 'summary.md')     -PathType Leaf

if (-not $HasChangeLog -or -not $HasSummary) {
    if ($HasPython -and $HasHelper) {
        $initRes = Invoke-Capture -Command (New-MemoryCommand -Mode 'init')
        if ($initRes.ExitCode -eq 0) {
            $MemState = 'created'
            $nameRes  = Invoke-Capture -Command (New-MemoryCommand -Mode 'name')
            $first    = @($nameRes.Output) | Select-Object -First 1
            if ($first) { $MemProject = "$first".Trim() }
            Info "    Память проекта: создана — $MemoryDir (проект $(if ($MemProject) { $MemProject } else { '?' }))"
            foreach ($line in @($initRes.Output)) { Write-Host ("      " + $line) }
        } else {
            $firstOut = @($initRes.Output) | Select-Object -First 1
            Warn "    Память проекта: не удалось создать — $(if ($firstOut) { $firstOut } else { 'без вывода' })"
            Warn "    Фабрика создаст её при первом обращении к проекту."
        }
    } else {
        $MemState = 'unavailable'
        if (-not $HasPython) {
            Warn "    Память проекта: не создана — python не найден"
        } else {
            Warn "    Память проекта: не создана — нет скрипта $MemScript"
        }
        Warn "    Фабрика создаст её при первом обращении к проекту."
    }
} elseif ($HasPython -and $HasHelper) {
    # Память уже есть: ничего не меняем (история проекта не перезаписывается). Проверяем
    # три исхода: журнал смешивает проекты | память объявлена за ДРУГОЙ проект | всё ок.
    # Любое состояние — только предупреждение, скрипт не роняем.
    $checkRes    = Invoke-Capture -Command (New-MemoryCommand -Mode 'check')
    $MemCheckOut = (@($checkRes.Output) | ForEach-Object { "$_" }) -join "`n"
    $memCheckRc  = $checkRes.ExitCode
    $MemOwner    = ''
    if ($MemCheckOut -match "belongs to project '([^']+)'") {
        $MemOwner = $matches[1]
    } elseif ($MemCheckOut -match "declares project '([^']+)'") {
        $MemOwner = $matches[1]
    }
    if ($MemCheckOut -match 'mixes projects') {
        $MemState = 'mixed'
        Warn "    Память проекта: НЕСОГЛАСОВАНА — в памяти записи разных проектов ($MemCheckOut)"
        Warn "    Проверьте принадлежность: поле project: в записях должно совпадать с проектом."
    } elseif (($MemCheckOut -match 'expected') -or
              (($MemOwner -ne '') -and ($MemOwner -ne $MemNameExpect) -and ($MemOwner -ne '(legacy, no project field)')) -or
              ($memCheckRc -ne 0)) {
        # Память принадлежит (или объявлена за) ДРУГОЙ проект — разворачиваемся не туда.
        $MemState = 'other'
        Warn "    Память проекта: ПРОВЕРИТЬ — память объявлена за проект '$(if ($MemOwner) { $MemOwner } else { '?' })', а фабрика разворачивается в каталоге '$MemNameExpect' ($MemCheckOut)"
        Warn "    Проверьте, что это тот же проект: поле project: в записях memory/change-log.md."
    } else {
        $MemState = 'ok'
        Info "    Память проекта: на месте — $MemCheckOut"
    }
} else {
    $MemState = 'unavailable'
    if (-not $HasPython) {
        Warn "    Память проекта: есть, но не проверена — python не найден"
    } else {
        Warn "    Память проекта: есть, но не проверена — нет скрипта $MemScript"
    }
}

# --- 4. Launcher'ы ------------------------------------------------------------
# Launcher'ы пишутся с явными кодировкой и переводами строк: start.sh — LF, start.cmd —
# CRLF, оба UTF-8 БЕЗ BOM (иначе bash/cmd ломаются на BOM перед shebang/@echo).
$LauncherSh  = Join-Path $ProjectDir 'start.sh'
$LauncherCmd = Join-Path $ProjectDir 'start.cmd'

$shLines = @(
    '#!/usr/bin/env bash',
    '# Launcher Code Factory — создан prepare_factory.sh. Запускайте без лишних команд:',
    '#   ./start.sh          — интерактивно (в чате: /skill:code-factory)',
    '#   ./start.sh --auto   — полностью автономно',
    'set -euo pipefail',
    '# Разделение моделей сабагентов (primary/secondary) включается здесь автоматически.',
    'export KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1',
    'exec kimi "$@"'
)
$shText = ($shLines -join "`n") + "`n"
$ShWritten = Write-FileStrict -Path $LauncherSh -Text $shText -Encoding $EncNoBom

$cmdLines = @(
    '@echo off',
    'chcp 65001 >nul',
    'setlocal',
    'rem Launcher Code Factory для Windows — создан prepare_factory.',
    'rem   start.cmd          — интерактивно (в чате: /skill:code-factory)',
    'rem   start.cmd --auto   — полностью автономно',
    'cd /d "%~dp0"',
    'rem Разделение моделей сабагентов (primary/secondary) включается здесь автоматически.',
    'set KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1',
    'where kimi >nul 2>&1',
    'if errorlevel 1 (',
    '    echo Команда kimi не найдена. Установите Kimi Code CLI и повторите запуск.',
    '    pause',
    '    exit /b 1',
    ')',
    'kimi %*',
    'set "EXITCODE=%ERRORLEVEL%"',
    'if not "%EXITCODE%"=="0" (',
    '    echo Фабрика завершилась с кодом %EXITCODE%.',
    '    pause',
    ')',
    'exit /b %EXITCODE%'
)
$cmdText = ($cmdLines -join "`r`n") + "`r`n"
# Существующий пользовательский start.cmd не затираем молча: если он отличается от шаблона —
# предупреждаем (launcher перезаписывается: он часть развёртывания, но пользователь узнаёт).
if (Test-Path -LiteralPath $LauncherCmd -PathType Leaf) {
    $existingCmd = $null
    try { $existingCmd = [System.IO.File]::ReadAllText($LauncherCmd) } catch { $existingCmd = $null }
    if ($null -ne $existingCmd -and $existingCmd -ne $cmdText) {
        Warn "    Launcher: $LauncherCmd уже существует и отличается от шаблона — перезаписываю"
    }
}
$CmdWritten = Write-FileStrict -Path $LauncherCmd -Text $cmdText -Encoding $EncNoBom
if ($CmdWritten) { Info "    Launcher: создан $LauncherCmd" }
if ($ShWritten)  { Info "    Launcher: создан $LauncherSh" }

# --- 5. .gitignore ------------------------------------------------------------
# Примечание: .gitignore влияет только на git-трекинг, но не на доступ к файлам
# на диске. Игнорирование .agents/ не ломает чтение/запись данных фабрики
# (кэш, история, контекст) — фабрика работает с .agents/ напрямую через файловую
# систему, а не через git.
$Gitignore        = Join-Path $ProjectDir '.gitignore'
$CfPatterns       = @('.agents/', '.code-factory/', '__pycache__/', '*.pyc', '.env', '.env.*', '*.env', '*.pem', '*.key')
$GitignoreExists  = Test-Path -LiteralPath $Gitignore -PathType Leaf
$GitignoreText    = ''
if ($GitignoreExists) { $GitignoreText = [System.IO.File]::ReadAllText($Gitignore) }
# Построчно: сравнение ровно со строкой, а не с подстрокой (".env" не должен «находиться»
# внутри "my.env.bak"). CRLF-файл при этом не мешает проверке.
$GitignoreLines   = @($GitignoreText -split "`r?`n")

$NeedGitignore = $false
foreach ($pat in $CfPatterns) {
    if ($GitignoreLines -notcontains $pat) { $NeedGitignore = $true }
}

if ($NeedGitignore) {
    Warn "    .gitignore: добавляю служебные паттерны фабрики"
    $nl = "`n"
    if ($GitignoreText -match "`r`n") { $nl = "`r`n" }
    $add = ''
    if ($GitignoreExists -and $GitignoreText.Length -gt 0) { $add += $nl }
    $add += "# --- Code Factory (auto-added by prepare_factory.ps1) ---" + $nl
    foreach ($pat in $CfPatterns) { $add += $pat + $nl }
    Write-FileStrict -Path $Gitignore -Text $add -Encoding $EncNoBom -Append | Out-Null
}

# --- 6. Проверка готовности ---------------------------------------------------
# Строку про память собираем из состояния шага 3 (повторный init не запускаем). Три
# различимых состояния: ok — память принадлежит этому проекту; mixed — записи разных
# проектов; other — память объявлена за другой проект (разворачиваемся не туда).
switch ($MemState) {
    'created' { $MemLine = "создана ✓ (проект $(if ($MemProject) { $MemProject } else { '?' }))" }
    'ok' {
        if ($MemCheckOut -match "project '([^']+)' \(([0-9]+) entries\)") {
            $memName  = $matches[1]
            $memCount = $matches[2]
            # Память без признака проекта (ни project: в записях, ни объявления в сводке):
            # подставляем имя проекта по basename корня развёртывания.
            if ($memName -eq '(legacy, no project field)' -and $HasPython -and $HasHelper) {
                $nameRes = Invoke-Capture -Command (New-MemoryCommand -Mode 'name')
                $first   = @($nameRes.Output) | Select-Object -First 1
                $memName = if ($first) { "$first".Trim() } else { '?' }
            }
            $MemLine = "OK ✓ (проект $memName, $memCount записей)"
        } else {
            $MemLine = "OK ✓"
        }
    }
    'mixed'       { $MemLine = "НЕСОГЛАСОВАНА ✗ — записи разных проектов в памяти — проверьте project:" }
    'other'       { $MemLine = "ПРОВЕРИТЬ ✗ — объявлен проект '$(if ($MemOwner) { $MemOwner } else { '?' })', разворачиваем в '$(if ($MemNameExpect) { $MemNameExpect } else { '?' })' ($MemCheckOut)" }
    'unavailable' {
        if (-not $HasPython) { $MemLine = "не проверено (нет python)" }
        else                 { $MemLine = "не проверено (нет memory_project.py)" }
    }
    default       { $MemLine = "ОТСУТСТВУЕТ ✗" }
}

$AgentsOk = if (Test-Path -LiteralPath (Join-Path $ProjectDir '.agents\skills\code-factory\SKILL.md') -PathType Leaf) { 'OK ✓' } else { 'ОТСУТСТВУЕТ ✗' }
$ShOk     = if (Test-Path -LiteralPath $LauncherSh  -PathType Leaf) { 'OK ✓' } else { 'ОТСУТСТВУЕТ ✗' }
$CmdOk    = if (Test-Path -LiteralPath $LauncherCmd -PathType Leaf) { 'OK ✓' } else { 'ОТСУТСТВУЕТ ✗' }
$GitOk    = if (Test-Path -LiteralPath (Join-Path $ProjectDir '.git') -PathType Container) { 'OK ✓' } else { 'ОТСУТСТВУЕТ ✗' }
$GiText   = if (Test-Path -LiteralPath $Gitignore -PathType Leaf) { [System.IO.File]::ReadAllText($Gitignore) } else { '' }
$GiLines  = @($GiText -split "`r?`n")
$GiOk     = if ($GiLines -contains '.agents/' -and $GiLines -contains '.code-factory/') { 'OK ✓ (.agents/ + .code-factory/)' } else { 'нет .agents/ или .code-factory/ ✗' }

Write-Host ""
Info "==> Проверка готовности:"
Write-Host "    • .agents/:            $AgentsOk"
Write-Host "    • start.sh:            $ShOk"
Write-Host "    • start.cmd:           $CmdOk"
Write-Host "    • .git/:               $GitOk"
Write-Host "    • .gitignore:          $GiOk"
Write-Host "    • memory/:              $MemLine"
Write-Host "    • git status:"
$statusOut = @()
if ($GitExe) {
    $statusRes = Invoke-Capture -Command @($GitExe.Source, '-C', $ProjectDir, 'status', '--short')
    $statusOut = @($statusRes.Output) | Select-Object -First 20
}
foreach ($line in $statusOut) { Write-Host "$line" }
if (@($statusOut).Count -eq 0) { Write-Host "      (чистое дерево)" }
Write-Host ""

# --- 7. Итог ------------------------------------------------------------------
# Жёсткая ошибка (фабрика не скопирована / файл запуска не записался) — развёртывание
# неполное: честный код возврата 1 и понятное объяснение вместо бодрого «Готово».
# Все прочие состояния (нет python, память не проверена) — предупреждения, код возврата 0.
if ($HardError) {
    Err "==> Развёртывание не завершено: фабрику или файлы запуска создать не удалось."
    Err "    Пункты, отмеченные выше как ОТСУТСТВУЕТ, на месте не появились."
    Err "    Запускать фабрику в этом проекте нельзя — проверьте права на запись в каталог"
    Err "    $ProjectDir и повторите запуск."
    exit 1
}

Info "==> Готово! Запуск фабрики — одно действие:"
Write-Host "    cd $ProjectDir"
Write-Host "    start.cmd             # в чате: /skill:code-factory"
Write-Host "    start.cmd --auto      # полностью автономно"
Write-Host ""
Write-Host "    Launcher сам выставляет KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1 —"
Write-Host "    дополнительных export-команд запоминать не нужно."
Write-Host "    (для Git Bash / Linux в проекте лежит start.sh с тем же смыслом)"
Write-Host ""

exit 0
