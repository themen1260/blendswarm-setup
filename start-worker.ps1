$ErrorActionPreference = "Stop"

try {
    Write-Host "BlendSwarm Windows worker setup" -ForegroundColor Cyan
    Write-Host "Install Blender 3.6+ and Python 3.9+ first."
    $server = Read-Host "Server URL [https://blendswarm.com]"
    if ([string]::IsNullOrWhiteSpace($server)) {
        $server = "https://blendswarm.com"
    }
    $server = $server.Trim().TrimEnd('/')
    if ($server -notmatch '^https://[A-Za-z0-9.-]+(?::[0-9]+)?$') {
        throw "Server must be an https URL, for example https://blendswarm.com."
    }

    $secureToken = Read-Host "Worker token (input hidden)" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "Worker token cannot be empty."
    }

    Write-Host "`nInstalling the worker. Keep this window open..." -ForegroundColor Yellow
    & "$PSScriptRoot\install.ps1" -Server $server -Token $token
    if (-not $?) {
        throw "Worker installer failed. Review the error shown above."
    }

    $runScript = Join-Path $env:USERPROFILE ".blendswarm-worker\run-worker.ps1"
    $test = Read-Host "`nRun the Blender/CPU benchmark now? [Y/n]"
    if ($test -notmatch '^(n|no)$') {
        & $runScript --test
        if (-not $?) {
            throw "Worker benchmark failed. Review the error shown above."
        }
    }

    Write-Host "`nStarting worker. Leave this window open; press Ctrl+C to stop." -ForegroundColor Green
    & $runScript
    if (-not $?) {
        throw "Worker exited with an error. Review the error shown above."
    }
} catch {
    Write-Host "`nSETUP/RUN ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Check Python, Blender, network access, and the worker token. This window will stay open."
}

Read-Host "`nPress Enter to close this window"
