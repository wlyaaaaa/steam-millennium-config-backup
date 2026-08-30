[CmdletBinding()]
param(
    [string] $SourceRoot,
    [string] $DestinationRoot,
    [string] $RuntimeRoot = '',
    [int] $ThrottleDays = 7,
    [switch] $Force,
    [switch] $AllowDirtyDestination
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime'
}

if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $DestinationRoot = Split-Path -Parent $PSScriptRoot
}

function Get-MillenniumSourceRoot {
    param([string] $ExplicitSourceRoot)

    if ($ExplicitSourceRoot) {
        if (Test-Path -LiteralPath $ExplicitSourceRoot) {
            return (Resolve-Path -LiteralPath $ExplicitSourceRoot).Path
        }

        throw "SourceRoot does not exist: $ExplicitSourceRoot"
    }

    $candidates = New-Object System.Collections.Generic.List[string]

    try {
        $steamPath = (Get-ItemProperty -LiteralPath 'HKCU:\Software\Valve\Steam' -Name SteamPath -ErrorAction Stop).SteamPath
        if ($steamPath) {
            $candidates.Add((Join-Path $steamPath 'millennium'))
        }
    }
    catch {
        # Registry discovery is best-effort; fall back to common install paths.
    }

    if ($env:ProgramFiles_x86) {
        $candidates.Add((Join-Path $env:ProgramFiles_x86 'Steam\millennium'))
    }
    elseif (${env:ProgramFiles(x86)}) {
        $candidates.Add((Join-Path ${env:ProgramFiles(x86)} 'Steam\millennium'))
    }

    if ($env:ProgramFiles) {
        $candidates.Add((Join-Path $env:ProgramFiles 'Steam\millennium'))
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Could not find Steam Millennium config root. Checked: $($candidates -join '; ')"
}

function Get-FullPath {
    param([Parameter(Mandatory = $true)] [string] $Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathsOverlap {
    param(
        [Parameter(Mandatory = $true)] [string] $Left,
        [Parameter(Mandatory = $true)] [string] $Right
    )

    $leftFull = (Get-FullPath $Left).TrimEnd('\', '/')
    $rightFull = (Get-FullPath $Right).TrimEnd('\', '/')
    if ($leftFull.Equals($rightFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }

    $separator = [System.IO.Path]::DirectorySeparatorChar
    return $leftFull.StartsWith($rightFull + $separator, [System.StringComparison]::OrdinalIgnoreCase) -or
        $rightFull.StartsWith($leftFull + $separator, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)] [string] $Parent,
        [Parameter(Mandatory = $true)] [string] $Child
    )

    $parentFull = Get-FullPath $Parent
    $childFull = Get-FullPath $Child
    if (-not $parentFull.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $parentFull = $parentFull + [System.IO.Path]::DirectorySeparatorChar
    }

    if (-not $childFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside parent path. Parent=$parentFull Child=$childFull"
    }
}

function Remove-DirectoryInside {
    param(
        [Parameter(Mandatory = $true)] [string] $Parent,
        [Parameter(Mandatory = $true)] [string] $Child
    )

    Assert-ChildPath -Parent $Parent -Child $Child
    if (Test-Path -LiteralPath $Child) {
        Remove-Item -LiteralPath $Child -Recurse -Force
    }
}

function Test-DestinationDirty {
    param(
        [Parameter(Mandatory = $true)] [string] $Root,
        [Parameter(Mandatory = $true)] [string] $SourceRoot
    )

    if (-not (Test-Path -LiteralPath (Join-Path $Root '.git'))) {
        return $false
    }

    # The scheduled task executes this script from the destination repository.
    # A source-only edit to the runner is not snapshot data that the task will
    # overwrite. Snapshot files are allowed only when they already byte-match
    # the current source; divergent manual edits remain protected.
    $selfRelativePath = 'tools\snapshot-millennium-config.ps1'
    $status = @(git -C $Root status --porcelain --untracked-files=all)
    foreach ($entry in $status) {
        if ([string]::IsNullOrWhiteSpace($entry) -or $entry.Length -lt 4) {
            continue
        }

        $relativePath = $entry.Substring(3).Trim().Trim('"').Replace('/', '\')
        if ($relativePath -eq $selfRelativePath) {
            continue
        }

        if ($relativePath -match '^(config|plugins|themes)[\\/]') {
            $sourcePath = Join-Path $SourceRoot $relativePath
            $destinationPath = Join-Path $Root $relativePath
            if ((Test-Path -LiteralPath $sourcePath -PathType Leaf) -and
                (Test-Path -LiteralPath $destinationPath -PathType Leaf)) {
                $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
                $destinationHash = (Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash
                if ($sourceHash -eq $destinationHash) {
                    continue
                }
            }
        }

        return $true
    }

    return $false
}

function Copy-IfPresent {
    param(
        [Parameter(Mandatory = $true)] [string] $SourceBase,
        [Parameter(Mandatory = $true)] [string] $StagingBase,
        [Parameter(Mandatory = $true)] [string] $RelativePath
    )

    $sourcePath = Join-Path $SourceBase $RelativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        return 0
    }

    $targetPath = Join-Path $StagingBase $RelativePath
    $targetDir = Split-Path -Parent $targetPath
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
    return 1
}

function Copy-MillenniumAllowlist {
    param(
        [Parameter(Mandatory = $true)] [string] $SourceBase,
        [Parameter(Mandatory = $true)] [string] $StagingBase
    )

    $copied = 0
    $copied += Copy-IfPresent -SourceBase $SourceBase -StagingBase $StagingBase -RelativePath 'config\config.json'
    $copied += Copy-IfPresent -SourceBase $SourceBase -StagingBase $StagingBase -RelativePath 'config\quick.css'

    $pluginRoot = Join-Path $SourceBase 'plugins'
    if (Test-Path -LiteralPath $pluginRoot) {
        foreach ($plugin in Get-ChildItem -LiteralPath $pluginRoot -Directory) {
            foreach ($fileName in @('plugin.json', 'metadata.json', 'install-state.json')) {
                $relativePath = Join-Path (Join-Path 'plugins' $plugin.Name) $fileName
                $copied += Copy-IfPresent -SourceBase $SourceBase -StagingBase $StagingBase -RelativePath $relativePath
            }
        }
    }

    $themeRoot = Join-Path $SourceBase 'themes'
    if (Test-Path -LiteralPath $themeRoot) {
        foreach ($theme in Get-ChildItem -LiteralPath $themeRoot -Directory) {
            foreach ($fileName in @('metadata.json', 'skin.json', 'theme.json', 'options.json', 'waifus.json')) {
                $relativePath = Join-Path (Join-Path 'themes' $theme.Name) $fileName
                $copied += Copy-IfPresent -SourceBase $SourceBase -StagingBase $StagingBase -RelativePath $relativePath
            }
        }
    }

    return $copied
}

function Test-SensitiveStagingContent {
    param([Parameter(Mandatory = $true)] [string] $StagingBase)

    $failures = New-Object System.Collections.Generic.List[string]
    $bannedFileNames = @('id_cache.json', 'cache.json', 'debug.log')
    $bannedDirs = @('bin', 'lib', 'crashes')
    $allowedExtensions = @('.json', '.css')

    foreach ($file in Get-ChildItem -LiteralPath $StagingBase -Recurse -File) {
        if ($bannedFileNames -contains $file.Name.ToLowerInvariant()) {
            $failures.Add("banned file copied: $($file.FullName)")
        }

        if ($allowedExtensions -notcontains $file.Extension.ToLowerInvariant()) {
            $failures.Add("banned extension copied: $($file.FullName)")
        }

        $relative = $file.FullName.Substring((Get-FullPath $StagingBase).Length).TrimStart('\', '/')
        foreach ($dir in $bannedDirs) {
            if ($relative -match "(^|[\\/])$([regex]::Escape($dir))([\\/]|$)") {
                $failures.Add("banned directory copied: $relative")
            }
        }

        $content = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction Stop
        if ($content -match '7656119\d{10}') {
            $failures.Add("SteamID64-like value found in $relative")
        }

        if ($content -match '"proxyPassword"\s*:\s*"[^"]+"') {
            $failures.Add("non-empty proxyPassword found in $relative")
        }

        if ($content -match '"proxyUsername"\s*:\s*"[^"]+"') {
            $failures.Add("non-empty proxyUsername found in $relative")
        }
    }

    if ($failures.Count -gt 0) {
        throw "Snapshot failed public-safety scan:`n$($failures -join "`n")"
    }
}

function Get-StatePath {
    param([Parameter(Mandatory = $true)] [string] $RuntimeRootPath)
    return (Join-Path $RuntimeRootPath 'snapshot-state.json')
}

function Test-ThrottleWindow {
    param(
        [Parameter(Mandatory = $true)] [string] $RuntimeRootPath,
        [Parameter(Mandatory = $true)] [int] $Days
    )

    if ($Force -or $Days -le 0) {
        return $false
    }

    $statePath = Get-StatePath -RuntimeRootPath $RuntimeRootPath
    if (-not (Test-Path -LiteralPath $statePath)) {
        return $false
    }

    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if (-not $state.lastSnapshotUtc) {
            return $false
        }

        $lastSnapshot = [datetime]::Parse($state.lastSnapshotUtc).ToUniversalTime()
        return ([datetime]::UtcNow - $lastSnapshot).TotalDays -lt $Days
    }
    catch {
        return $false
    }
}

$resolvedSource = Get-MillenniumSourceRoot -ExplicitSourceRoot $SourceRoot
$destinationFull = Get-FullPath $DestinationRoot
if (Test-PathsOverlap -Left $resolvedSource -Right $destinationFull) {
    throw "SourceRoot and DestinationRoot must not overlap. Source=$resolvedSource Destination=$destinationFull"
}

New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

$resolvedDestination = (Resolve-Path -LiteralPath $DestinationRoot).Path
$resolvedRuntime = (Resolve-Path -LiteralPath $RuntimeRoot).Path

if ((Test-DestinationDirty -Root $resolvedDestination -SourceRoot $resolvedSource) -and -not $AllowDirtyDestination) {
    throw "Destination git workspace is dirty. Commit/review existing changes before snapshot, or pass -AllowDirtyDestination for an intentional manual run."
}

if (Test-ThrottleWindow -RuntimeRootPath $resolvedRuntime -Days $ThrottleDays) {
    Write-Host "Skipped: last snapshot is newer than $ThrottleDays day(s). Use -Force to override."
    exit 0
}

$stagingRoot = Join-Path $resolvedRuntime 'staging'
Remove-DirectoryInside -Parent $resolvedRuntime -Child $stagingRoot
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null

$copiedCount = Copy-MillenniumAllowlist -SourceBase $resolvedSource -StagingBase $stagingRoot
if ($copiedCount -eq 0) {
    throw "No allowlisted Millennium config files were found under $resolvedSource"
}

Test-SensitiveStagingContent -StagingBase $stagingRoot

foreach ($dirName in @('config', 'plugins', 'themes')) {
    $targetDir = Join-Path $resolvedDestination $dirName
    Remove-DirectoryInside -Parent $resolvedDestination -Child $targetDir

    $stagedDir = Join-Path $stagingRoot $dirName
    if (Test-Path -LiteralPath $stagedDir) {
        Copy-Item -LiteralPath $stagedDir -Destination $resolvedDestination -Recurse -Force
    }
}

$state = [pscustomobject]@{
    lastSnapshotUtc = [datetime]::UtcNow.ToString('o')
    sourceRoot      = $resolvedSource
    destinationRoot = $resolvedDestination
    copiedFiles     = $copiedCount
}
$state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Get-StatePath -RuntimeRootPath $resolvedRuntime) -Encoding UTF8

Write-Host "Snapshot complete. Copied $copiedCount allowlisted file(s)."
