[CmdletBinding()]
param(
    [string]$IsccPath = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    [string]$InstallRoot = "$env:LOCALAPPDATA\Programs",
    [switch]$KeepEvidence
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$productionGuid = 'B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D'
$testGuid = ([guid]::NewGuid().ToString()).ToUpperInvariant()
$testName = "InvoiceHubInstallerLifecycle-$PID"
$installRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
$installDir = Join-Path (Join-Path $installRoot $testName) 'install'
$workDir = Join-Path $env:TEMP "$testName-work"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{$testGuid}_is1"
$userDataDir = Join-Path $workDir 'user-data'
$appDataDir = Join-Path $userDataDir 'AppData\InvoiceHub'
$documentsDir = Join-Path $userDataDir 'Documents\Invoice Hub'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-Setup {
    param([string]$Path, [string]$LogName)
    $logPath = Join-Path $workDir $LogName
    $process = Start-Process -FilePath $Path -ArgumentList @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/MERGETASKS=!desktopicon',
        "/LOG=$logPath"
    ) -Wait -PassThru -WindowStyle Hidden
    Assert-True ($process.ExitCode -eq 0) "Setup failed with exit code $($process.ExitCode)."
    return $logPath
}

function Get-RegisteredUninstaller {
    Assert-True (Test-Path -LiteralPath $uninstallKey) 'Uninstall registration is missing.'
    $command = [string](Get-ItemPropertyValue -LiteralPath $uninstallKey -Name UninstallString)
    $command = $command.Trim()
    if ($command.StartsWith('"')) {
        $endQuote = $command.IndexOf('"', 1)
        Assert-True ($endQuote -gt 1) 'Registered uninstall command is malformed.'
        return $command.Substring(1, $endQuote - 1)
    }
    $match = [regex]::Match($command, '^(.*?\.exe)(?:\s|$)', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
    Assert-True $match.Success 'Registered uninstall command does not contain an executable.'
    return $match.Groups[1].Value
}

function Assert-CurrentRegistration {
    param([string]$Version)
    $uninstaller = Get-RegisteredUninstaller
    $displayVersion = Get-ItemPropertyValue -LiteralPath $uninstallKey -Name DisplayVersion
    $installLocation = Get-ItemPropertyValue -LiteralPath $uninstallKey -Name InstallLocation
    Assert-True ($displayVersion -eq $Version) "Expected version $Version, got $displayVersion."
    Assert-True (Test-Path -LiteralPath $uninstaller) 'Registered uninstaller is missing.'
    Assert-True (Test-Path -LiteralPath ([IO.Path]::ChangeExtension($uninstaller, '.dat'))) 'Registered uninstall log is missing.'
    $registeredInstallPath = $installLocation.TrimEnd('\')
    $expectedInstallPath = (Resolve-Path -LiteralPath $installDir).Path.TrimEnd('\')
    Assert-True ($registeredInstallPath -ieq $expectedInstallPath) 'InstallLocation does not match the isolated install directory.'
}

function Invoke-RegisteredUninstall {
    param([switch]$AllowInstallDirectoryRemainder)
    $command = Get-RegisteredUninstaller
    Assert-True (Test-Path -LiteralPath $command) 'Registered uninstaller does not exist.'
    $process = Start-Process -FilePath $command -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
    ) -Wait -PassThru -WindowStyle Hidden
    Assert-True ($process.ExitCode -eq 0) "Uninstall failed with exit code $($process.ExitCode)."
    for ($i = 0; $i -lt 50 -and (Test-Path -LiteralPath $uninstallKey); $i++) {
        Start-Sleep -Milliseconds 100
    }
    Assert-True (-not (Test-Path -LiteralPath $uninstallKey)) 'Uninstall registration remained.'
    if (-not $AllowInstallDirectoryRemainder) {
        for ($i = 0; $i -lt 50 -and (Test-Path -LiteralPath $installDir); $i++) {
            Start-Sleep -Milliseconds 100
        }
        Assert-True (-not (Test-Path -LiteralPath $installDir)) 'Install directory remained after verified uninstall.'
    }
}

function Invoke-ExpectedUninstallAbort {
    param([string]$Reason)
    $command = Get-RegisteredUninstaller
    Assert-True (Test-Path -LiteralPath $command) 'Registered uninstaller does not exist before expected abort.'
    $process = Start-Process -FilePath $command -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
    ) -Wait -PassThru -WindowStyle Hidden
    Write-Verbose "Expected uninstall abort for $Reason returned exit code $($process.ExitCode)."
    Assert-True (Test-Path -LiteralPath $uninstallKey) "Uninstall registration was removed after expected abort: $Reason"
    Assert-True (Test-Path -LiteralPath $installDir) "Install directory was removed after expected abort: $Reason"
    Assert-True (Test-Path -LiteralPath $command) "Registered uninstaller was removed after expected abort: $Reason"
    Assert-NoProductResidualProcesses
}

function Get-UserDataSnapshot {
    $records = @(
        Get-ChildItem -LiteralPath $userDataDir -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName |
            ForEach-Object {
                $relative = $_.FullName.Substring($userDataDir.Length).TrimStart('\')
                $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
                '{0}|{1}|{2}' -f $relative, $_.Length, $hash
            }
    )
    return ($records -join [Environment]::NewLine)
}

function Assert-UserDataUnchanged {
    param([string]$ExpectedSnapshot)
    Assert-True (Test-Path -LiteralPath $appDataDir) 'AppData fixture was removed.'
    Assert-True (Test-Path -LiteralPath $documentsDir) 'Documents fixture was removed.'
    $actualSnapshot = Get-UserDataSnapshot
    Assert-True ($actualSnapshot -eq $ExpectedSnapshot) 'User data changed during installer lifecycle.'
}

function New-UserDataFixture {
    New-Item -ItemType Directory -Path (Join-Path $appDataDir 'attachments') -Force | Out-Null
    New-Item -ItemType Directory -Path $documentsDir -Force | Out-Null
    [IO.File]::WriteAllText(
        (Join-Path $appDataDir 'invoices.db'),
        'synthetic invoice database baseline',
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::WriteAllText(
        (Join-Path $appDataDir 'attachments\historical-rc2-proof.pdf'),
        'synthetic attachment baseline',
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::WriteAllText(
        (Join-Path $documentsDir 'historical-export.zip'),
        'synthetic export baseline',
        [Text.UTF8Encoding]::new($false)
    )
}

function Write-FixtureFile {
    param([string]$Root, [string]$RelativePath, [string]$Content)
    $path = Join-Path $Root $RelativePath
    $parent = Split-Path -Parent $path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    [IO.File]::WriteAllText($path, $Content, [Text.UTF8Encoding]::new($false))
}

function New-HistoricalPayloads {
    $payloads = @{}
    foreach ($name in @('rc1', 'rc2', 'current')) {
        $payloads[$name] = Join-Path $workDir "payload-$name"
        New-Item -ItemType Directory -Path $payloads[$name] -Force | Out-Null
    }

    Write-FixtureFile $payloads.rc1 'InvoiceHub.exe' 'synthetic RC1 executable'
    Write-FixtureFile $payloads.rc1 'legacy\rc1-only.pyd' 'synthetic RC1-only module'
    Write-FixtureFile $payloads.rc1 'legacy\nested\rc1-only.txt' 'synthetic nested RC1 file'
    Write-FixtureFile $payloads.rc1 'legacy-junction\sentinel.dll' 'synthetic junction sentinel'

    Write-FixtureFile $payloads.rc2 'InvoiceHub.exe' 'synthetic RC2 executable'
    Write-FixtureFile $payloads.rc2 'legacy\rc1-only.pyd' 'synthetic RC1-only module'
    Write-FixtureFile $payloads.rc2 'legacy\nested\rc1-only.txt' 'synthetic nested RC1 file'
    Write-FixtureFile $payloads.rc2 'legacy\rc2-only.dll' 'synthetic RC2-only module'
    Write-FixtureFile $payloads.rc2 'legacy-junction\sentinel.dll' 'synthetic junction sentinel'

    Write-FixtureFile $payloads.current 'InvoiceHub.exe' 'synthetic current executable'
    Write-FixtureFile $payloads.current 'current\current-only.dll' 'synthetic current module'
    return $payloads
}

function Invoke-Python {
    param([string[]]$Arguments)
    & python @Arguments
    Assert-True ($LASTEXITCODE -eq 0) "Python command failed: python $($Arguments -join ' ')"
}

function New-OwnershipFixtures {
    param([hashtable]$Payloads)
    $generator = Join-Path $repoRoot 'scripts\dev\generate_installer_ownership.py'
    $manifestRc1 = Join-Path $workDir 'rc1-files.txt'
    $manifestRc2 = Join-Path $workDir 'rc2-files.txt'
    Invoke-Python @(
        $generator, 'manifest', '--source-dir', $Payloads.rc1, '--output', $manifestRc1,
        '--release', 'fixture-rc1', '--asset-name', 'fixture-rc1.zip', '--asset-sha256', ('0' * 64)
    )
    Invoke-Python @(
        $generator, 'manifest', '--source-dir', $Payloads.rc2, '--output', $manifestRc2,
        '--release', 'fixture-rc2', '--asset-name', 'fixture-rc2.zip', '--asset-sha256', ('1' * 64)
    )
    $legacyDir = Join-Path $workDir 'legacy'
    New-Item -ItemType Directory -Path $legacyDir -Force | Out-Null
    $include = Join-Path $legacyDir 'installer_ownership.issinc'
    $currentManifest = Join-Path $workDir 'current-files.txt'
    Invoke-Python @(
        $generator, 'include', '--current-dir', $Payloads.current,
        '--legacy-manifest', $manifestRc1, '--legacy-manifest', $manifestRc2,
        '--output', $include, '--current-manifest-output', $currentManifest
    )
    $includeText = [IO.File]::ReadAllText($include, [Text.Encoding]::UTF8)
    Assert-True ($includeText.Contains('LegacyOwnershipCount = 4;')) 'Historical fixture did not produce four old-only records.'
    return $include
}

function Compile-Installer {
    param([string]$ScriptPath, [string]$Version, [string]$PayloadDir)
    $compilerOutput = & $IsccPath $ScriptPath "/DAppVersion=$Version" "/DDefaultInstallDir=$installDir" "/DSourceDir=$PayloadDir" "/DOutputDir=$workDir"
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed for version $Version.`n$($compilerOutput -join [Environment]::NewLine)" }
    Write-Verbose ($compilerOutput -join [Environment]::NewLine)
    $setupPath = Join-Path $workDir "InvoiceHub-$Version-win64-setup.exe"
    Assert-True (Test-Path -LiteralPath $setupPath) "Setup output was not created for $Version."
    return $setupPath
}

function Assert-NoProductResidualProcesses {
    $residual = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -match '^(InvoiceHub|unins[0-9]+|ISCC)$'
    })
    Assert-True ($residual.Count -eq 0) "Installer lifecycle probe left residual process(es): $($residual.ProcessName -join ', ')"
}

try {
    Assert-True (Test-Path -LiteralPath $IsccPath) "ISCC.exe was not found at $IsccPath."
    Assert-True ($installDir.StartsWith((Join-Path $installRoot 'InvoiceHubInstallerLifecycle-'))) 'Unsafe test install path.'
    Assert-True ($workDir.StartsWith((Join-Path $env:TEMP 'InvoiceHubInstallerLifecycle-'))) 'Unsafe test work path.'

    New-Item -ItemType Directory -Path $workDir -Force | Out-Null
    New-UserDataFixture
    $userDataSnapshot = Get-UserDataSnapshot
    Assert-True ($userDataSnapshot.Length -gt 0) 'User data fixture was not created.'

    $payloads = New-HistoricalPayloads
    $ownershipInclude = New-OwnershipFixtures $payloads

    $sourcePath = Join-Path $repoRoot 'packaging\invoice_hub_windows.iss'
    $source = [IO.File]::ReadAllText($sourcePath, [Text.Encoding]::UTF8)
    Assert-True $source.Contains('RemoveBrokenUninstallRegistration') 'Stale-registration removal code is missing.'
    Assert-True $source.Contains('RemoveKnownLegacyOwnedFiles') 'Historical ownership cleanup is missing.'
    Assert-True (-not $source.Contains('RegWriteStringValue')) 'Installer must not rewrite uninstall registration.'
    Assert-True (-not $source.Contains('FindAlternateUninstaller')) 'Installer must not manually select an alternate log.'
    Assert-True $source.Contains('Abort;') 'Installer must abort before native uninstall when preservation fails.'
    Assert-True $source.Contains('Refusing to touch a legacy path below a reparse point') 'Installer must reject reparse paths before mutation.'
    $testSource = $source.Replace($productionGuid, $testGuid)
    Assert-True ($testSource -ne $source) 'Test AppId replacement failed.'
    $currentScript = Join-Path $workDir 'current.iss'
    [IO.File]::WriteAllText($currentScript, $testSource, [Text.UTF8Encoding]::new($false))

    $codeIndex = $testSource.IndexOf('[Code]')
    Assert-True ($codeIndex -gt 0) 'The installer repair code section was not found.'
    $oldScript = Join-Path $workDir 'historical.iss'
    [IO.File]::WriteAllText(
        $oldScript,
        $testSource.Substring(0, $codeIndex),
        [Text.UTF8Encoding]::new($false)
    )

    $rc1 = Compile-Installer $oldScript '0.1.5-rc1' $payloads.rc1
    $rc2 = Compile-Installer $oldScript '0.1.5-rc2' $payloads.rc2
    $candidate = Compile-Installer $currentScript '0.1.5-rc3-dev' $payloads.current

    # Fresh candidate install -> registered uninstall -> clean install tree.
    Invoke-Setup $candidate 'fresh.log' | Out-Null
    Assert-CurrentRegistration '0.1.5-rc3-dev'
    Invoke-RegisteredUninstall
    Assert-UserDataUnchanged $userDataSnapshot

    # Distinct historical RC1 payload -> candidate upgrade. The old-only
    # files are not in the current payload, so verified ownership cleanup must
    # remove them before the install directory is considered clean.
    Invoke-Setup $rc1 'rc1-valid.log' | Out-Null
    Invoke-Setup $candidate 'rc1-to-candidate.log' | Out-Null
    Assert-CurrentRegistration '0.1.5-rc3-dev'
    Invoke-RegisteredUninstall
    Assert-UserDataUnchanged $userDataSnapshot

    # Preserve the current FAIL evidence: RC1/RC2 use different payloads and
    # the ARP entry is intentionally restored to the observed stale unins000
    # registration while a valid unins001 pair remains in the app directory.
    Invoke-Setup $rc1 'field-rc1.log' | Out-Null
    $rc1Uninstaller = Get-RegisteredUninstaller
    Assert-True ((Split-Path -Leaf $rc1Uninstaller) -ieq 'unins000.exe') 'Historical RC1 fixture did not use unins000.exe.'
    Remove-Item -LiteralPath ([IO.Path]::ChangeExtension($rc1Uninstaller, '.dat')) -Force
    Invoke-Setup $rc2 'field-rc2.log' | Out-Null
    $brokenExe = Join-Path $installDir 'unins000.exe'
    $alternateExe = Join-Path $installDir 'unins001.exe'
    $alternateDat = Join-Path $installDir 'unins001.dat'
    Assert-True (Test-Path -LiteralPath $brokenExe) 'Historical RC2 fixture lost unins000.exe.'
    Assert-True (Test-Path -LiteralPath $alternateExe) 'Historical RC2 fixture did not create unins001.exe.'
    Assert-True (Test-Path -LiteralPath $alternateDat) 'Historical RC2 fixture did not create unins001.dat.'
    Remove-Item -LiteralPath ([IO.Path]::ChangeExtension($brokenExe, '.dat')) -Force -ErrorAction SilentlyContinue

    # This is a test-only registry fixture for the previously observed field
    # state. Product code never rewrites an alternate command; it deletes the
    # exact stale key and lets native Inno AppId discovery choose the log.
    Set-ItemProperty -LiteralPath $uninstallKey -Name DisplayVersion -Value '0.1.5-rc1'
    Set-ItemProperty -LiteralPath $uninstallKey -Name UninstallString -Value ('"' + $brokenExe + '"')
    Set-ItemProperty -LiteralPath $uninstallKey -Name QuietUninstallString -Value ('"' + $brokenExe + '" /SILENT')

    $repairLog = Invoke-Setup $candidate 'field-repair.log'
    Assert-CurrentRegistration '0.1.5-rc3-dev'
    Assert-True (Test-Path -LiteralPath $alternateExe) 'Valid alternate uninstaller was removed during repair.'
    Assert-True (Test-Path -LiteralPath $alternateDat) 'Valid alternate uninstall log was removed during repair.'
    $repairText = [IO.File]::ReadAllText($repairLog, [Text.Encoding]::UTF8)
    Assert-True ($repairText.Contains('Removed the damaged Invoice Hub uninstall registration before native setup.')) 'Stale ARP removal was not logged.'
    Invoke-RegisteredUninstall
    Assert-UserDataUnchanged $userDataSnapshot

    # Unknown user-created files are not in the historical manifest and must
    # survive the native uninstall. The harness removes only this synthetic
    # file afterwards so the next case starts from a clean install directory.
    Invoke-Setup $candidate 'unknown-file.log' | Out-Null
    $unknownFile = Join-Path $installDir 'user-created.txt'
    [IO.File]::WriteAllText($unknownFile, 'synthetic user file', [Text.UTF8Encoding]::new($false))
    Assert-CurrentRegistration '0.1.5-rc3-dev'
    Invoke-RegisteredUninstall -AllowInstallDirectoryRemainder
    Assert-True (Test-Path -LiteralPath $unknownFile) 'Unknown user file was deleted by uninstall.'
    Assert-UserDataUnchanged $userDataSnapshot
    Remove-Item -LiteralPath $unknownFile -Force
    Remove-Item -LiteralPath $installDir -Recurse -Force

    # A historical file whose hash changed must also be preserved.
    Invoke-Setup $rc1 'hash-mismatch-rc1.log' | Out-Null
    Invoke-Setup $candidate 'hash-mismatch-candidate.log' | Out-Null
    $alteredFile = Join-Path $installDir 'legacy\rc1-only.pyd'
    Assert-True (Test-Path -LiteralPath $alteredFile) 'Historical old-only fixture file was not present.'
    [IO.File]::WriteAllText($alteredFile, 'synthetic user modification', [Text.UTF8Encoding]::new($false))
    Invoke-RegisteredUninstall -AllowInstallDirectoryRemainder
    Assert-True (Test-Path -LiteralPath $alteredFile) 'Hash-mismatched historical file was deleted.'
    Assert-UserDataUnchanged $userDataSnapshot
    Remove-Item -LiteralPath $installDir -Recurse -Force

    # A reparse point is an unsafe filesystem boundary. The uninstaller must
    # abort before native processing, leaving both the junction and its
    # external target untouched and the ARP registration usable.
    Invoke-Setup $candidate 'reparse-candidate.log' | Out-Null
    $externalDir = Join-Path $workDir 'external-junction-target'
    $junctionDir = Join-Path $installDir 'legacy-junction'
    New-Item -ItemType Directory -Path $externalDir -Force | Out-Null
    $externalSentinel = Join-Path $externalDir 'sentinel.dll'
    [IO.File]::WriteAllText($externalSentinel, 'synthetic junction sentinel', [Text.UTF8Encoding]::new($false))
    New-Item -ItemType Junction -Path $junctionDir -Target $externalDir | Out-Null
    $junctionInfo = Get-Item -LiteralPath $junctionDir -Force
    Assert-True (($junctionInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) 'Junction fixture was not a reparse point.'
    $externalBefore = (Get-FileHash -LiteralPath $externalSentinel -Algorithm SHA256).Hash
    Invoke-ExpectedUninstallAbort 'reparse point'
    Assert-True (Test-Path -LiteralPath $junctionDir) 'Reparse junction was removed after expected abort.'
    Assert-True (Test-Path -LiteralPath $externalSentinel) 'External junction target was removed after expected abort.'
    $externalAfter = (Get-FileHash -LiteralPath $externalSentinel -Algorithm SHA256).Hash
    Assert-True ($externalAfter -eq $externalBefore) 'External junction target changed after expected abort.'
    Assert-True (Test-Path -LiteralPath (Join-Path $installDir 'InvoiceHub.exe')) 'Application was removed after expected reparse abort.'
    if (Test-Path -LiteralPath $junctionDir) {
        [IO.Directory]::Delete($junctionDir, $false)
    }
    Remove-Item -LiteralPath $externalDir -Recurse -Force
    Invoke-RegisteredUninstall
    Assert-UserDataUnchanged $userDataSnapshot

    # A hash-mismatched file held open by another process cannot be moved to a
    # preservation name. That failure must abort native uninstall. After the
    # handle is released, retrying must preserve the modified file normally.
    Invoke-Setup $rc1 'locked-rc1.log' | Out-Null
    Invoke-Setup $candidate 'locked-candidate.log' | Out-Null
    $lockedFile = Join-Path $installDir 'legacy\rc1-only.pyd'
    Assert-True (Test-Path -LiteralPath $lockedFile) 'Locked historical fixture file was not present.'
    [IO.File]::WriteAllText($lockedFile, 'synthetic locked user modification', [Text.UTF8Encoding]::new($false))
    $lockedHash = (Get-FileHash -LiteralPath $lockedFile -Algorithm SHA256).Hash
    $lockedStream = [IO.File]::Open($lockedFile, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        Invoke-ExpectedUninstallAbort 'locked hash-mismatched file'
        Assert-True (Test-Path -LiteralPath $lockedFile) 'Locked file disappeared after expected abort.'
        $lockedAfterAbortHash = (Get-FileHash -LiteralPath $lockedFile -Algorithm SHA256).Hash
        Assert-True ($lockedAfterAbortHash -eq $lockedHash) 'Locked file changed after expected abort.'
    }
    finally {
        $lockedStream.Dispose()
    }
    Invoke-RegisteredUninstall -AllowInstallDirectoryRemainder
    Assert-True (Test-Path -LiteralPath $lockedFile) 'Modified file was not restored after retry.'
    $lockedAfterRetryHash = (Get-FileHash -LiteralPath $lockedFile -Algorithm SHA256).Hash
    Assert-True ($lockedAfterRetryHash -eq $lockedHash) 'Modified file content changed after retry.'
    Assert-UserDataUnchanged $userDataSnapshot
    Remove-Item -LiteralPath $installDir -Recurse -Force

    # Reinstall -> registered uninstall remains valid after all recovery paths.
    Invoke-Setup $candidate 'reinstall.log' | Out-Null
    Assert-CurrentRegistration '0.1.5-rc3-dev'
    Invoke-RegisteredUninstall
    Assert-UserDataUnchanged $userDataSnapshot
    Assert-NoProductResidualProcesses
    Write-Output 'INSTALLER_LIFECYCLE_PROBE: PASS'
}
finally {
    if ($KeepEvidence) {
        $evidenceDir = Join-Path $env:TEMP "$testName-evidence"
        if (Test-Path -LiteralPath $evidenceDir) {
            Remove-Item -LiteralPath $evidenceDir -Recurse -Force
        }
        New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
        if (Test-Path -LiteralPath $workDir) {
            Copy-Item -LiteralPath $workDir -Destination (Join-Path $evidenceDir 'work') -Recurse -Force
        }
        if (Test-Path -LiteralPath $installDir) {
            Copy-Item -LiteralPath $installDir -Destination (Join-Path $evidenceDir 'install') -Recurse -Force
        }
        if (Test-Path -LiteralPath $uninstallKey) {
            Get-ItemProperty -LiteralPath $uninstallKey | Out-File -FilePath (Join-Path $evidenceDir 'uninstall-registration.txt') -Encoding utf8
        }
        Write-Output "INSTALLER_LIFECYCLE_EVIDENCE: $evidenceDir"
    }
    if (Test-Path -LiteralPath $uninstallKey) {
        Remove-Item -LiteralPath $uninstallKey -Recurse -Force
    }
    if (Test-Path -LiteralPath $installDir) {
        $resolved = (Resolve-Path -LiteralPath $installDir).Path
        if ($resolved.StartsWith((Join-Path $installRoot 'InvoiceHubInstallerLifecycle-'))) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
    if (Test-Path -LiteralPath $workDir) {
        $resolved = (Resolve-Path -LiteralPath $workDir).Path
        if ($resolved.StartsWith((Join-Path $env:TEMP 'InvoiceHubInstallerLifecycle-'))) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}
