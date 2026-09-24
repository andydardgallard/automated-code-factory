param(
    [Parameter(Position = 0)]
    [string]$ProjectDir
)

# =============================================================================
# prepare_factory.ps1 — prepare a project for running Code Factory in one action
# (the Windows version of prepare_factory.sh: same result, no Git Bash).
#
# Purpose: copy the factory (.agents/) into the project, create the memory of
# THIS specific project (`memory/` — the long-term memory of the target project:
# journal `memory/change-log.md` + summary `memory/summary.md`), configure
# .gitignore, initialize a git repository if needed, create the `start.cmd`
# (Windows) and `start.sh` (Git Bash/Linux) launchers and verify readiness.
#
# Where the memory lives and how the project is named:
#   * `memory/` is created IN THE DEPLOYMENT ROOT — the directory passed to this
#     script; the base project name at deployment = basename of that directory.
#   * If the task's `repo_path` points to a SUBDIRECTORY of the deployment root,
#     the main agent creates the memory explicitly, naming the project:
#       memory_project.py init --repo <deployment root> --project <repo_path basename>
# Existing project memory is NEVER overwritten: missing files are created, while
# existing ones (the project's run history) are left untouched. If the memory is
# declared for ANOTHER project or mixes projects — only a warning (the script
# still exits with exit 0).
#
# Python is needed only for the factory scripts (project memory) and may be
# absent — in that case the deployment continues and completes successfully.
#
# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File prepare_factory.ps1 <path-to-project>
#
# Example:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File prepare_factory.ps1 C:\work\my-project
#
# After preparation a single action is enough:
#   cd <path-to-project>
#   start.cmd            # interactive (in the chat: /skill:code-factory)
#   start.cmd --auto     # fully autonomous
#
# The script does NOT commit anything. All steps are safe and idempotent.
# =============================================================================

# Non-ASCII text must remain readable when output is redirected (pipe/file).
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

# Child python processes must also print UTF-8: in the local code page (cp1251) a project
# name with Cyrillic reads as garbage, and characters outside cp1251 (e.g. CJK) break
# printing entirely (UnicodeEncodeError) — the memory would look uncreated although the files were created.
$env:PYTHONUTF8 = '1'

# --- Paths ---------------------------------------------------------------------
$ScriptDir  = if ($PSScriptRoot) { (Resolve-Path -LiteralPath $PSScriptRoot).Path } else { (Get-Location).Path }
$FactorySrc = Join-Path $ScriptDir '.agents'          # the ready-made factory (this repository)
$EncNoBom   = New-Object System.Text.UTF8Encoding($false)

# A hard error is the same as `set -e` in the bash version: if the factory could not be copied
# or a launcher file was not written, the deployment is incomplete and exits with code 1
# (no "Done" banner). Expected degradations (no python, memory not verified) are NOT hard errors.
$HardError  = $false

function Info { param([string]$Message) Write-Host $Message }
function Warn { param([string]$Message) Write-Host $Message }
function Err  { param([string]$Message) [Console]::Error.WriteLine($Message) }

# --- Helper functions -----------------------------------------------------------
# Run an external command capturing stdout+stderr and the exit code.
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

# Copying the factory tree: robocopy (preserves everything, including hidden items),
# falling back to a recursive Copy-Item if robocopy is unavailable/fails.
function Copy-FactoryTree {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
        $null = New-Item -ItemType Directory -Force -Path $Destination
    }
    $robocopy = Get-Command robocopy.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($robocopy) {
        & $robocopy.Source $Source $Destination /E /NFL /NDL /NJH /NJS /NP | Out-Null
        # 0-7 — success (incl. "files copied"), 8+ — a real error.
        if ($LASTEXITCODE -lt 8) { return }
    }
    # A Copy-Item failure does not crash the script in PowerShell (non-terminating error): the
    # output gets raw engine records (CategoryInfo, FullyQualifiedErrorId) that tell the user
    # nothing. So we turn the error into a terminating one (-ErrorAction Stop) and report the
    # failure ourselves — like Write-FileStrict. A partially copied .agents/ is a hard error
    # (same as `set -e` in the bash version): the deployment exits with code 1, no "Done" banner.
    try {
        Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force -ErrorAction Stop
        }
    } catch {
        $script:HardError = $true
        Err "    Factory: copy failed — $($_.Exception.Message)"
    }
}

# Write a deployment file. A write failure (e.g. no permissions on the directory) does not
# crash the script in PowerShell, so we catch it ourselves and mark the run with a hard error:
# without the launcher file the project cannot be considered prepared. Returns $true if written.
function Write-FileStrict {
    param([string]$Path, [string]$Text, [System.Text.Encoding]$Encoding, [switch]$Append)
    try {
        if ($Append) { [System.IO.File]::AppendAllText($Path, $Text, $Encoding) }
        else         { [System.IO.File]::WriteAllText($Path, $Text, $Encoding) }
        return $true
    } catch {
        $script:HardError = $true
        Err "    Failed to write file: $Path"
        return $false
    }
}

# --- Python interpreter ----------------------------------------------------------
# Needed for the factory scripts (project memory). May be missing — that is not an error.
# Candidate order: py -3, py, python, python3. The Microsoft Store `python3` stub
# (Windows) exists as a file but does not work, so every candidate is checked with a
# real run and the first WORKING one is taken.
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

# --- Argument check --------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    Err "Specify the project path:  prepare_factory.ps1 <path-to-project>"
    exit 1
}
if (-not (Test-Path -LiteralPath $ProjectDir -PathType Container)) {
    Err "Project folder not found: $ProjectDir"
    exit 1
}
if (-not (Test-Path -LiteralPath $FactorySrc -PathType Container)) {
    Err "Factory not found: $FactorySrc (run the script from the factory repository root)"
    exit 1
}

$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
Info "==> Preparing project: $ProjectDir"

# --- 1. Git repository ------------------------------------------------------------
$GitExe = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (Test-Path -LiteralPath (Join-Path $ProjectDir '.git') -PathType Container) {
    Info "    Git: repository already exists ✓"
} else {
    Warn "    Git: no repository — running git init"
    if (-not $GitExe) {
        Err "    Git: the git command was not found — install Git and run again."
        exit 1
    }
    & $GitExe.Source -C $ProjectDir init -b main
    if ($LASTEXITCODE -ne 0) {
        Err "    Git: failed to create the repository (git init, code $LASTEXITCODE)."
        exit 1
    }
}

# --- 2. Copying the factory --------------------------------------------------------
$ProjectAgents = Join-Path $ProjectDir '.agents'
if ($ProjectDir -eq $ScriptDir) {
    Warn "    The project is the factory repository itself: .agents/ is already in place, skipping the copy."
} elseif (Test-Path -LiteralPath $ProjectAgents -PathType Container) {
    Info "    .agents/ already exists — updating the factory contents (the factory is the source of truth)"
    # We overwrite all factory files with the current versions. User files that are not
    # part of the factory are left untouched (the copy does not delete extras).
    Copy-FactoryTree -Source $FactorySrc -Destination $ProjectAgents
} else {
    Info "    Factory: copying .agents/ → $ProjectAgents"
    Copy-FactoryTree -Source $FactorySrc -Destination $ProjectAgents
}

# Copy verification: no SKILL.md means the factory did not make it into the project (a
# robocopy/Copy-Item failure does not crash PowerShell, so check the result explicitly — like `set -e` in the bash version).
$SkillMd = Join-Path $ProjectAgents 'skills\code-factory\SKILL.md'
if (-not (Test-Path -LiteralPath $SkillMd -PathType Leaf)) {
    $HardError = $true
    Err "    Factory: NOT copied — $SkillMd is missing in the project"
}

# --- 3. Project memory -------------------------------------------------------------
# memory/ — the long-term memory of THE project the factory works on. The
# memory directory always lives IN THE DEPLOYMENT ROOT ($ProjectDir), and the base
# project name at deployment = basename of that directory. The only writer of the
# journal is the factory's main agent, so here only MISSING files are created:
# existing memory (the project's run history) is never overwritten — only its
# ownership is checked.
$MemoryDir   = Join-Path $ProjectDir 'memory'
$MemScript   = Join-Path $ProjectDir '.agents\skills\code-factory\scripts\memory_project.py'
$MemState    = 'absent'          # created | ok | mixed | other | unavailable
$MemProject  = ''                # project name (created state)
$MemOwner    = ''                # memory owner per memory_project.py check
$MemCheckOut = ''
$HasPython   = [bool]$PyExe
$HasHelper   = Test-Path -LiteralPath $MemScript -PathType Leaf

function New-MemoryCommand {
    param([string]$Mode)
    return @($PyExe) + @($PyPrefix) + @($MemScript, $Mode, '--repo', $ProjectDir)
}

# The expected project name = basename of the deployment root (an interpreter error must
# not interrupt the deployment).
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
            Info "    Project memory: created — $MemoryDir (project $(if ($MemProject) { $MemProject } else { '?' }))"
            foreach ($line in @($initRes.Output)) { Write-Host ("      " + $line) }
        } else {
            $firstOut = @($initRes.Output) | Select-Object -First 1
            Warn "    Project memory: failed to create — $(if ($firstOut) { $firstOut } else { 'no output' })"
            Warn "    The factory will create it on first access to the project."
        }
    } else {
        $MemState = 'unavailable'
        if (-not $HasPython) {
            Warn "    Project memory: not created — python not found"
        } else {
            Warn "    Project memory: not created — script $MemScript is missing"
        }
        Warn "    The factory will create it on first access to the project."
    }
} elseif ($HasPython -and $HasHelper) {
    # Memory already exists: we change nothing (the project's history is never overwritten).
    # Check three outcomes: the journal mixes projects | the memory is declared for ANOTHER
    # project | everything is fine. Any state is only a warning — we do not crash the script.
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
        Warn "    Project memory: INCONSISTENT — entries from different projects in memory ($MemCheckOut)"
        Warn "    Check ownership: the project: field in entries must match the project."
    } elseif (($MemCheckOut -match 'expected') -or
              (($MemOwner -ne '') -and ($MemOwner -ne $MemNameExpect) -and ($MemOwner -ne '(legacy, no project field)')) -or
              ($memCheckRc -ne 0)) {
        # The memory belongs to (or is declared for) ANOTHER project — we are deploying to the wrong place.
        $MemState = 'other'
        Warn "    Project memory: CHECK — the memory is declared for project '$(if ($MemOwner) { $MemOwner } else { '?' })', but the factory is being deployed in directory '$MemNameExpect' ($MemCheckOut)"
        Warn "    Verify this is the same project: the project: field in the memory/change-log.md entries."
    } else {
        $MemState = 'ok'
        Info "    Project memory: in place — $MemCheckOut"
    }
} else {
    $MemState = 'unavailable'
    if (-not $HasPython) {
        Warn "    Project memory: present but not verified — python not found"
    } else {
        Warn "    Project memory: present but not verified — script $MemScript is missing"
    }
}

# --- 4. Launchers ------------------------------------------------------------------
# The launchers are written with explicit encoding and line endings: start.sh — LF,
# start.cmd — CRLF, both UTF-8 WITHOUT BOM (otherwise bash/cmd break on the BOM before the shebang/@echo).
$LauncherSh  = Join-Path $ProjectDir 'start.sh'
$LauncherCmd = Join-Path $ProjectDir 'start.cmd'

$shLines = @(
    '#!/usr/bin/env bash',
    '# Code Factory launcher — created by prepare_factory.sh. Run it with no extra commands:',
    '#   ./start.sh          — interactive (in the chat: /skill:code-factory)',
    '#   ./start.sh --auto   — fully autonomous',
    'set -euo pipefail',
    '# Subagent model split (primary/secondary) is enabled here automatically.',
    'export KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1',
    'exec kimi "$@"'
)
$shText = ($shLines -join "`n") + "`n"
$ShWritten = Write-FileStrict -Path $LauncherSh -Text $shText -Encoding $EncNoBom

$cmdLines = @(
    '@echo off',
    'chcp 65001 >nul',
    'setlocal',
    'rem Code Factory launcher for Windows — created by prepare_factory.',
    'rem   start.cmd          — interactive (in the chat: /skill:code-factory)',
    'rem   start.cmd --auto   — fully autonomous',
    'cd /d "%~dp0"',
    'rem Subagent model split (primary/secondary) is enabled here automatically.',
    'set KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1',
    'where kimi >nul 2>&1',
    'if errorlevel 1 (',
    '    echo The kimi command was not found. Install Kimi Code CLI and run again.',
    '    pause',
    '    exit /b 1',
    ')',
    'kimi %*',
    'set "EXITCODE=%ERRORLEVEL%"',
    'if not "%EXITCODE%"=="0" (',
    '    echo The factory exited with code %EXITCODE%.',
    '    pause',
    ')',
    'exit /b %EXITCODE%'
)
$cmdText = ($cmdLines -join "`r`n") + "`r`n"
# We do not silently overwrite an existing user start.cmd: if it differs from the template —
# warn (the launcher is overwritten: it is part of the deployment, but the user finds out).
if (Test-Path -LiteralPath $LauncherCmd -PathType Leaf) {
    $existingCmd = $null
    try { $existingCmd = [System.IO.File]::ReadAllText($LauncherCmd) } catch { $existingCmd = $null }
    if ($null -ne $existingCmd -and $existingCmd -ne $cmdText) {
        Warn "    Launcher: $LauncherCmd already exists and differs from the template — overwriting"
    }
}
$CmdWritten = Write-FileStrict -Path $LauncherCmd -Text $cmdText -Encoding $EncNoBom
if ($CmdWritten) { Info "    Launcher: created $LauncherCmd" }
if ($ShWritten)  { Info "    Launcher: created $LauncherSh" }

# --- 5. .gitignore -----------------------------------------------------------------
# Note: .gitignore only affects git tracking, not access to files on disk.
# Ignoring .agents/ does not break reading/writing the factory's data (cache,
# history, context) — the factory works with .agents/ directly through the file
# system, not through git.
$Gitignore        = Join-Path $ProjectDir '.gitignore'
$CfPatterns       = @('.agents/', '.code-factory/', '__pycache__/', '*.pyc', '.env', '.env.*', '*.env', '*.pem', '*.key')
$GitignoreExists  = Test-Path -LiteralPath $Gitignore -PathType Leaf
$GitignoreText    = ''
if ($GitignoreExists) { $GitignoreText = [System.IO.File]::ReadAllText($Gitignore) }
# Line by line: compare with the exact line, not a substring (".env" must not be "found"
# inside "my.env.bak"). A CRLF file does not break the check.
$GitignoreLines   = @($GitignoreText -split "`r?`n")

$NeedGitignore = $false
foreach ($pat in $CfPatterns) {
    if ($GitignoreLines -notcontains $pat) { $NeedGitignore = $true }
}

if ($NeedGitignore) {
    Warn "    .gitignore: adding the factory's utility patterns"
    $nl = "`n"
    if ($GitignoreText -match "`r`n") { $nl = "`r`n" }
    $add = ''
    if ($GitignoreExists -and $GitignoreText.Length -gt 0) { $add += $nl }
    $add += "# --- Code Factory (auto-added by prepare_factory.ps1) ---" + $nl
    foreach ($pat in $CfPatterns) { $add += $pat + $nl }
    Write-FileStrict -Path $Gitignore -Text $add -Encoding $EncNoBom -Append | Out-Null
}

# --- 6. Readiness check -------------------------------------------------------------
# The memory line is assembled from the state of step 3 (we do not run init again).
# Three distinguishable states: ok — the memory belongs to this project; mixed —
# entries from different projects; other — the memory is declared for another project (we are deploying to the wrong place).
switch ($MemState) {
    'created' { $MemLine = "created ✓ (project $(if ($MemProject) { $MemProject } else { '?' }))" }
    'ok' {
        if ($MemCheckOut -match "project '([^']+)' \(([0-9]+) entries\)") {
            $memName  = $matches[1]
            $memCount = $matches[2]
            # Memory without a project marker (neither project: in entries nor a declaration in
            # the summary): substitute the project name from the deployment root basename.
            if ($memName -eq '(legacy, no project field)' -and $HasPython -and $HasHelper) {
                $nameRes = Invoke-Capture -Command (New-MemoryCommand -Mode 'name')
                $first   = @($nameRes.Output) | Select-Object -First 1
                $memName = if ($first) { "$first".Trim() } else { '?' }
            }
            $MemLine = "OK ✓ (project $memName, $memCount entries)"
        } else {
            $MemLine = "OK ✓"
        }
    }
    'mixed'       { $MemLine = "INCONSISTENT ✗ — entries from different projects in memory — check project:" }
    'other'       { $MemLine = "CHECK ✗ — declared project '$(if ($MemOwner) { $MemOwner } else { '?' })', deploying into '$(if ($MemNameExpect) { $MemNameExpect } else { '?' })' ($MemCheckOut)" }
    'unavailable' {
        if (-not $HasPython) { $MemLine = "not verified (no python)" }
        else                 { $MemLine = "not verified (no memory_project.py)" }
    }
    default       { $MemLine = "MISSING ✗" }
}

$AgentsOk = if (Test-Path -LiteralPath (Join-Path $ProjectDir '.agents\skills\code-factory\SKILL.md') -PathType Leaf) { 'OK ✓' } else { 'MISSING ✗' }
$ShOk     = if (Test-Path -LiteralPath $LauncherSh  -PathType Leaf) { 'OK ✓' } else { 'MISSING ✗' }
$CmdOk    = if (Test-Path -LiteralPath $LauncherCmd -PathType Leaf) { 'OK ✓' } else { 'MISSING ✗' }
$GitOk    = if (Test-Path -LiteralPath (Join-Path $ProjectDir '.git') -PathType Container) { 'OK ✓' } else { 'MISSING ✗' }
$GiText   = if (Test-Path -LiteralPath $Gitignore -PathType Leaf) { [System.IO.File]::ReadAllText($Gitignore) } else { '' }
$GiLines  = @($GiText -split "`r?`n")
$GiOk     = if ($GiLines -contains '.agents/' -and $GiLines -contains '.code-factory/') { 'OK ✓ (.agents/ + .code-factory/)' } else { 'no .agents/ or .code-factory/ ✗' }

Write-Host ""
Info "==> Readiness check:"
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
if (@($statusOut).Count -eq 0) { Write-Host "      (clean tree)" }
Write-Host ""

# --- 7. Summary ----------------------------------------------------------------------
# A hard error (factory not copied / launcher file not written) means the deployment is
# incomplete: an honest exit code 1 and a clear explanation instead of a cheerful "Done".
# All other states (no python, memory not verified) are warnings, exit code 0.
if ($HardError) {
    Err "==> Deployment incomplete: the factory or the launcher files could not be created."
    Err "    The items marked MISSING above did not appear."
    Err "    The factory cannot be started in this project — check write permissions for the directory"
    Err "    $ProjectDir and run again."
    exit 1
}

Info "==> Done! Starting the factory is a single action:"
Write-Host "    cd $ProjectDir"
Write-Host "    start.cmd             # in the chat: /skill:code-factory"
Write-Host "    start.cmd --auto      # fully autonomous"
Write-Host ""
Write-Host "    The launcher sets KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1 itself —"
Write-Host "    no extra export commands to remember."
Write-Host "    (for Git Bash / Linux the project contains start.sh with the same meaning)"
Write-Host ""

exit 0
