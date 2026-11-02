param(
    [switch]$WithBot,
    [switch]$BotOnly,
    [ValidateRange(1, 65535)][int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($WithBot -and $BotOnly) { throw 'Choose -WithBot or -BotOnly.' }
Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup-windows.ps1 first.' }
    if (-not (Test-Path -LiteralPath '.env')) { throw 'Run setup-windows.ps1 first to create .env.' }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONUNBUFFERED = '1'
    $arguments = @('manage.py', 'runall', "127.0.0.1:$Port")
    if ($BotOnly) { $arguments += '--no-web' }
    elseif (-not $WithBot) { $arguments += '--web-only' }
    & $python @arguments
    $result = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $result
