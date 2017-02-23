from __future__ import print_function, unicode_literals
from string import Template

TPL = Template('''
#!/bin/bash

set -e
SCRIPT=${USER_TEST_SCRIPT}
OS_AUTH_TOKEN=${OS_AUTH_TOKEN}
NOVA_ENDPOINT=${NOVA_ENDPOINT}
METADATA_KEY=${METADATA_KEY}
METADATA_VALUE_OK=${METADATA_VALUE_OK}
METADATA_VALUE_ERR=${METADATA_VALUE_ERR}
METADATA_EXITCODE_KEY=${METADATA_EXITCODE_KEY}

INSTANCE_ID=$(cat /var/lib/cloud/data/instance-id)

function set_metadata() {
	key=$1
	val=$2
	echo "Reporting: $key -> $val"
	/usr/bin/curl -f -X POST \
		$NOVA_ENDPOINT/servers/$INSTANCE_ID/metadata \
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
		set_metadata $METADATA_KEY $METADATA_VALUE_ERR
		set_metadata $METADATA_EXITCODE_KEY $code
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


def get_script(os_auth_token, nova_endpoint, user_test_script, metadata_key,
               metadata_value_ok, metadata_value_err, metadata_exitcode_key):
    return TPL.safe_substitute(
        OS_AUTH_TOKEN=os_auth_token,
        NOVA_ENDPOINT=nova_endpoint,
        USER_TEST_SCRIPT=user_test_script,
        METADATA_KEY=metadata_key,
        METADATA_VALUE_OK=metadata_value_ok,
        METADATA_VALUE_ERR=metadata_value_err,
        METADATA_EXITCODE_KEY=metadata_exitcode_key)
