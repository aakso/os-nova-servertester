from __future__ import print_function, unicode_literals

import argparse
import logging
import os
import signal
import sys

import keystoneauth1.loading as ksloading

from os_nova_servertester.errors import TesterError
from os_nova_servertester.log import set_debug, setup_logging
from os_nova_servertester.tests import SimpleTest

LOG = logging.getLogger('tester')


# Treat SIGTERM as interrupt so we can abort this tool 
# cleanly for example in Jenkins
def sigterm(s, f):
    raise KeyboardInterrupt('SIGTERM')


signal.signal(signal.SIGTERM, sigterm)


def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        description='Tool to test Nova server provisioning')
    parser.add_argument(
        '--image-id',
        metavar='UUID',
        default=os.environ.get('TEST_IMAGE_ID'),
        help='Image to test with')
    parser.add_argument(
        '--flavor',
        metavar='NAME_OR_UUID',
        default=os.environ.get('TEST_FLAVOR'),
        help='Flavor name or uuid to test with')
    parser.add_argument(
        '--network',
        metavar='NAME_OR_UUID',
        default=os.environ.get('TEST_NETWORK'),
        help='Network name or uuid to test with')
    parser.add_argument(
        '--test-script',
        metavar='FILE',
        default=os.environ.get('TEST_TEST_SCRIPT'),
        help='Optional test script to deploy to server(s). Must return exit status 0 for ok. ' + \
             'Must be powershell script if using cloudbase-init')
    parser.add_argument(
        '--console-logs',
        metavar='PATH',
        default=os.environ.get('TEST_CONSOLE_LOGS'),
        help='Save console logs to this dir')
    parser.add_argument(
        '--availability-zone',
        metavar='NAME',
        default=os.environ.get('TEST_AVAILABILITY_ZONE'),
        help='Availability zone to use')
    parser.add_argument(
        '--count',
        metavar='NUM',
        type=int,
        default=os.environ.get('TEST_COUNT', 1),
        help='How many servers to provision for the test')
    parser.add_argument(
        '--callhome-timeout',
        metavar='secs',
        type=int,
        default=os.environ.get('TEST_CALLHOME_TIMEOUT', 300),
        help='how long to wait for server(s) to report test completed')
    parser.add_argument(
        '--build-timeout',
        metavar='secs',
        type=int,
        default=os.environ.get('TEST_BUILD_TIMEOUT', 300),
        help='how long to wait for server(s) to start')
    parser.add_argument(
        '--shim-type',
        choices=['bash', 'powershell'],
        default=os.environ.get('TEST_SHIM_SCRIPT_TYPE', 'bash'),
        help='What style of shim script to use. You should use powershell if your os is Windows')
    parser.add_argument(
        '--cloud-init-type',
        choices=['cloud-init', 'cloudbase-init'],
        default=os.environ.get('TEST_CLOUD_INIT_TYPE', 'cloud-init'),
        help='What style cloud-init to use')

    ksloading.register_auth_argparse_arguments(parser, sys.argv)
    ksloading.session.register_argparse_arguments(parser)

    args = parser.parse_args()

    try:
        if args.flavor is None or args.image_id is None:
            raise TesterError('flavor and image id are required')

        auth = ksloading.cli.load_from_argparse_arguments(args)
        SimpleTest(
            auth,
            args.image_id,
            args.flavor,
            count=args.count,
            network=args.network,
            az=args.availability_zone,
            test_script=args.test_script,
            console_logs=args.console_logs,
            build_timeout=args.build_timeout,
            callhome_timeout=args.callhome_timeout,
            shim_type=args.shim_type,
            cloud_init_type=args.cloud_init_type).begin()
    except TesterError as e:
        print('ERROR: {}'.format(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('User interrupt')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
