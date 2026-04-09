param(
    [switch]$SkipTorch,
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$launcher = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } elseif (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { $null }
if (-not $launcher) {
    throw "Could not find 'py' or 'python' to launch install_neural_interface.py."
}

$args = @('install_neural_interface.py', '--main')
if ($SkipTorch) {
    $args += '--skip-main-torch'
}
if ($PythonExe) {
    $args += @('--python-exe', $PythonExe)
}

& $launcher @args
