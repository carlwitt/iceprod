"""
Test script for config module
"""

from __future__ import absolute_import, division, print_function

from tests.util import unittest_reporter, glob_tests, messaging_mock

import logging
logger = logging.getLogger('modules_config_test')

import os
import sys
import time
import random
import signal
from datetime import datetime,timedelta
import shutil
import tempfile
import json
import unittest

from flexmock import flexmock


import iceprod.server
import iceprod.core.logger
from iceprod.server import module
from iceprod.server import basic_config
from iceprod.server.modules.config import config

class modules_config_test(unittest.TestCase):
    def setUp(self):
        super(modules_config_test,self).setUp()
        self.test_dir = tempfile.mkdtemp(dir=os.getcwd())

        def sig(*args):
            sig.args = args
        flexmock(signal).should_receive('signal').replace_with(sig)
        def basicConfig(*args,**kwargs):
            pass
        flexmock(logging).should_receive('basicConfig').replace_with(basicConfig)
        def setLogger(*args,**kwargs):
            pass
        flexmock(iceprod.core.logger).should_receive('setlogger').replace_with(setLogger)
        def removestdout(*args,**kwargs):
            pass
        flexmock(iceprod.core.logger).should_receive('removestdout').replace_with(removestdout)

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        super(modules_config_test,self).tearDown()

    @unittest_reporter
    def test_01_init(self):
        """Test init"""
        # mock some functions so we don't go too far
        def start():
            start.called = True
        flexmock(config).should_receive('start').replace_with(start)
        start.called = False

        cfg_file = os.path.join(self.test_dir,'cfg.json')
        cfg = basic_config.BasicConfig()
        cfg.messaging_url = 'localhost'
        q = config(cfg,filename=cfg_file)
        if not q:
            raise Exception('did not return config object')
        if start.called != True:
            raise Exception('init did not call start')

        q.messaging = messaging_mock()

        new_cfg = {'new':1}
        q.messaging.BROADCAST.reload(cfg=new_cfg)
        if not q.messaging.called:
            raise Exception('init did not call messaging')
        if q.messaging.called[0] != ['BROADCAST','reload',tuple(),{'cfg':new_cfg}]:
            raise Exception('init did not call correct message')

    @unittest_reporter
    def test_02_save(self):
        """Test save"""
        # mock some functions so we don't go too far
        def start():
            start.called = True
        flexmock(config).should_receive('start').replace_with(start)
        start.called = False

        cfg_file = os.path.join(self.test_dir,'cfg.json')
        cfg = basic_config.BasicConfig()
        cfg.messaging_url = 'localhost'
        q = config(cfg,filename=cfg_file)
        q.config.filename = os.path.join(self.test_dir,'test.json')
        q.config['test'] = 1
        q.messaging = messaging_mock()

        def cb(ret=None):
            cb.ret = ret

        cb.ret = None
        q.service_class.get(callback=cb)
        if 'test' not in cb.ret or cb.ret['test'] != 1:
            raise Exception('get() did not return config')

        cb.ret = None
        q.service_class.get(key='test',callback=cb)
        if cb.ret != 1:
            raise Exception('get(key="test") did not return 1')

        cb.ret = None
        q.service_class.set(key='test',value=2,callback=cb)
        if q.config['test'] != 2:
            raise Exception('set(key="test",2) did not set to 2')

        txt = json.load(open(q.config.filename))
        if 'test' not in txt or txt['test'] != 2:
            raise Exception('set() did not save to file')

        cb.ret = None
        q.service_class.delete(key='test',callback=cb)
        if 'test' in q.config:
            raise Exception('delete(key="test") did not delete')

        txt = json.load(open(q.config.filename))
        if 'test' in txt:
            raise Exception('delete() did not save to file')


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    alltests = glob_tests(loader.getTestCaseNames(modules_config_test))
    suite.addTests(loader.loadTestsFromNames(alltests,modules_config_test))
    return suite