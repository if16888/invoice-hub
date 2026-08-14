[CmdletBinding()]
param(
    [string]$IsccPath = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    [switch]$KeepEvidence
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$productionGuid = 'B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D'
$testGuid = ([guid]::NewGuid().ToString()).ToUpperInvariant()
$testName = "InvoiceHubInstallerLifecycle-$PID"
$installDir = Join-Path $env:LOCALAPPDATA $testName
$workDir = Join-Path $env:TEMP $testName
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

function Invoke-RegisteredUninstall {
    $command = (Get-ItemPropertyValue -LiteralPath $uninstallKey -Name UninstallString).Trim('"')
    Assert-True (Test-Path -LiteralPath $command) 'Registered uninstaller does not exist.'
    $process = Start-Process -FilePath $command -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
    ) -Wait -PassThru -WindowStyle Hidden
    Assert-True ($process.ExitCode -eq 0) "Uninstall failed with exit code $($process.ExitCode)."
    for ($i = 0; $i -lt 50 -and (Test-Path -LiteralPath $installDir); $i++) {
        Start-Sleep -Milliseconds 100
    }
    Assert-True (-not (Test-Path -LiteralPath $uninstallKey)) 'Uninstall registration remained.'
    Assert-True (-not (Test-Path -LiteralPath $installDir)) 'Install directory remained.'
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

function Assert-CurrentRegistration {
    param([string]$Version)
    Assert-True (Test-Path -LiteralPath $uninstallKey) 'Uninstall registration is missing.'
    $displayVersion = Get-ItemPropertyValue -LiteralPath $uninstallKey -Name DisplayVersion
    $uninstallString = Get-ItemPropertyValue -LiteralPath $uninstallKey -Name UninstallString
    $uninstaller = $uninstallString.Trim('"')
    Assert-True ($displayVersion -eq $Version) "Expected version $Version, got $displayVersion."
    Assert-True (Test-Path -LiteralPath $uninstaller) 'Registered uninstaller is missing.'
    Assert-True (Test-Path -LiteralPath ([IO.Path]::ChangeExtension($uninstaller, '.dat'))) 'Registered uninstall log is missing.'
}

function Compile-Installer {
    param([string]$ScriptPath, [string]$Version)
    $compilerOutput = & $IsccPath $ScriptPath "/DAppVersion=$Version" "/DDefaultInstallDir=$installDir" "/DSourceDir=$workDir\payload" "/DOutputDir=$workDir"
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed for version $Version." }
    Write-Verbose ($compilerOutput -join [Environment]::NewLine)
    return Join-Path $workDir "InvoiceHub-$Version-win64-setup.exe"
}

try {
    Assert-True (Test-Path -LiteralPath $IsccPath) "ISCC.exe was not found at $IsccPath."
    Assert-True ($installDir.StartsWith((Join-Path $env:LOCALAPPDATA 'InvoiceHubInstallerLifecycle-'))) 'Unsafe test install path.'
    Assert-True ($workDir.StartsWith((Join-Path $env:TEMP 'InvoiceHubInstallerLifecycle-'))) 'Unsafe test work path.'

    New-Item -ItemType Directory -Path (Join-Path $workDir 'payload') -Force | Out-Null
    New-UserDataFixture
    $userDataSnapshot = Get-UserDataSnapshot
    Assert-True ($userDataSnapshot.Length -gt 0) 'User data fixture was not created.'

    [IO.File]::WriteAllText(
        (Join-Path $workDir 'payload\InvoiceHub.exe'),
        'synthetic installer lifecycle payload',
        [Text.UTF8Encoding]::new($false)
    )

    $sourcePath = Join-Path $repoRoot 'packaging\invoice_hub_windows.iss'
    $source = [IO.File]::ReadAllText($sourcePath, [Text.Encoding]::UTF8)
    Assert-True $source.Contains('RemoveBrokenUninstallRegistration') 'Stale-registration removal code is missing.'
    Assert-True (-not $source.Contains('RegWriteStringValue')) 'Installer must not rewrite uninstall registration.'
    Assert-True (-not $source.Contains('FindAlternateUninstaller')) 'Installer must not manually select an alternate log.'
    $testSource = $source.Replace($productionGuid, $testGuid)
    Assert-True ($testSource -ne $source) 'Test AppId replacement failed.'
    $currentScript = Join-Path $workDir 'current.iss'
    [IO.File]::WriteAllText($currentScript, $testSource, [Text.UTF8Encoding]::new($false))

    $codeIndex = $testSource.IndexOf('[Code]')
    Assert-True ($codeIndex -gt 0) 'The installer repair code section was not found.'
    $oldScript = Join-Path $workDir 'old.iss'
    [IO.File]::WriteAllText(
        $oldScript,
        $testSource.Substring(0, $codeIndex),
        [Text.UTF8Encoding]::new($false)
    )

    $rc1 = Compile-Installer $oldScript '0.1.5-rc1'
    $rc2 = Compile-Installer $oldScript '0.1.5-rc2'
    $candidate = Compile-Installer $currentScript '0.1.5-rc3-dev'

    # Fresh install -> uninstall.
    Invoke-Setup $candidate 'fresh.log' | Out-Null
    Assert-CurrentRegistration '0.1.5-rc3-dev'
    Invoke-RegisteredUninstall
    Assert-UserDataUnchanged $userDataSnapshot

    # Historical RC1 -> candidate upgrade with an intact native uninstall log.
    Invoke-Setup $rc1 'historical-rc1-valid.log' | Out-Null
    Invoke-Setup $candidate 'historical-rc1-upgrade.log' | Out-Null
    Assert-CurrentRegistration '0.1.5-rc3-dev'
    Invoke-RegisteredUninstall
    Assert-UserDataUnchanged $userDataSnapshot

    # Reproduce the historical RC1/RC2 field state: RC1 left the registered
    # unins000 entry, RC2 left a valid unins001 pair, but the ARP entry still
    # points at unins000 without its matching .dat.
    Invoke-Setup $rc1 'historical-rc1-damaged.log' | Out-Null
    Assert-CurrentRegistration '0.1.5-rc1'
    $brokenDat = Join-Path $installDir 'unins000.dat'
    Remove-Item -LiteralPath $brokenDat -Force
    Invoke-Setup $rc2 'historical-rc2-damaged.log' | Out-Null
    $brokenExe = Join-Path $installDir 'unins000.exe'
    $alternateExe = Join-Path $installDir 'unins001.exe'
    $alternateDat = Join-Path $installDir 'unins001.dat'
    Assert-True (Test-Path -LiteralPath $brokenExe) 'Historical RC2 fixture lost unins000.exe.'
    Assert-True (Test-Path -LiteralPath $alternateExe) 'Historical RC2 fixture did not create unins001.exe.'
    Assert-True (Test-Path -LiteralPath $alternateDat) 'Historical RC2 fixture did not create unins001.dat.'

    if (Test-Path -LiteralPath $brokenDat) {
        Remove-Item -LiteralPath $brokenDat -Force
    }
    Set-ItemProperty -LiteralPath $uninstallKey -Name DisplayVersion -Value '0.1.5-rc1'
    Set-ItemProperty -LiteralPath $uninstallKey -Name UninstallString -Value ('"' + $brokenExe + '"')
    Set-ItemProperty -LiteralPath $uninstallKey -Name QuietUninstallString -Value ('"' + $brokenExe + '" /SILENT')

    # The candidate must leave the valid alternate pair untouched while native
    # Inno chooses the new/appended log.
    $repairLog = Invoke-Setup $candidate 'historical-rc2-repair.log'
    Assert-CurrentRegistration '0.1.5-rc3-dev'
    Assert-True (Test-Path -LiteralPath $alternateExe) 'Valid alternate uninstaller was removed.'
    Assert-True (Test-Path -LiteralPath $alternateDat) 'Valid alternate uninstall log was removed.'
    $repairText = [IO.File]::ReadAllText($repairLog, [Text.Encoding]::UTF8)
    Assert-True ($repairText.Contains('Removed the damaged Invoice Hub uninstall registration before native setup.')) 'Stale ARP removal was not logged.'
    Invoke-RegisteredUninstall
    Assert-UserDataUnchanged $userDataSnapshot

    # Reinstall candidate -> registered uninstall, with user data still intact.
    Invoke-Setup $candidate 'reinstall.log' | Out-Null
    Assert-CurrentRegistration '0.1.5-rc3-dev'
    Invoke-RegisteredUninstall
    Assert-UserDataUnchanged $userDataSnapshot

    $residual = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -match '^(InvoiceHub|unins[0-9]+)$'
    })
    Assert-True ($residual.Count -eq 0) 'Installer lifecycle probe left a residual process.'
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
        if ($resolved.StartsWith((Join-Path $env:LOCALAPPDATA 'InvoiceHubInstallerLifecycle-'))) {
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
