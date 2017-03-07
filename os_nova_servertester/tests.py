from __future__ import print_function, unicode_literals

import datetime as dt
import logging
import os
import sys
import time

import six
from keystoneauth1.session import Session
from novaclient.client import Client
from novaclient.exceptions import NotFound as NovaNotFound

from os_nova_servertester.errors import TesterError, TimeOut
from os_nova_servertester.server import shim
from os_nova_servertester.server.cloudconfig import CloudConfigGenerator

LOG = logging.getLogger(__name__)


class StopWorkFlow(RuntimeError):
    pass


class TestWorkFlow(object):
    def __init__(self):
        self.current_state = None
        self.rollback_cbs = []

    def next_state(self, nxt):
        self.current_state = nxt

    def cleanup(self):
        for func in reversed(self.rollback_cbs):
            LOG.info('%s: executing rollback: %s (%s)',
                     self.__class__.__name__, func.__name__, func.__doc__)
            func()

    def add_rollback(self, cb):
        if not callable(cb):
            raise RuntimeError('invalid callback')
        self.rollback_cbs.append(cb)

    def begin(self):
        while self.current_state:
            try:
                if not callable(self.current_state):
                    break
                func = self.current_state
                self.current_state = None
                LOG.info('%s: executing: %s (%s)', self.__class__.__name__,
                         func.__name__, func.__doc__)
                func()
                LOG.info('%s: completed: %s (%s)', self.__class__.__name__,
                         func.__name__, func.__doc__)
                if self.current_state is None:
                    self.cleanup()
                    LOG.info('%s: workflow completed', self.__class__.__name__)
                    break
            except StopWorkFlow:
                LOG.info('%s: workflow stopped', self.__class__.__name__)
                break
            except (Exception, KeyboardInterrupt):
                LOG.error('%s: workflow failed', self.__class__.__name__)
                self.cleanup()
                six.reraise(*sys.exc_info())


class SimpleTest(TestWorkFlow):
    TEST_STATUS_KEY = 'SimpleTestStatus'
    TEST_STATUS_PENDING = 'pending'
    TEST_STATUS_COMPLETE = 'complete'
    TEST_STATUS_ERROR = 'error'

    TEST_STATUS_EXITCODE_KEY = 'SimpleTestExitStatus'

    TEST_SHIM = '/run_test.sh'
    USER_TEST_SCRIPT = '/user_test.sh'
    SHELL = '/bin/bash'

    def __init__(self,
                 auth,
                 image,
                 flavor,
                 network=None,
                 az=None,
                 count=1,
                 api_timeout=60,
                 build_timeout=120,
                 callhome_timeout=300,
                 test_script=None,
                 console_logs=None,
                 shim_type='bash',
                 cloud_init_type='cloud-init',
                 **kwargs):
        super(SimpleTest, self).__init__(**kwargs)
        self.client = Client(
            '2', session=Session(auth=auth), timeout=api_timeout)
        self.image = image
        self.flavor = flavor
        self.network = network
        self.az = az
        self.count = count
        self.api_timeout = api_timeout
        self.build_timeout = build_timeout
        self.callhome_timeout = callhome_timeout
        self.test_script = test_script
        if console_logs is not None:
            self.console_logs = os.path.abspath(console_logs)
        else:
            self.console_logs = None
        self.servers = []
        self.userdata = None
        self.shim_type = shim_type
        self.cloud_init_type = cloud_init_type
        self.next_state(self.state_prepare)

    def state_prepare(self):
        '''Checks nova connectivity and validates parameters'''
        self.image = self.client.glance.find_image(self.image)
        LOG.info('Image: %s %s', self.image.id, self.image.name)
        if self.network is not None and self.network != 'auto':
            try:
                self.network = self.client.neutron.find_network(self.network)
                netname = self.network.name
            except NovaNotFound:
                self.network = self.client.networks.get(self.network)
                netname = self.network.label
            LOG.info('Network: %s %s', self.network.id, netname)
        self.flavor = self.client.flavors.find(name=self.flavor)
        LOG.info('Flavor: %s %s', self.flavor.id, self.flavor.name)
        self.next_state(self.state_prepare_userdata)

    def state_prepare_userdata(self):
        '''Prepare userdata scripts that allow server to report its state'''
        test_script_content = ''
        if self.test_script:
            with open(self.test_script) as f:
                test_script_content = f.read()

        shimscript = shim.get_script(
            self.client.client.get_token(), self.client.client.get_endpoint(),
            self.USER_TEST_SCRIPT, self.TEST_STATUS_KEY,
            self.TEST_STATUS_COMPLETE, self.TEST_STATUS_ERROR,
            self.TEST_STATUS_EXITCODE_KEY, test_script_content=test_script_content,
            script_type=self.shim_type)
        if self.cloud_init_type == 'cloud-init':
            cconfig = CloudConfigGenerator()
            # Ensure curl is installed
            cconfig.add_write_file(self.TEST_SHIM, shimscript, mode='0750')
            if self.test_script:
                cconfig.add_write_file(self.USER_TEST_SCRIPT, test_script_content, mode='0750')
            if self.shim_type == 'bash':
                cconfig.add_package('curl')
                cconfig.add_runcmd('/bin/bash', self.TEST_SHIM)
            elif self.shim_type == 'powershell':
                cconfig.add_runcmd('/usr/bin/env', 'powershell', '-File', self.TEST_SHIM)
            else:
                raise TesterError('unsupported shim type: {}'.format(self.shim_type))
            self.userdata = cconfig.generate()
        elif self.cloud_init_type == 'cloudbase-init':
            userdata = []
            userdata.append('#ps1_sysnative')
            userdata.append(shimscript)
            self.userdata = "\n".join(userdata)
        else:
            raise TesterError('Unsupported cloud-init type: {}'.format(self.cloud_init_type))
        self.next_state(self.state_create_servers)

    def state_create_servers(self):
        '''Creates test servers according to configuration'''
        servers = []

        def save_logs():
            if self.console_logs is None:
                return
            for server in servers:
                try:
                    log = server.get_console_output()
                    name = "console-output-{}.txt".format(server.id)
                    with open(os.path.join(self.console_logs, name), 'w') as f:
                        f.write(log)
                except Exception as e:
                    LOG.error("error while saving logs: %s", e)
                    pass

        def delete_servers():
            for server in servers:
                self.client.servers.delete(server)

        self.add_rollback(delete_servers)

        if self.network is not None and self.network != 'auto':
            nics = [{'net-id': self.network.id}]
        else:
            nics = self.network
        for i in range(1, self.count + 1):
            server_name = 'test-server-{}-{}'.format(self.__class__.__name__,
                                                     i)
            servers.append(
                self.client.servers.create(
                    server_name,
                    self.image,
                    self.flavor,
                    nics=nics,
                    userdata=self.userdata,
                    meta={self.TEST_STATUS_KEY: self.TEST_STATUS_PENDING},
                    availability_zone=self.az, ))
        LOG.info("Created servers: %s", ' '.join(x.id for x in servers))
        self.servers = servers[:]
        self.add_rollback(save_logs)
        self.next_state(self.state_wait_for_active)

    def state_wait_for_active(self):
        '''Wait until all servers reach ACTIVE status'''
        wait_servers = self.servers[:]
        start = dt.datetime.now()
        while wait_servers:
            if (dt.datetime.now() - start).seconds > self.build_timeout:
                raise TimeOut(
                    'Timed out while waiting for servers to transition into ACTIVE')
            server = self.client.servers.get(wait_servers.pop(0))
            if server.status != 'ACTIVE':
                wait_servers.append(server)
            time.sleep(1)
        self.next_state(self.state_wait_for_callhome_events)

    def state_wait_for_callhome_events(self):
        '''Wait until all servers have reported ok state thru nova api'''
        wait_servers = self.servers[:]
        start = dt.datetime.now()
        while wait_servers:
            if (dt.datetime.now() - start).seconds > self.callhome_timeout:
                LOG.error("Timed out while waiting for servers: %s",
                          ', '.join(x.id for x in wait_servers))
                raise TimeOut(
                    'Timed out while waiting for servers to call home')
            server = self.client.servers.get(wait_servers.pop(0))
            if server.metadata.get(
                    self.TEST_STATUS_KEY) == self.TEST_STATUS_COMPLETE:
                LOG.info("Server %s: success", server.id)

            elif server.metadata.get(
                    self.TEST_STATUS_KEY) == self.TEST_STATUS_ERROR:
                LOG.error("Server %s: error code: %s", server.id,
                          server.metadata.get(self.TEST_STATUS_EXITCODE_KEY))
                raise TesterError("Server {} reported error".format(server.id))

            else:
                wait_servers.append(server)
            time.sleep(1)
