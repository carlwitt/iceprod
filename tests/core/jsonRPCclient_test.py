"""
Test script for jsonRPCclient
"""

from __future__ import absolute_import, division, print_function

from tests.util import unittest_reporter, glob_tests

import logging
logger = logging.getLogger('jsonRPCclient')

import os, sys, time
import shutil
import random
import string
from threading import Thread
from multiprocessing import Queue

try:
    import cPickle as pickle
except:
    import pickle

import unittest
import pycurl

from flexmock import flexmock

import iceprod.core.util
import iceprod.core.jsonUtil
import iceprod.core.jsonRPCclient


class jsonRPCclient_test(unittest.TestCase):
    def setUp(self):
        super(jsonRPCclient_test,self).setUp()
        self.test_dir = os.path.join(os.getcwd(),'test')
        if not os.path.exists(self.test_dir):
            os.mkdir(self.test_dir)

        # mock the PycURL interface
        self.put_called = False
        self.put_args = ([],{})
        flexmock(iceprod.core.util.PycURL).should_receive('put').replace_with(self.put)
        self.fetch_body = ''
        self.fetch_called = False
        self.fetch_args = ([],{})
        flexmock(iceprod.core.util.PycURL).should_receive('fetch').replace_with(self.fetch)
        self.post_headers = []
        self.post_body = ''
        self.post_called = False
        self.post_args = ([],{})
        flexmock(iceprod.core.util.PycURL).should_receive('post').replace_with(self.post)

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        super(jsonRPCclient_test,self).tearDown()

    # the mocked functions of PycURL
    def put(self,*args,**kwargs):
        self.put_called = True
        self.put_args = (args,kwargs)
    def fetch(self, *args,**kwargs):
        with open(args[1]) as f:
            f.write(self.fetch_body)
        self.fetch_called = True
        self.fetch_args = (args,kwargs)
    def post(self, *args,**kwargs):
        url = args[0]
        writefunc = args[1]
        if 'headerfunc' in kwargs:
            headerfunc = kwargs['headerfunc']
            for h in self.post_headers:
                headerfunc(h)
        if 'postbody' in kwargs:
            self.post_body = kwargs['postbody']
        self.post_called = True
        self.post_args = (args,kwargs)
        writefunc(self.post_response())

    @unittest_reporter(name='Client.init()')
    def test_01_init(self):
        """Test init"""
        address = 'the address'
        rpc = iceprod.core.jsonRPCclient.Client(address=address)

    @unittest_reporter(name='Client.newid()')
    def test_02_newid(self):
        """Test newid"""
        def runner(q):
            ret = []
            for _ in xrange(1000):
                ret.append(iceprod.core.jsonRPCclient.Client.newid())
            q.put(ret)
        q = Queue()
        for _ in xrange(10):
            Thread(target=runner,args=(q,)).start()
        ret = []
        for _ in xrange(10):
            ret.extend(q.get())
        if len(ret) != len(set(ret)):
            raise Exception('duplicate ids')
        if len(ret) != 1000*10:
            raise Exception('incorrect number of ids')

    @unittest_reporter(name='Client.request()')
    def test_03_request(self):
        """Test request"""
        address = 'the address'
        passkey = 'passkey'
        result = 'the result'
        rpc = iceprod.core.jsonRPCclient.Client(address=address)

        def response():
            body = iceprod.core.jsonUtil.json_decode(self.post_body)
            ret = {}
            ret['id'] = body['id']
            ret['jsonrpc'] = body['jsonrpc']
            ret['result'] = result
            return iceprod.core.jsonUtil.json_encode(ret)
        self.post_response = response
        self.post_headers = []
        self.post_body = ''
        self.post_called = False
        self.post_args = ([],{})

        kwargs = {
            'passkey':passkey,
        }
        ret = rpc.request('test',kwargs)

        if self.post_called is False:
            raise Exception('PycURL.post() not called')
        elif ret != result:
            raise Exception('did not return result.  expecting %r but got %r'%(result,ret))

    @unittest_reporter(name='JSONRPC.start()')
    def test_10_start(self):
        """Test start"""
        address = 'the address'
        passkey = 'passkey'
        for _ in range(10):
            iceprod.core.jsonRPCclient.JSONRPC.start(address=address,passkey=passkey)

    @unittest_reporter(name='JSONRPC.stop()')
    def test_11_stop(self):
        """Test stop"""
        address = 'the address'
        passkey = 'passkey'
        for _ in range(10):
            iceprod.core.jsonRPCclient.JSONRPC.start(address=address,passkey=passkey)
            iceprod.core.jsonRPCclient.JSONRPC.stop()

    @unittest_reporter(name='JSONRPC.restart()')
    def test_12_restart(self):
        """Test restart"""
        address = 'the address'
        passkey = 'passkey'
        for _ in range(10):
            iceprod.core.jsonRPCclient.JSONRPC.start(address=address,passkey=passkey)
            iceprod.core.jsonRPCclient.JSONRPC.restart()

    @unittest_reporter(name='JSONRPC.rpc()')
    def test_20_rpc(self):
        """Test actual rpc functions"""
        address = 'the address'
        passkey = 'passkey'
        result = 'the result'
        iceprod.core.jsonRPCclient.JSONRPC.start(address=address,passkey=passkey)

        def response():
            body = iceprod.core.jsonUtil.json_decode(self.post_body)
            ret = {}
            ret['id'] = body['id']
            ret['jsonrpc'] = body['jsonrpc']
            ret['result'] = result
            return iceprod.core.jsonUtil.json_encode(ret)
        self.post_response = response
        self.post_headers = []
        self.post_body = ''
        self.post_called = False
        self.post_args = ([],{})

        ret = iceprod.core.jsonRPCclient.JSONRPC.test()

        if self.post_called is False:
            raise Exception('PycURL.post() not called')
        elif ret != result:
            raise Exception('did not return result.  expecting %r but got %r'%(result,ret))

    @unittest_reporter(name='JSONRPC timeout')
    def test_21_timeout(self):
        """Test rpc timeout"""
        address = 'the address'
        passkey = 'passkey'
        result = 'the result'
        iceprod.core.jsonRPCclient.JSONRPC.start(timeout=2,address=address,passkey=passkey)

        def response():
            body = iceprod.core.jsonUtil.json_decode(self.post_body)
            raise pycurl.error(pycurl.E_OPERATION_TIMEOUTED, "timeout")

        self.post_response = response
        self.post_headers = []
        self.post_body = ''
        self.post_called = False
        self.post_args = ([],{})

        try:
            iceprod.core.jsonRPCclient.JSONRPC.test()
        except:
            pass
        else:
            raise Exception('PycURL.post() timeout not raised')


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    alltests = glob_tests(loader.getTestCaseNames(jsonRPCclient_test))
    suite.addTests(loader.loadTestsFromNames(alltests,jsonRPCclient_test))
    return suite