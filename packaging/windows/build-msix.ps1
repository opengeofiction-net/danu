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

# the newest SDK's makeappx
$makeappx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $makeappx) { throw 'no makeappx: the Windows SDK is not installed' }

# a layout of its own, gone afterwards however the pack went
$layout = Join-Path ([System.IO.Path]::GetTempPath()) "danu-msix-$([guid]::NewGuid())"
New-Item -ItemType Directory $layout | Out-Null
try {
    Copy-Item -Recurse "$Tree\*" $layout
    Copy-Item -Recurse "$here\msix\Assets" $layout
    # literal replacements: a publisher may hold what -replace would read as a group
    (Get-Content -Raw "$here\msix\AppxManifest.xml.in").Replace('@NAME@', $Name).
        Replace('@PUBLISHER_DISPLAY@', $PublisherDisplay).Replace('@PUBLISHER@', $Publisher).
        Replace('@VERSION@', $v4) | Set-Content -Encoding utf8 "$layout\AppxManifest.xml"
    New-Item -ItemType Directory -Force $Out | Out-Null
    $msix = Join-Path (Resolve-Path $Out) "danu-$Version-windows.msix"
    $said = & $makeappx.FullName pack /o /h SHA256 /d $layout /p $msix 2>&1
    if ($LASTEXITCODE) { $said; throw "makeappx failed: $LASTEXITCODE" }
    $said | Select-Object -Last 2
} finally {
    Remove-Item -Recurse -Force $layout
}
Get-Item $msix | Select-Object Name, Length
