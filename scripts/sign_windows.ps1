param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]]$Path,

    [switch]$RequireSignature
)

$signToolPath = $env:SIGNTOOL_PATH
$certSubject = $env:CERT_SUBJECT
$timestampUrl = $env:TIMESTAMP_URL

function Assert-AuthenticodeSignature {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$Target,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedSubject,

        [switch]$RequireTimestamp
    )

    $signature = Get-AuthenticodeSignature -FilePath $Target.FullName
    if ([string]$signature.Status -ne "Valid") {
        throw "Authenticode verification failed for $($Target.Name): status=$($signature.Status)."
    }
    if ($null -eq $signature.SignerCertificate) {
        throw "Authenticode verification failed for $($Target.Name): signer certificate is missing."
    }

    $actualSubject = [string]$signature.SignerCertificate.Subject
    if ($actualSubject.IndexOf($ExpectedSubject, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Authenticode verification failed for $($Target.Name): signer subject does not match the configured publisher."
    }

    if ($RequireTimestamp -and $null -eq $signature.TimeStamperCertificate) {
        throw "Authenticode verification failed for $($Target.Name): trusted timestamp is missing."
    }

    Write-Host "Authenticode signature valid: $($Target.Name)"
    Write-Host "Signer subject: $actualSubject"
    if ($null -ne $signature.TimeStamperCertificate) {
        Write-Host "Timestamp signer: $($signature.TimeStamperCertificate.Subject)"
    }
}

$missingSigningConfig = @()
if ([string]::IsNullOrWhiteSpace($signToolPath)) {
    $missingSigningConfig += "SIGNTOOL_PATH"
}
if ([string]::IsNullOrWhiteSpace($certSubject)) {
    $missingSigningConfig += "CERT_SUBJECT"
}

if ($missingSigningConfig.Count -gt 0) {
    $missingText = $missingSigningConfig -join ", "
    if ($RequireSignature) {
        throw "Authenticode signing is required for this release, but signing configuration is missing: $missingText."
    }
    Write-Warning "Signing skipped: missing $missingText. Prerelease/audit artifacts may remain unsigned."
    return
}

if ($RequireSignature -and [string]::IsNullOrWhiteSpace($timestampUrl)) {
    throw "Authenticode signing is required for this release, but TIMESTAMP_URL is not configured."
}

$signTool = Get-Item -LiteralPath $signToolPath -ErrorAction Stop

foreach ($target in $Path) {
    $resolvedTarget = Get-Item -LiteralPath $target -ErrorAction Stop
    $args = @("sign", "/fd", "SHA256", "/n", $certSubject)
    if ([string]::IsNullOrWhiteSpace($timestampUrl)) {
        Write-Warning "Signing $($resolvedTarget.Name) without timestamp because TIMESTAMP_URL is not configured."
    }
    else {
        $args += @("/tr", $timestampUrl, "/td", "SHA256")
    }
    $args += $resolvedTarget.FullName

    & $signTool.FullName @args
    if ($LASTEXITCODE -ne 0) {
        throw "signtool.exe failed with exit code $LASTEXITCODE for $($resolvedTarget.Name)."
    }

    Assert-AuthenticodeSignature \
        -Target $resolvedTarget \
        -ExpectedSubject $certSubject \
        -RequireTimestamp:$RequireSignature
}
