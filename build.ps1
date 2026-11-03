param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist'))
$ErrorActionPreference = 'Stop'
$packageDirectory = Join-Path $OutputDirectory 'staging/factory_building'
New-Item -ItemType Directory -Path $packageDirectory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'factory_building/__init__.py') -Destination $packageDirectory -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'factory_building/core.py') -Destination $packageDirectory -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'factory_building/collider_geometry.py') -Destination $packageDirectory -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'factory_building/colliders.py') -Destination $packageDirectory -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'factory_building/exporter.py') -Destination $packageDirectory -Force
$archive = Join-Path $OutputDirectory 'factory_building-0.3.2.zip'
Compress-Archive -LiteralPath $packageDirectory -DestinationPath $archive -Force
Write-Output (Get-Item -LiteralPath $archive).FullName
