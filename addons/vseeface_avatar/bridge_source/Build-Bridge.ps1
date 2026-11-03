param(
    [Parameter(Mandatory=$true)][string]$VSeeFacePath,
    [string]$OutputDirectory = ''
)
$ErrorActionPreference='Stop'
if (!$OutputDirectory) { $OutputDirectory=Join-Path $PSScriptRoot 'build' }
. (Join-Path $PSScriptRoot 'File-Digest.ps1')
$payload=Join-Path (Split-Path $PSScriptRoot) 'bridge_payload'
$supported=@{
    '1.13.38c4'='5a24888245967b07a5884a8bd40059e33ff3141608177e7bd4f5c26df67838fe'
    '1.13.38c5'='bfe25e23fad5647c2da46a1c995a235f97c5bfdb4f9c6ed9a921ab1ef75d4150'
}
$managed=Join-Path (Resolve-Path -LiteralPath $VSeeFacePath).Path 'VSeeFace_Data/Managed'
$game=Join-Path $managed 'Assembly-CSharp.dll'
if ((Get-PrototypeDigest $game).ToLowerInvariant() -notin $supported.Values) { throw 'Unsupported VSeeFace assembly; inspect compatibility before adding support.' }
$loaderName='BepInEx_win_x64_5.4.23.3.zip'
$archive=Join-Path $payload $loaderName
if ((Get-PrototypeDigest $archive).ToLowerInvariant() -ne '41a089e5b1b1f0713b331346baf6677b1184c69eabebf51101097954e854c749') { throw 'The pinned loader checksum differs.' }
$build=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $build -Force | Out-Null
$loader=Join-Path $build 'loader'
Expand-Archive -LiteralPath $archive -DestinationPath $loader -Force
$core=Join-Path $loader 'BepInEx/core'
$compiler=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$refs=@('UnityEngine.dll','UnityEngine.CoreModule.dll','UnityEngine.AudioModule.dll','UnityEngine.JSONSerializeModule.dll','VRM.dll') | ForEach-Object { '/reference:'+(Join-Path $managed $_) }
$sources=@('BridgeState.cs','StateFile.cs','AudioProbe.cs','VmcEmotions.cs','StatusHeartbeat.cs','BridgePlugin.cs') | ForEach-Object { Join-Path $PSScriptRoot $_ }
$args=@('/nologo','/target:library','/optimize+',('/out:'+(Join-Path $build 'NCVSeeFaceBridge.dll')),('/reference:'+$game),('/reference:'+(Join-Path $core 'BepInEx.dll')),('/reference:'+(Join-Path $core '0Harmony.dll')))+$refs+$sources
& $compiler @args
if ($LASTEXITCODE -ne 0) { throw 'Bridge compilation failed.' }
Copy-Item -LiteralPath (Join-Path $build 'NCVSeeFaceBridge.dll') -Destination (Join-Path $payload 'NCVSeeFaceBridge.dll') -Force
$files=@{}; $sourceFiles=@{}
Get-ChildItem -LiteralPath $payload -File -Recurse | Where-Object Name -ne 'manifest.json' | ForEach-Object {
    $relative=$_.FullName.Substring(([IO.Path]::GetFullPath($payload)).Length+1).Replace('\','/')
    $files[$relative]=(Get-PrototypeDigest $_.FullName).ToLowerInvariant()
}
Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object Name -ne '.gitignore' | ForEach-Object {
    $sourceFiles[$_.Name]=(Get-PrototypeDigest $_.FullName).ToLowerInvariant()
}
$manifest=@{schema_version=1;bridge_version='0.2.0';protocol_version=1;plugin_id='nc.vseeface.speech.prototype';supported_assemblies=$supported;files=$files;source_files=$sourceFiles;loader_url='https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.3/BepInEx_win_x64_5.4.23.3.zip'}
$json=$manifest | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText((Join-Path $payload 'manifest.json'),$json,(New-Object Text.UTF8Encoding($false)))
Write-Output ('Built and inventoried, not installed: '+(Join-Path $payload 'NCVSeeFaceBridge.dll'))
