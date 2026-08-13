[CmdletBinding()]
param(
    [string]$IsccPath = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$productionGuid = 'B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D'
$testGuid = ([guid]::NewGuid().ToString()).ToUpperInvariant()
$testName = "InvoiceHubInstallerLifecycle-$PID"
$installDir = Join-Path $env:LOCALAPPDATA $testName
$workDir = Join-Path $env:TEMP $testName
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{$testGuid}_is1"

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
    [IO.File]::WriteAllText(
        (Join-Path $workDir 'payload\InvoiceHub.exe'),
        'synthetic installer lifecycle payload',
        [Text.UTF8Encoding]::new($false)
    )

    $sourcePath = Join-Path $repoRoot 'packaging\invoice_hub_windows.iss'
    $source = [IO.File]::ReadAllText($sourcePath, [Text.Encoding]::UTF8)
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

    $old1 = Compile-Installer $oldScript '1.0'
    $old2 = Compile-Installer $oldScript '2.0'
    $current = Compile-Installer $currentScript '3.0'

    # Fresh install -> uninstall.
    Invoke-Setup $current 'fresh.log' | Out-Null
    Assert-CurrentRegistration '3.0'
    Invoke-RegisteredUninstall

    # Valid old install -> current upgrade -> uninstall.
    Invoke-Setup $old1 'valid-old.log' | Out-Null
    Invoke-Setup $current 'valid-upgrade.log' | Out-Null
    Assert-CurrentRegistration '3.0'
    Invoke-RegisteredUninstall

    # A later valid old install follows the same native append path.
    Invoke-Setup $old2 'valid-old2.log' | Out-Null
    Invoke-Setup $current 'valid-upgrade2.log' | Out-Null
    Assert-CurrentRegistration '3.0'
    Invoke-RegisteredUninstall

    # A broken registration without any alternate log creates one clean current
    # log, then removes the stale executable after installation.
    Invoke-Setup $old1 'broken-only-old.log' | Out-Null
    $brokenOnlyDat = Join-Path $installDir 'unins000.dat'
    $brokenOnlyExe = Join-Path $installDir 'unins000.exe'
    Remove-Item -LiteralPath $brokenOnlyDat -Force
    $brokenOnlyLog = Invoke-Setup $current 'broken-only-repair.log'
    Assert-CurrentRegistration '3.0'
    Assert-True (-not (Test-Path -LiteralPath $brokenOnlyExe)) 'Broken uninstaller without an alternate remained.'
    $brokenOnlyText = [IO.File]::ReadAllText($brokenOnlyLog, [Text.Encoding]::UTF8)
    Assert-True ($brokenOnlyText.Contains('No alternate Inno uninstall log candidate was found.')) 'Missing-alternate repair path was not used.'
    Invoke-RegisteredUninstall

    # Reproduce the RC2 state: the registered unins000 log is missing, a valid
    # alternate unins001 pair exists, and the registry still targets unins000.
    Invoke-Setup $old1 'damaged-old1.log' | Out-Null
    $brokenDat = Join-Path $installDir 'unins000.dat'
    Assert-True (Test-Path -LiteralPath $brokenDat) 'Expected old uninstall log is missing.'
    Remove-Item -LiteralPath $brokenDat -Force
    Invoke-Setup $old2 'damaged-old2.log' | Out-Null
    $brokenExe = Join-Path $installDir 'unins000.exe'
    Assert-True (Test-Path -LiteralPath (Join-Path $installDir 'unins001.dat')) 'Alternate uninstall log was not created.'
    Set-ItemProperty -LiteralPath $uninstallKey -Name DisplayVersion -Value '1.0'
    Set-ItemProperty -LiteralPath $uninstallKey -Name UninstallString -Value ('"' + $brokenExe + '"')
    Set-ItemProperty -LiteralPath $uninstallKey -Name QuietUninstallString -Value ('"' + $brokenExe + '" /SILENT')

    $repairLog = Invoke-Setup $current 'damaged-repair.log'
    Assert-CurrentRegistration '3.0'
    Assert-True (-not (Test-Path -LiteralPath $brokenExe)) 'Broken registered uninstaller remained.'
    $repairText = [IO.File]::ReadAllText($repairLog, [Text.Encoding]::UTF8)
    Assert-True ($repairText.Contains('Repaired the damaged Invoice Hub uninstall registration.')) 'Repair was not logged.'
    Assert-True ($repairText.Contains('Will append to existing uninstall log:')) 'Valid alternate log was not reused.'
    Invoke-RegisteredUninstall

    # Reinstall current -> uninstall.
    Invoke-Setup $current 'reinstall.log' | Out-Null
    Assert-CurrentRegistration '3.0'
    Invoke-RegisteredUninstall

    $residual = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -match '^(InvoiceHub|unins[0-9]+)$'
    })
    Assert-True ($residual.Count -eq 0) 'Installer lifecycle probe left a residual process.'
    Write-Output 'INSTALLER_LIFECYCLE_PROBE: PASS'
}
finally {
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
