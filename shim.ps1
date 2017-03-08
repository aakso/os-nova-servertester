#ps1_sysnative

$ErrorActionPreference = "Stop"
filter timestamp {
    "$(Get-Date -format o) $_"
}

$global:http_timeout = 10
$testscript = "ZXhpdCAxCg=="

$env:os_auth_token = "a6d787c2fbc14e0784a2cccebbedcce8"
$env:nova_endpoint = "https://compute.fi-1.nebulacloud.fi:8774/v2/d8c2269383a941bf8417f606dcef0f52"
$env:metadata_key = "SimpleTestStatus"
$env:metadata_value_ok = "complete"
$env:metadata_value_err = "error"
$env:metadata_exitcode_key = "SimpleTestExitStatus"

#$env:instance_id = (Invoke-RestMethod -Uri http://169.254.169.254/openstack/latest/meta_data.json -TimeoutSec $global:http_timeout).uuid
$env:instance_id = "8c5a0e81-1cf4-4221-9336-2ef1a07f288f"

function SetMetadata($key, $val) {
    $url = "$($env:nova_endpoint)/servers/$($env:instance_id)/metadata"
    Write-Output "Reporting: $key -> $val to $url" | timestamp
    $headers = @{
        'X-Auth-Token' = $env:os_auth_token
        'Accept' = 'application/json'
    }
    $body = @{
        metadata = @{
            $key = $val.toString()
        }
    } | ConvertTo-Json
    Invoke-RestMethod -Method POST -Verbose -Uri $url -ContentType 'application/json' -Body $body -Headers $headers -TimeoutSec $global:http_timeout
}

function Report($code) {
    if($code -eq 0) {
        SetMetadata $env:metadata_key $env:metadata_value_ok
    } else {
        SetMetadata $env:metadata_exitcode_key $code
        SetMetadata $env:metadata_key $env:metadata_value_err
    }
}

if($testscript -ne "") {
    $script = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($testscript))
    Write-Output("Executing user test script") | timestamp
    Write-Output $script | powershell -noprofile -
    $code = $LASTEXITCODE
    if($code -ne 0) {
        Report $code
        [System.Environment]::Exit(0)
    }
}
Report 0