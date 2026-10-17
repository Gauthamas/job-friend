# Start Job-Friend on Windows: LM Studio server + models, FastAPI backend, SvelteKit frontend.
#
# Run from PowerShell, in the folder that contains backend\ and frontend\:
#     powershell -ExecutionPolicy Bypass -File .\start_job_friend.ps1
# Stop everything (backend, frontend, models, LM Studio server):
#     powershell -ExecutionPolicy Bypass -File .\start_job_friend.ps1 stop
# Ctrl+C in the window stops the backend and frontend; LM Studio keeps running.
#
# EDIT THE SETTINGS BELOW to match your machine. Run `lms ls` to see exact model names.

param([string]$Action = "start")

# ---------- settings ----------
$RepoDir      = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir   = Join-Path $RepoDir "backend"
$FrontendDir  = Join-Path $RepoDir "frontend"
$VenvPython   = Join-Path $BackendDir ".venv\Scripts\python.exe"   # falls back to "python" if missing

$LlmModel     = "qwen/qwen3-8b"                                     # chat model (name from `lms ls`)
$EmbedModel   = "text-embedding-nomic-embed-text-v2-moe"            # embedding model (name from `lms ls`)
$LlmContext   = 8192

$LmsPort      = 1234
$BackendPort  = 8001
$FrontendPort = 5500
$StartFrontend = $true

$LogDir       = Join-Path $RepoDir "logs"
# ------------------------------

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Say($msg)  { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

function Test-Url($url) {
    try { Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true }
    catch { return $false }
}

function Wait-For($url, $seconds, $label) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Test-Url $url) { Write-Host "$label is up."; return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Stop-Tree($proc) {
    if ($proc -and -not $proc.HasExited) { & taskkill /PID $proc.Id /T /F 2>$null | Out-Null }
}

function Stop-Port($port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) { & taskkill /PID $c.OwningProcess /T /F 2>$null | Out-Null }
}

# lms CLI
$lms = Get-Command lms -ErrorAction SilentlyContinue
if (-not $lms) {
    $candidate = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"
    if (Test-Path $candidate) { $lmsPath = $candidate } else {
        Fail "The LM Studio CLI 'lms' was not found. Open LM Studio once, then run in PowerShell:  & `"$env:USERPROFILE\.lmstudio\bin\lms.exe`" bootstrap   and open a new PowerShell window."
    }
} else { $lmsPath = $lms.Source }

if ($Action -eq "stop") {
    Say "Stopping"
    & $lmsPath unload --all 2>$null
    & $lmsPath server stop 2>$null
    Stop-Port $BackendPort
    Stop-Port $FrontendPort
    Write-Host "Stopped."
    exit 0
}

# ---------- LM Studio ----------
Say "LM Studio server"
if (Test-Url "http://localhost:$LmsPort/v1/models") {
    Write-Host "Server already running on port $LmsPort."
} else {
    & $lmsPath server start --port $LmsPort *> (Join-Path $LogDir "lmstudio.log")
    if (-not (Wait-For "http://localhost:$LmsPort/v1/models" 30 "LM Studio server")) {
        Fail "LM Studio server did not come up. See $LogDir\lmstudio.log"
    }
}

Say "Models"
$loaded = (& $lmsPath ps 2>$null) -join "`n"
if ($loaded -match [regex]::Escape($LlmModel)) {
    Write-Host "$LlmModel already loaded."
} else {
    Write-Host "Loading $LlmModel (this can take a minute)..."
    & $lmsPath load $LlmModel --context-length $LlmContext -y
    if ($LASTEXITCODE -ne 0) { Fail "Could not load $LlmModel. Check the name with: lms ls" }
}
if ($loaded -match [regex]::Escape($EmbedModel)) {
    Write-Host "$EmbedModel already loaded."
} else {
    Write-Host "Loading $EmbedModel..."
    & $lmsPath load $EmbedModel -y
    if ($LASTEXITCODE -ne 0) { Fail "Could not load $EmbedModel. Check the name with: lms ls" }
}

$backendProc = $null
$frontendProc = $null

try {
    # ---------- Backend ----------
    Say "Backend (FastAPI)"
    if (-not (Test-Path $BackendDir)) { Fail "Backend folder not found: $BackendDir" }
    if (Test-Url "http://localhost:$BackendPort/docs") {
        Write-Host "Something already answers on port $BackendPort; not starting another backend."
    } else {
        $py = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
        $backendProc = Start-Process -FilePath $py `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
            -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $LogDir "backend.log") `
            -RedirectStandardError  (Join-Path $LogDir "backend.err.log")
        if (-not (Wait-For "http://localhost:$BackendPort/docs" 40 "Backend")) {
            Fail "Backend did not come up. See $LogDir\backend.err.log"
        }
    }

    # ---------- Frontend ----------
    if ($StartFrontend) {
        Say "Frontend (SvelteKit)"
        if (-not (Test-Path $FrontendDir)) { Fail "Frontend folder not found: $FrontendDir" }
        if (Test-Url "http://localhost:$FrontendPort") {
            Write-Host "Something already answers on port $FrontendPort; not starting another frontend."
        } else {
            $frontendProc = Start-Process -FilePath "npm.cmd" `
                -ArgumentList @("run", "dev", "--", "--port", "$FrontendPort") `
                -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $LogDir "frontend.log") `
                -RedirectStandardError  (Join-Path $LogDir "frontend.err.log")
            if (-not (Wait-For "http://localhost:$FrontendPort" 60 "Frontend")) {
                Fail "Frontend did not come up. See $LogDir\frontend.err.log"
            }
        }
    }

    Say "Ready"
    Write-Host "App:      http://localhost:$FrontendPort"
    Write-Host "Backend:  http://localhost:$BackendPort/docs"
    Write-Host "Logs:     $LogDir"
    Write-Host "Press Ctrl+C to stop the backend and frontend (LM Studio keeps running; run with 'stop' to stop it too)."

    while ($true) { Start-Sleep -Seconds 2 }
}
finally {
    Write-Host ""
    Write-Host "Shutting down..."
    Stop-Tree $frontendProc
    Stop-Tree $backendProc
}
