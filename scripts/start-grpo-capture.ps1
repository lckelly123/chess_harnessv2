param(
    [string]$PythonPath = (Join-Path $env:USERPROFILE '.unsloth\studio\unsloth_studio\Scripts\python.exe'),
    [string]$AdapterRoot = (Join-Path $env:USERPROFILE '.unsloth\studio\outputs'),
    [string]$ListenAddress = '0.0.0.0',
    [ValidateRange(1024, 65535)][int]$Port = 8890
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.runtime'
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Unsloth Python was not found. Pass -PythonPath pointing to an environment with Unsloth, FastAPI and Uvicorn installed.'
}
if (-not (Test-Path -LiteralPath $AdapterRoot -PathType Container)) {
    throw 'The Unsloth adapter output directory was not found. Pass -AdapterRoot with the Studio outputs directory.'
}
if ($ListenAddress -notmatch '^[A-Za-z0-9.:-]+$') { throw 'Invalid listen address.' }
$healthUrl = "http://127.0.0.1:$Port/health"
$existing = $null
try { $existing = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 } catch { }
if ($existing) {
    if ($existing.service -ne 'chess-grpo-capture') { throw "Port $Port is already used by another service." }
    Write-Output "GRPO capture worker is already running on port $Port."
    exit 0
}
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
$tokenPath = Join-Path $runtimePath 'grpo-capture.token'
if (-not (Test-Path -LiteralPath $tokenPath)) {
    $tokenBytes = [byte[]]::new(32)
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($tokenBytes) } finally { $rng.Dispose() }
    $token = ([BitConverter]::ToString($tokenBytes)).Replace('-', '').ToLowerInvariant()
    [IO.File]::WriteAllText($tokenPath, $token)
}
$workerArgs = @(
    '-m', 'grpo_capture.worker', '--host', $ListenAddress, '--port', [string]$Port,
    '--adapter-root', ('"' + $AdapterRoot + '"'), '--token-file', ('"' + $tokenPath + '"')
)
$workerProcess = Start-Process -FilePath $PythonPath -ArgumentList $workerArgs -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'grpo-capture.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'grpo-capture.stderr.log')
[IO.File]::WriteAllText((Join-Path $runtimePath 'grpo-capture.pid'), [string]$workerProcess.Id)
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
        if ($health.service -eq 'chess-grpo-capture') { $ready = $true; break }
    } catch { }
    $workerProcess.Refresh()
    if ($workerProcess.HasExited) { break }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) {
    throw 'The capture worker did not become ready. See .runtime/grpo-capture.stderr.log for the startup error.'
}
Write-Output "Started GRPO capture worker (PID $($workerProcess.Id), port $Port). The model loads when Save for GRPO starts a collection."
