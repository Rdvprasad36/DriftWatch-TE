# DriftWatch-TE: Local Reference Model Runner (Windows / Ollama)
# Alternative to GitHub Actions runner for hardware-accelerated local reference evaluation.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run_local_reference.ps1 -Week 2026-11-09 -Trials 5

param (
    [string]$Week = (Get-Date -Format "yyyy-MM-dd"),
    [int]$Trials = 5,
    [string]$Model = "llama3.2:1b",
    [string]$OllamaUrl = "http://localhost:11434/v1"
)

$ErrorActionPreference = "Stop"

Write-Host "=== DriftWatch-TE Local Reference Evaluation ===" -ForegroundColor Cyan
Write-Host "Week: $Week | Trials: $Trials | Model: $Model"

# 1. Verify Ollama is running with readiness loop
Write-Host "Checking Ollama service readiness..."
$ready = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($resp.version) {
            Write-Host "Ollama service active (version: $($resp.version), attempt $i)." -ForegroundColor Green
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) {
    Write-Error "Ollama is not running. Please start Ollama before running this script."
}

# 2. Record and verify pinned model digest
Write-Host "Verifying model digest for $Model against config/study.yaml..."
python -c "from driftwatch.config import load_study_config; import subprocess, sys; cfg = load_study_config(); expected = (cfg.local_model_digest or '').strip(); res = subprocess.run(['ollama', 'list'], capture_output=True, text=True); actual = ''; [actual := line.split()[1] for line in res.stdout.splitlines() if '$Model' in line]; print(f'Expected: {expected} | Actual: {actual}'); sys.exit(0 if (expected and (actual == expected or actual.startswith(expected) or expected.startswith(actual))) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Model digest verification failed. Model does not match pinned local_model_digest in config/study.yaml."
}

# 3. Verify suite integrity
Write-Host "Verifying suite integrity..."
python -m driftwatch.cli.main verify
if ($LASTEXITCODE -ne 0) {
    Write-Error "Suite verification failed. Exiting."
}

# 4. Run canary prompts
Write-Host "Running zero-temperature canary prompts..."
$env:LOCAL_MODEL_URL = $OllamaUrl
$env:LOCAL_MODEL = $Model
python -m driftwatch.cli.main canary --week "$Week" --models "local" --results-dir "weekly"

# 5. Run evaluation trials
Write-Host "Running evaluation trials for local reference..."
python -m driftwatch.cli.main run --week "$Week" --suites "canary,control,attacks_v1" --models "local" --trials $Trials --results-dir "weekly"

Write-Host "Local reference evaluation complete for week $Week." -ForegroundColor Green

