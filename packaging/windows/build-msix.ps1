# The MSIX: the tree build-tree.sh makes, with a manifest and the tiles,
# packed by the Windows SDK's makeappx. Unsigned - the Store signs what it is
# given; CI signs a copy with a test certificate to install it.
#
#   build-msix.ps1 -Tree OUT\Danu -Version 0.2.0 -Out out [-Name ...] [-Publisher ...]
#
# Name and Publisher are the identity Partner Center reserves for the app;
# until it has one, these are stand-ins that install but cannot be submitted.
param(
    [Parameter(Mandatory)] [string] $Tree,
    [Parameter(Mandatory)] [string] $Version,
    [Parameter(Mandatory)] [string] $Out,
    [string] $Name = 'OpenGeofiction.Danu',
    [string] $Publisher = 'CN=OpenGeofiction',
    [string] $PublisherDisplay = 'OpenGeofiction'
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

# MSIX versions have four parts, the last of which the Store reserves as 0
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "version $Version is not x.y.z" }
$v4 = "$Version.0"

$layout = Join-Path ([System.IO.Path]::GetTempPath()) "danu-msix-$PID"
if (Test-Path $layout) { throw "$layout exists" }
New-Item -ItemType Directory $layout | Out-Null
Copy-Item -Recurse "$Tree\*" $layout
Copy-Item -Recurse "$here\msix\Assets" $layout
(Get-Content -Raw "$here\msix\AppxManifest.xml.in") `
    -replace '@NAME@', $Name -replace '@PUBLISHER@', $Publisher `
    -replace '@PUBLISHER_DISPLAY@', $PublisherDisplay -replace '@VERSION@', $v4 |
    Set-Content -Encoding utf8 "$layout\AppxManifest.xml"

# the newest SDK's makeappx
$makeappx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $makeappx) { throw 'no makeappx: the Windows SDK is not installed' }
New-Item -ItemType Directory -Force $Out | Out-Null
$msix = Join-Path (Resolve-Path $Out) "danu-$Version-windows.msix"
& $makeappx.FullName pack /o /h SHA256 /d $layout /p $msix | Select-Object -Last 3
if ($LASTEXITCODE) { throw "makeappx failed: $LASTEXITCODE" }
Remove-Item -Recurse -Force $layout
Get-Item $msix | Select-Object Name, Length
