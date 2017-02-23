from __future__ import print_function, unicode_literals

import argparse
import logging
import sys

import keystoneauth1.loading as ksloading

from os_nova_servertester.log import setup_logging, set_debug
from os_nova_servertester.errors import TesterError
from os_nova_servertester.tests import SimpleTest

LOG = logging.getLogger('tester')


def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        description='Tool to test Nova server provisioning')
    parser.add_argument(
        '--image-id', required=True, metavar='UUID', help='Image to test with')
    parser.add_argument(
        '--flavor',
        required=True,
        metavar='NAME_OR_UUID',
        help='Flavor name or uuid to test with')
    parser.add_argument(
        '--network',
        metavar='NAME_OR_UUID',
        help='Network name or uuid to test with')
    parser.add_argument(
        '--test-script',
        metavar='FILE',
        help='Optional test script to deploy to server(s). Must return exit status 0 for ok')
    parser.add_argument(
        '--availability-zone', metavar='NAME', help='Availability zone to use')
    parser.add_argument(
        '--count',
        metavar='NUM',
        type=int,
        default=1,
        help='How many servers to provision for the test')

    ksloading.register_auth_argparse_arguments(parser, sys.argv)
    ksloading.session.register_argparse_arguments(parser)

    args = parser.parse_args()

    try:
        auth = ksloading.cli.load_from_argparse_arguments(args)
        SimpleTest(
            auth,
            args.image_id,
            args.flavor,
            count=args.count,
            network=args.network,
            az=args.availability_zone,
            test_script=args.test_script).begin()
    except TesterError as e:
        print('ERROR: {}'.format(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('User interrupt')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
