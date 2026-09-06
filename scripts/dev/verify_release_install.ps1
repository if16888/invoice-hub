[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SetupPath,

    [Parameter(Mandatory = $true)]
    [string]$SourceExePath,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedVersion,

    [int]$StartupThresholdMs = 3000,

    [string]$EvidenceDir = "build\release-install-smoke"
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$setup = (Resolve-Path -LiteralPath $SetupPath).Path
$sourceExe = (Resolve-Path -LiteralPath $SourceExePath).Path
$evidence = [IO.Path]::GetFullPath((Join-Path $repoRoot $EvidenceDir))
$probeBase = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$probeRoot = Join-Path $probeBase "InvoiceHubReleaseSmoke-$PID"
$installDir = Join-Path $probeRoot 'install'
$runtimeDir = Join-Path $probeRoot 'runtime'
$setupLog = Join-Path $evidence 'setup.log'
$startupLog = Join-Path $evidence 'startup.log'
$summaryPath = Join-Path $evidence 'summary.txt'
$productionGuid = 'B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D'
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{$productionGuid}_is1"
$sourceSha = if ($env:SOURCE_SHA) { $env:SOURCE_SHA } else { $env:GITHUB_SHA }
$previousRuntimeDir = $env:INVOICE_HUB_RUNTIME_DIR
$installed = $false
$uninstalled = $false

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Add-Evidence {
    param([string]$Line)
    Add-Content -LiteralPath $summaryPath -Value $Line -Encoding utf8
}

function Invoke-RegisteredUninstall {
    if (-not (Test-Path -LiteralPath $installDir)) {
        return
    }

    $uninstaller = Get-ChildItem -LiteralPath $installDir -Filter 'unins*.exe' -File -ErrorAction SilentlyContinue |
        Sort-Object Name |
        Select-Object -First 1
    Assert-True ($null -ne $uninstaller) 'Installed package did not provide an Inno Setup uninstaller.'

    $process = Start-Process -FilePath $uninstaller.FullName -ArgumentList @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART'
    ) -Wait -PassThru -WindowStyle Hidden
    Assert-True ($process.ExitCode -eq 0) "Uninstall failed with exit code $($process.ExitCode)."

    for ($i = 0; $i -lt 100 -and (Test-Path -LiteralPath $installDir); $i++) {
        Start-Sleep -Milliseconds 100
    }
    Assert-True (-not (Test-Path -LiteralPath $installDir)) 'Install directory remained after uninstall.'
    Assert-True (-not (Test-Path -LiteralPath $uninstallKey)) 'Uninstall registration remained after uninstall.'
}

try {
    Assert-True ($StartupThresholdMs -gt 0) 'StartupThresholdMs must be positive.'
    Assert-True ($ExpectedVersion -match '^\d+\.\d+\.\d+(?:-(?:rc|pre)\d+)?$') 'ExpectedVersion is not a supported release version.'
    Assert-True ([IO.Path]::GetFileName($setup) -eq "InvoiceHub-$ExpectedVersion-win64-setup.exe") 'Setup filename does not match ExpectedVersion.'
    Assert-True ([IO.Path]::GetFileName($sourceExe) -eq 'InvoiceHub.exe') 'SourceExePath must identify InvoiceHub.exe.'
    Assert-True ($sourceSha -match '^[0-9a-fA-F]{40}$') 'SOURCE_SHA/GITHUB_SHA must identify the exact 40-character source commit.'

    $sourceExeHash = (Get-FileHash -LiteralPath $sourceExe -Algorithm SHA256).Hash.ToLowerInvariant()

    New-Item -ItemType Directory -Path $probeRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $evidence -Force | Out-Null
    Set-Content -LiteralPath $summaryPath -Value @(
        "SOURCE_SHA=$($sourceSha.ToLowerInvariant())",
        "EXPECTED_VERSION=$ExpectedVersion",
        "SETUP_FILE=$([IO.Path]::GetFileName($setup))",
        "SETUP_SHA256=$((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant())",
        "SOURCE_EXE_SHA256=$sourceExeHash"
    ) -Encoding utf8

    $setupArgs = @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/MERGETASKS=!desktopicon',
        "/DIR=`"$installDir`"",
        "/LOG=`"$setupLog`""
    )
    $setupProcess = Start-Process -FilePath $setup -ArgumentList $setupArgs -Wait -PassThru -WindowStyle Hidden
    Assert-True ($setupProcess.ExitCode -eq 0) "Setup failed with exit code $($setupProcess.ExitCode)."
    $installed = $true

    $exe = Join-Path $installDir 'InvoiceHub.exe'
    Assert-True (Test-Path -LiteralPath $exe) 'Installed InvoiceHub.exe is missing.'
    Assert-True (Test-Path -LiteralPath $uninstallKey) 'Installed package did not register an uninstaller.'

    $displayVersion = [string](Get-ItemPropertyValue -LiteralPath $uninstallKey -Name DisplayVersion)
    $installLocation = [string](Get-ItemPropertyValue -LiteralPath $uninstallKey -Name InstallLocation)
    Assert-True ($displayVersion -eq $ExpectedVersion) "Installed DisplayVersion is $displayVersion, expected $ExpectedVersion."
    Assert-True ($installLocation.TrimEnd('\') -ieq $installDir.TrimEnd('\')) 'Installed InstallLocation does not match the isolated audit directory.'

    $installedExeHash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-True ($installedExeHash -eq $sourceExeHash) 'Installed InvoiceHub.exe does not match the signed source executable bundled into the installer.'

    Add-Evidence 'INSTALL=PASS'
    Add-Evidence "INSTALLED_EXE_SHA256=$installedExeHash"
    Add-Evidence 'INSTALLED_EXE_MATCHES_SOURCE=PASS'

    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $env:INVOICE_HUB_RUNTIME_DIR = $runtimeDir
    $checker = Join-Path $repoRoot 'scripts\check_startup_time.py'
    $startupOutput = & python $checker $exe --threshold $StartupThresholdMs 2>&1
    $startupExit = $LASTEXITCODE
    $startupOutput | Set-Content -LiteralPath $startupLog -Encoding utf8
    $startupOutput | ForEach-Object { Write-Host $_ }
    Assert-True ($startupExit -eq 0) "Installed executable startup gate failed with exit code $startupExit."
    Add-Evidence 'STARTUP=PASS'

    Invoke-RegisteredUninstall
    $uninstalled = $true
    Add-Evidence 'UNINSTALL=PASS'
    Add-Evidence 'RELEASE_INSTALL_SMOKE=PASS'
    Write-Host 'RELEASE_INSTALL_SMOKE=PASS'
}
finally {
    if ($null -eq $previousRuntimeDir) {
        Remove-Item Env:INVOICE_HUB_RUNTIME_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:INVOICE_HUB_RUNTIME_DIR = $previousRuntimeDir
    }

    if ($installed -and -not $uninstalled -and (Test-Path -LiteralPath $installDir)) {
        try {
            Invoke-RegisteredUninstall
        }
        catch {
            Write-Warning "Cleanup uninstall failed: $($_.Exception.Message)"
        }
    }

    if (Test-Path -LiteralPath $probeRoot) {
        Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
