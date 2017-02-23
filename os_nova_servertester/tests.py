from __future__ import print_function, unicode_literals

import logging
import six
import sys
import time

from novaclient.client import Client
from keystoneauth1.session import Session
from uuid import UUID
import datetime as dt

from os_nova_servertester.errors import TimeOut, TesterError
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
                    #self.cleanup()
                    LOG.info('%s: workflow completed', self.__class__.__name__)
                    break
            except StopWorkFlow:
                LOG.info('%s: workflow stopped', self.__class__.__name__)
                break
            except Exception, KeyboardInterrupt:
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

        self.servers = []
        self.userdata = None
        self.next_state(self.state_prepare)

    def state_prepare(self):
        '''Checks nova connectivity and validates parameters'''
        self.image = self.client.glance.find_image(self.image)
        LOG.info('Image: %s %s', self.image.id, self.image.name)
        if self.network is not None and self.network != 'auto':
            self.network = self.client.neutron.find_network(self.network)
            LOG.info('Network: %s %s', self.network.id, self.network.name)
        self.flavor = self.client.flavors.find(name=self.flavor)
        LOG.info('Flavor: %s %s', self.flavor.id, self.flavor.name)
        self.next_state(self.state_prepare_userdata)

    def state_prepare_userdata(self):
        '''Prepare userdata scripts that allow server to report its state'''
        shimscript = shim.get_script(
            self.client.client.get_token(), self.client.client.get_endpoint(),
            self.USER_TEST_SCRIPT, self.TEST_STATUS_KEY,
            self.TEST_STATUS_COMPLETE, self.TEST_STATUS_ERROR,
            self.TEST_STATUS_EXITCODE_KEY)
        cconfig = CloudConfigGenerator()
        cconfig.add_write_file(self.TEST_SHIM, shimscript, mode='0750')
        if self.test_script:
            with open(self.test_script) as f:
                cconfig.add_write_file(self.USER_TEST_SCRIPT, f, mode='0750')
        cconfig.add_runcmd('/bin/bash', self.TEST_SHIM)
        self.userdata = cconfig.generate()
        self.next_state(self.state_create_servers)

    def state_create_servers(self):
        '''Creates test servers according to configuration'''
        servers = []
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
        LOG.info("Created servers: %s", servers)
        self.servers = servers[:]

        def delete_servers():
            for server in servers:
                self.client.servers.delete(server)

        self.add_rollback(delete_servers)
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
                raise TesterError("Server %s reported error", server.id)

            else:
                wait_servers.append(server)
            time.sleep(1)