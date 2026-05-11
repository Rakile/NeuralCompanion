param(
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$launcher = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } elseif (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { $null }
if (-not $launcher) {
    throw "Could not find 'py' or 'python' to launch install_neural_companion.py."
}

$args = @('install_neural_companion.py', '--musetalk')
if ($PythonExe) {
    $args += @('--python-exe', $PythonExe)
}

& $launcher @args
