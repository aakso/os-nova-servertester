from __future__ import print_function, unicode_literals

import base64
from string import Template

from os_nova_servertester.errors import TesterError


TPL_BASH = Template('''
set -e
SCRIPT=${USER_TEST_SCRIPT}
OS_AUTH_TOKEN=${OS_AUTH_TOKEN}
NOVA_ENDPOINT=${NOVA_ENDPOINT}
METADATA_KEY=${METADATA_KEY}
METADATA_VALUE_OK=${METADATA_VALUE_OK}
METADATA_VALUE_ERR=${METADATA_VALUE_ERR}
METADATA_EXITCODE_KEY=${METADATA_EXITCODE_KEY}

INSTANCE_ID=$(curl -s http://169.254.169.254/openstack/latest/meta_data.json | $(which python || which python3) -c 'import sys,json; sys.stdout.write(json.load(sys.stdin)["uuid"])')

function set_metadata() {
	key=$1
	val=$2
	url="$NOVA_ENDPOINT/servers/$INSTANCE_ID/metadata"
	echo "Reporting: $key -> $val to $url"
	/usr/bin/curl -s -f -X POST \
		$url \
		-H "User-Agent: os-nova-servertester" \
		-H "Content-Type: application/json" \
		-H "Accept: application/json" \
		-H "X-Auth-Token: $OS_AUTH_TOKEN" \
		-d "{\\"metadata\\": {\\"$key\\": \\"$val\\"}}"
}

function report() {
	code=$1
	if [ $code -eq 0 ]; then
		set_metadata $METADATA_KEY $METADATA_VALUE_OK
	else
		set_metadata $METADATA_EXITCODE_KEY $code
		set_metadata $METADATA_KEY $METADATA_VALUE_ERR
	fi
}

if [ -f $SCRIPT ]; then
	$SCRIPT || code=$?
	if [ ! $code -eq 0 ]; then
		report $code
		exit 0
	fi
fi
report 0
''')

TPL_PS = Template('''
filter timestamp {
    "$(Get-Date -format o) $_"
}

$global:http_timeout = 10
$global:output_log = "c:\output.log"
$global:serial_device = "COM1"

$testscript = "${test_script_content}"

$env:os_auth_token = "${OS_AUTH_TOKEN}"
$env:nova_endpoint = "${NOVA_ENDPOINT}"
$env:metadata_key = "${METADATA_KEY}"
$env:metadata_value_ok = "${METADATA_VALUE_OK}"
$env:metadata_value_err = "${METADATA_VALUE_ERR}"
$env:metadata_exitcode_key = "${METADATA_EXITCODE_KEY}"

$env:instance_id = (Invoke-RestMethod -Uri http://169.254.169.254/openstack/latest/meta_data.json -TimeoutSec $global:http_timeout).uuid

function SetMetadata($key, $val) {
    $url = "$($env:nova_endpoint)/servers/$($env:instance_id)/metadata"
    Write-Output "Reporting: $key -> $val to $url" | timestamp
    $headers = @{
        'X-Auth-Token' = $env:os_auth_token
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

Start-Transcript $global:output_log
try {
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
} catch {
    $ErrorMessage = $_.Exception.Message
    $FailedItem = $_.Exception.ItemName
    Write-Output $_.Exception | Format-List -force
} Finally {
    Stop-Transcript
    if ($global:serial_device -in [System.IO.Ports.SerialPort]::GetPortNames()) {
        $port = new-Object System.IO.Ports.SerialPort $global:serial_device,9600,None,8,one
        $port.Open()
        $port.Write([IO.File]::ReadAllText($global:output_log))
        $port.Close()
    }
}''')


def get_script(os_auth_token,
               nova_endpoint,
               user_test_script,
               metadata_key,
               metadata_value_ok,
               metadata_value_err,
               metadata_exitcode_key,
               test_script_content='',
               script_type='bash'):

    if script_type == 'bash':
        tpl = TPL_BASH
    elif script_type == 'powershell':
        tpl = TPL_PS
    else:
        raise TesterError('invalid template type: {}'.format(script_type))

    return tpl.safe_substitute(
        OS_AUTH_TOKEN=os_auth_token,
        NOVA_ENDPOINT=nova_endpoint,
        USER_TEST_SCRIPT=user_test_script,
        METADATA_KEY=metadata_key,
        METADATA_VALUE_OK=metadata_value_ok,
        METADATA_VALUE_ERR=metadata_value_err,
        METADATA_EXITCODE_KEY=metadata_exitcode_key,
        test_script_content=base64.b64encode(test_script_content))
