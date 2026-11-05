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

# 1. Verify Ollama is running
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 5
    Write-Host "Ollama service active (version: $($resp.version))." -ForegroundColor Green
} catch {
    Write-Error "Ollama is not running. Please start Ollama before running this script."
}

# 2. Record pinned model digest
Write-Host "Recording model digest for $Model..."
$showResp = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post -Body (@{name=$Model} | ConvertTo-Json) -ContentType "application/json"
$digest = $showResp.details.parent_model
Write-Host "Pinned Model Digest: $digest" -ForegroundColor Yellow

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

