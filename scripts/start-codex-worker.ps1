param(
    [string]$Model,
    [string]$ReasoningEffort
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$runtimePath = Join-Path $projectRoot '.runtime'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create backend\.venv and install backend\requirements-mcp.txt first. See docs\codex-mcp.md.'
}
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
$pidPath = Join-Path $runtimePath 'worker.pid'
if (Test-Path -LiteralPath $pidPath) {
    $workerProcessId = [int](Get-Content -LiteralPath $pidPath)
    $existingWorker = Get-CimInstance Win32_Process -Filter "ProcessId = $workerProcessId" -ErrorAction SilentlyContinue
    if ($existingWorker -and $existingWorker.CommandLine -match 'codex_training\.worker') {
        Write-Output "Codex worker already running (PID $workerProcessId)."
        exit 0
    }
}
$workerArgs = @('-m', 'codex_training.worker')
if ($Model) { $workerArgs += @('--model', $Model) }
if ($ReasoningEffort) { $workerArgs += @('--reasoning-effort', $ReasoningEffort) }
if ($Model -and $Model -notmatch '^[A-Za-z0-9_.:/-]+$') { throw 'Invalid model identifier.' }
if ($ReasoningEffort -and $ReasoningEffort -notmatch '^(low|medium|high|xhigh|max|ultra)$') { throw 'Invalid reasoning effort.' }
$workerProcess = Start-Process -FilePath $pythonPath -ArgumentList $workerArgs -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'worker.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'worker.stderr.log')
[IO.File]::WriteAllText($pidPath, [string]$workerProcess.Id)
Write-Output "Started Codex worker (PID $($workerProcess.Id)). Select Codex (training) in Positional testing once it connects."
