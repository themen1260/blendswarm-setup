# BlendSwarm worker installer for Windows PowerShell 5.1+.
# Use from a downloaded bundle:
#   .\install.ps1 -Server https://blendswarm.com -Token WORKER_TOKEN
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$Token,
    [string]$Dir = "$env:USERPROFILE\.blendswarm-worker"
)
$ErrorActionPreference = "Stop"
$Server = $Server.TrimEnd('/')
if ([string]::IsNullOrWhiteSpace($Token)) {
    $secureToken = Read-Host "Worker token (input hidden)" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}
if ([string]::IsNullOrWhiteSpace($Token)) { throw "Worker token cannot be empty." }

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonArgs = @("-3")
    & $pythonCommand.Source @pythonArgs --version *> $null
    if ($LASTEXITCODE -ne 0) { throw "Python 3.9+ is required. Install it from https://www.python.org/downloads/." }
    $python = $pythonCommand.Source
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw "Python 3.9+ is required. Install it from https://www.python.org/downloads/ (enable Python in PATH)." }
    $python = $pythonCommand.Source
    $pythonArgs = @()
    & $python --version *> $null
    if ($LASTEXITCODE -ne 0) { throw "Could not run Python. Install Python 3.9+ and reopen PowerShell." }
}
$versionOutput = & $python @pythonArgs --version 2>&1
if ($versionOutput -notmatch 'Python 3\.(\d+)' -or [int]$Matches[1] -lt 9) {
    throw "Python 3.9+ is required; detected: $versionOutput"
}

$blenderCommand = Get-Command blender -ErrorAction SilentlyContinue
$blender = if ($blenderCommand) { $blenderCommand.Source } else { $null }
if (-not $blender) {
    $blenderRoot = "$env:ProgramFiles\Blender Foundation"
    if (Test-Path $blenderRoot) {
        $blender = Get-ChildItem $blenderRoot -Recurse -File -Filter blender.exe -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if (-not $blender) {
    throw "Blender 3.6+ was not found. Install it from https://www.blender.org/download/, then rerun this installer."
}

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$bundleDir = $PSScriptRoot
if ((Test-Path "$bundleDir\worker_client.py") -and (Test-Path "$bundleDir\requirements.txt")) {
    Copy-Item "$bundleDir\worker_client.py" "$Dir\worker_client.py" -Force
    Copy-Item "$bundleDir\requirements.txt" "$Dir\requirements.txt" -Force
} else {
    Invoke-WebRequest "$Server/downloads/worker_client.py" -OutFile "$Dir\worker_client.py"
    Invoke-WebRequest "$Server/downloads/requirements.txt" -OutFile "$Dir\requirements.txt"
}

$venvPython = "$Dir\venv\Scripts\python.exe"
& $python @pythonArgs -m venv "$Dir\venv"
if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
& $venvPython -m pip install --disable-pip-version-check -q --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not update pip." }
& $venvPython -m pip install --disable-pip-version-check -q -r "$Dir\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "Could not install worker dependencies." }

$secureToken = ConvertTo-SecureString -String $Token -AsPlainText -Force
ConvertFrom-SecureString -SecureString $secureToken | Set-Content "$Dir\token.credential" -Encoding ASCII
$Token = $null

$runFile = "$Dir\run-worker.ps1"
@"
`$ErrorActionPreference = "Stop"
`$secureToken = Get-Content "$Dir\token.credential" -Raw | ConvertTo-SecureString
`$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(`$secureToken)
try {
    `$token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(`$pointer)
    `$oldServer = `$env:RENDERSWARM_SERVER
    `$oldToken = `$env:RENDERSWARM_TOKEN
    try {
        `$env:RENDERSWARM_SERVER = "$Server"
        `$env:RENDERSWARM_TOKEN = `$token
        & "$venvPython" "$Dir\worker_client.py" --blender "$blender" @args
        if (`$LASTEXITCODE -ne 0) { throw "Worker process exited with code `$LASTEXITCODE." }
    } finally {
        `$env:RENDERSWARM_SERVER = `$oldServer
        `$env:RENDERSWARM_TOKEN = `$oldToken
        `$token = `$null
    }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR(`$pointer)
}
"@ | Set-Content $runFile -Encoding UTF8

Write-Host ""
Write-Host "BlendSwarm worker installed to $Dir"
Write-Host "Benchmark: & `"$runFile`" --test"
Write-Host "Start:     & `"$runFile`""
