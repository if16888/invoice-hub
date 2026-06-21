param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]]$Path
)

$signToolPath = $env:SIGNTOOL_PATH
$certSubject = $env:CERT_SUBJECT
$timestampUrl = $env:TIMESTAMP_URL

if ([string]::IsNullOrWhiteSpace($signToolPath) -or [string]::IsNullOrWhiteSpace($certSubject)) {
    Write-Warning "Signing skipped: SIGNTOOL_PATH and CERT_SUBJECT must both be configured."
    return
}

$signTool = Get-Item -LiteralPath $signToolPath -ErrorAction Stop

foreach ($target in $Path) {
    $resolvedTarget = Get-Item -LiteralPath $target -ErrorAction Stop
    $args = @("sign", "/fd", "SHA256", "/n", $certSubject)
    if ([string]::IsNullOrWhiteSpace($timestampUrl)) {
        Write-Warning "Signing $($resolvedTarget.FullName) without timestamp because TIMESTAMP_URL is not configured."
    }
    else {
        $args += @("/tr", $timestampUrl, "/td", "SHA256")
    }
    $args += $resolvedTarget.FullName

    & $signTool.FullName @args
    if ($LASTEXITCODE -ne 0) {
        throw "signtool.exe failed with exit code $LASTEXITCODE for $($resolvedTarget.FullName)"
    }
}
