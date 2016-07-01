"""
Test script for master_communication
"""

from __future__ import absolute_import, division, print_function

from tests.util import unittest_reporter, glob_tests

import logging
logger = logging.getLogger('master_communication_test')

import os, sys, time
import shutil
import tempfile
import random
import unittest

from flexmock import flexmock

from iceprod.core.jsonUtil import json_encode, json_decode
import iceprod.server.master_communication

class FakeResponse:
    def __init__(self,status,body,error=None):
        self.code = status
        self.body = body
        self.error = error

class master_communication_test(unittest.TestCase):
    def setUp(self):
        super(master_communication_test,self).setUp()
        self.test_dir = tempfile.mkdtemp(dir=os.getcwd())

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        super(master_communication_test,self).tearDown()

    @unittest_reporter
    def test_01_send_master(self):
        """Test master_communication.send_master()"""
        def client(*args,**kwargs):
            client.args = args
            client.kwargs = kwargs
            client.called = True
        client.called = False
        flexmock(iceprod.server.master_communication.AsyncHTTPClient).should_receive('fetch').replace_with(client)

        site_id = 'thesite'
        cfg = {'site_id':site_id,'master':{'url':'localhost','passkey':'thekey'}}
        method = 'mymethod'
        def cb(ret=None):
            cb.called = True
            cb.ret = ret
        cb.called = False
        iceprod.server.master_communication.send_master(cfg,method,callback=cb)
        if not client.called:
            raise Exception('client not called')
        client_body = json_decode(client.kwargs['body'])
        if client_body['method'] != method:
            raise Exception('method not correct')
        expected = {'site_id':site_id,'passkey':cfg['master']['passkey']}
        if client_body['params'] != expected:
            raise Exception('params not correct')

        r = FakeResponse(200,json_encode({'result':'ok'}),None)
        client.kwargs['callback'](r)
        if not cb.called:
            raise Exception('did not call callback')
        if cb.ret != 'ok':
            raise Exception('did not get response result')

        cb.called = False
        r = FakeResponse(200,json_encode({'error':'fail'}),None)
        client.kwargs['callback'](r)
        if not cb.called:
            raise Exception('did not call callback')
        if not isinstance(cb.ret,Exception):
            raise Exception('did not return exception')
        correct = ('error: %r'%u'fail',)
        if cb.ret.args != correct:
            logger.info('value: %r',cb.ret.args)
            logger.info('correct: %r',correct)
            raise Exception('wrong error')

        cb.called = False
        r = FakeResponse(400,'','fail')
        client.kwargs['callback'](r)
        if not cb.called:
            raise Exception('did not call callback')
        if not isinstance(cb.ret,Exception):
            raise Exception('did not return exception')
        correct = ('http error: %r'%'fail',)
        if cb.ret.args != correct:
            logger.info('value: %r',cb.ret.args)
            logger.info('correct: %r',correct)
            raise Exception('wrong error')

        cb.called = False
        r = FakeResponse(200,json_encode({}),None)
        client.kwargs['callback'](r)
        if not cb.called:
            raise Exception('did not call callback')
        if not isinstance(cb.ret,Exception):
            raise Exception('did not return exception')
        correct = ('bad response',)
        if cb.ret.args != correct:
            logger.info('value: %r',cb.ret.args)
            logger.info('correct: %r',correct)
            raise Exception('wrong error')

        client.called = False
        iceprod.server.master_communication.send_master(cfg,method)
        if not client.called:
            raise Exception('client not called')

        try:
            cfg = {}
            iceprod.server.master_communication.send_master(cfg,method)
        except Exception:
            pass
        else:
            raise Exception('did not raise exception')

        # try without passkey
        cfg = {'master':{'url':'localhost'}}
        method = 'mymethod'
        cb.called = False
        try:
            iceprod.server.master_communication.send_master(cfg,method,callback=cb)
        except Exception:
            pass
        else:
            raise Exception('did not raise exception')

        # try giving passkey directly
        cfg = {'master':{'url':'localhost','passkey':'tmpkey'}}
        method = 'mymethod'
        cb.called = False
        iceprod.server.master_communication.send_master(cfg,method,
                                                        passkey='otherkey',
                                                        callback=cb)
        if not client.called:
            raise Exception('client not called')
        client_body = json_decode(client.kwargs['body'])
        expected = {'passkey':'otherkey'}
        if client_body['params'] != expected:
            raise Exception('params not correct')

        # try with / on end of url
        cfg = {'site_id':site_id,'master':{'url':'localhost/','passkey':'tmpkey'}}
        cb.called = False
        iceprod.server.master_communication.send_master(cfg,method,callback=cb)
        if not client.called:
            raise Exception('client not called')
        client_body = json_decode(client.kwargs['body'])
        if client_body['method'] != method:
            raise Exception('method not correct')
        expected = {'site_id':site_id,'passkey':cfg['master']['passkey']}
        if client_body['params'] != expected:
            raise Exception('params not correct')

def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    alltests = glob_tests(loader.getTestCaseNames(master_communication_test))
    suite.addTests(loader.loadTestsFromNames(alltests,master_communication_test))
    return suite
