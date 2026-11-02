param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Push-Location $PSScriptRoot
try {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONUNBUFFERED = '1'
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $python)) {
        if ($PythonPath) {
            & $PythonPath -m venv .venv
        } elseif ($uv) {
            $env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.runtime'
            & $uv.Source venv .venv --python 3.12 --cache-dir .uv-cache
        } else {
            & py -3.12 -m venv .venv
        }
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or uv, then run setup again.' }
    }
    if ($uv) {
        & $uv.Source pip install --python $python -r requirements.txt --cache-dir .uv-cache
    } else {
        & $python -m pip install -r requirements.txt
    }
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

    $envFile = Join-Path $PSScriptRoot '.env'
    if (-not (Test-Path -LiteralPath $envFile)) {
        $secret = & $python -c 'import secrets; print(secrets.token_urlsafe(64))'
        if ($LASTEXITCODE -ne 0) { throw 'SECRET_KEY generation failed.' }
        $template = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '.env.windows.example'))
        [IO.File]::WriteAllText($envFile, $template.Replace('GENERATE_ON_SETUP', $secret), [Text.UTF8Encoding]::new($false))
        Write-Host 'Created local .env with a random SECRET_KEY.'
    } else {
        Write-Host 'Using existing .env.'
    }
    foreach ($command in @(@('check'), @('migrate', '--noinput'), @('collectstatic', '--noinput'))) {
        & $python manage.py @command
        if ($LASTEXITCODE -ne 0) { throw "Django command failed: $command" }
    }
    Write-Host 'Ready. Start the website: powershell -ExecutionPolicy Bypass -File .\start-windows.ps1'
} finally {
    Pop-Location
}
