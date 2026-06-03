# run_phase1.ps1
# Runs the phase 1 prompts in sequence. Stops on first failure.
# Usage: .\run_phase1.ps1
#
# Optional: pass a starting prompt number to resume from a specific point.
# Example: .\run_phase1.ps1 -StartAt 3   (skips prompts 1 and 2)

param(
    [int]$StartAt = 1,
    [switch]$DryRun,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

# Repo root is the parent of this script's folder (phase1_prompts/).
$RepoRoot = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

# Test gate: the non-integration suite must stay green after every prompt.
# Returns $true when green (or when -SkipTests / python missing), $false on failure.
function Test-SuiteGreen {
    if ($SkipTests) { return $true }
    if (-not (Test-Path $Python)) {
        Write-Host "  (test gate skipped: $Python not found)" -ForegroundColor DarkYellow
        return $true
    }
    Write-Host "  Running test gate: pytest -q -m 'not integration'" -ForegroundColor DarkCyan
    & $Python -m pytest -q -m "not integration" --no-header
    return ($LASTEXITCODE -eq 0)
}

$prompts = Get-ChildItem -Path $PSScriptRoot -Filter "prompt_*.md" | Sort-Object Name

if ($prompts.Count -eq 0) {
    Write-Host "No prompt_*.md files found in $PSScriptRoot" -ForegroundColor Red
    exit 1
}

foreach ($p in $prompts) {
    # Extract the prompt number from the filename (prompt_NN_*.md)
    if ($p.Name -match '^prompt_(\d+)_') {
        $num = [int]$Matches[1]
    } else {
        continue
    }

    if ($num -lt $StartAt) {
        Write-Host "Skipping $($p.Name) (before StartAt=$StartAt)" -ForegroundColor DarkGray
        continue
    }

    Write-Host ""
    Write-Host "=== Running $($p.Name) ===" -ForegroundColor Cyan
    Write-Host ""

    if ($DryRun) {
        Write-Host "[dry run] would execute: claude --dangerously-skip-permissions -p `"<contents of $($p.Name)>`""
        continue
    }

    $content = Get-Content -Raw $p.FullName
    claude --dangerously-skip-permissions -p $content

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "FAILED on $($p.Name) (claude exit code $LASTEXITCODE)" -ForegroundColor Red
        Write-Host "Resume with: .\run_phase1.ps1 -StartAt $num" -ForegroundColor Yellow
        exit 1
    }

    # Gate on the test suite so a session that exits 0 but leaves tests red
    # halts the chain instead of cascading breakage into later prompts.
    if (-not (Test-SuiteGreen)) {
        Write-Host ""
        Write-Host "FAILED test gate after $($p.Name) (suite is red)" -ForegroundColor Red
        Write-Host "Inspect the failures, then resume with: .\run_phase1.ps1 -StartAt $num" -ForegroundColor Yellow
        exit 1
    }

    Write-Host "Completed $($p.Name)" -ForegroundColor Green
}

Write-Host ""
Write-Host "All prompts completed." -ForegroundColor Green
