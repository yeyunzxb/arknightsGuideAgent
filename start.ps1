$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$candidates = @(
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    'py',
    'python',
    'python3'
)
# Also locate Python installations when PATH contains only Windows Store aliases.
$pythonRoot = Join-Path $env:LOCALAPPDATA 'Python'
if (Test-Path -LiteralPath $pythonRoot) {
    $candidates += @(Get-ChildItem -LiteralPath $pythonRoot -Directory | Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'python.exe' })
}
foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
    try {
        & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $candidate (Join-Path $PSScriptRoot 'scripts\launch.py') @args
            exit $LASTEXITCODE
        }
    } catch { continue }
}
Write-Host 'Please install Python 3.11+ and Node.js 18.19+ (22 LTS recommended), then retry.' -ForegroundColor Red
exit 1
