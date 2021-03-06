"""
Test script for REST/auth
"""

import logging
logger = logging.getLogger('rest_auth_test')

import os
import sys
import time
import random
import shutil
import tempfile
import unittest
import subprocess
import json
from functools import partial
from unittest.mock import patch, MagicMock

from tests.util import unittest_reporter, glob_tests

import ldap3
import tornado.web
import tornado.ioloop
from tornado.httpclient import AsyncHTTPClient, HTTPError
from tornado.testing import AsyncTestCase

from rest_tools.server import Auth, RestServer

from iceprod.server.modules.rest_api import setup_rest
import iceprod.server.rest.config

class rest_config_test(AsyncTestCase):
    def setUp(self):
        super(rest_config_test,self).setUp()
        self.test_dir = tempfile.mkdtemp(dir=os.getcwd())
        def cleanup():
            shutil.rmtree(self.test_dir)
        self.addCleanup(cleanup)

        try:
            self.port = random.randint(10000,50000)
            self.mongo_port = random.randint(10000,50000)
            dbpath = os.path.join(self.test_dir,'db')
            os.mkdir(dbpath)
            dblog = os.path.join(dbpath,'logfile')

            m = subprocess.Popen(['mongod', '--port', str(self.mongo_port),
                                  '--dbpath', dbpath, '--smallfiles',
                                  '--quiet', '--nounixsocket',
                                  '--logpath', dblog])
            self.addCleanup(partial(time.sleep, 0.05))
            self.addCleanup(m.terminate)

            config = {
                'auth': {
                    'secret': 'secret'
                },
                'rest': {
                    'config': {
                        'database': {'port':self.mongo_port},
                    }
                },
            }
            routes, args = setup_rest(config)
            self.server = RestServer(**args)
            for r in routes:
                self.server.add_route(*r)
            self.server.startup(port=self.port)
            self.token = Auth('secret').create_token('foo', type='user', payload={'role':'admin'})
        except Exception:
            logger.info('failed setup', exc_info=True)


    @unittest_reporter(name='REST GET    /config/<dataset_id>')
    def test_100_config(self):
        client = AsyncHTTPClient()
        with self.assertRaises(HTTPError) as e:
            r = yield client.fetch('http://localhost:%d/config/bar'%self.port,
                    headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(e.exception.code, 404)

    @unittest_reporter(name='REST PUT    /config/<dataset_id>')
    def test_110_config(self):
        client = AsyncHTTPClient()
        data = {
            'name': 'foo'
        }
        r = yield client.fetch('http://localhost:%d/config/bar'%self.port,
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:%d/config/bar'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(data, ret)

def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    alltests = glob_tests(loader.getTestCaseNames(rest_config_test))
    suite.addTests(loader.loadTestsFromNames(alltests,rest_config_test))
    return suite
