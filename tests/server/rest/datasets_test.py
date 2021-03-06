"""
Test script for REST/datasets
"""

import logging
logger = logging.getLogger('rest_datasets_test')

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
import tornado.gen
from tornado.httpclient import AsyncHTTPClient, HTTPError, HTTPRequest, HTTPResponse
from tornado.testing import AsyncTestCase

from rest_tools.server import Auth, RestServer

from iceprod.server.modules.rest_api import setup_rest
import iceprod.server.rest.datasets

orig_fetch = tornado.httpclient.AsyncHTTPClient.fetch

class rest_datasets_test(AsyncTestCase):
    def setUp(self):
        super(rest_datasets_test,self).setUp()
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

            self.module_auth_token = Auth('secret').create_token('foo', type='system', payload={'role':'system','username':'admin'})
            config = {
                'auth': {
                    'secret': 'secret'
                },
                'rest': {
                    'datasets': {
                        'database': {'port':self.mongo_port},
                    },
                },
                'rest_api': {
                    'auth_key': self.module_auth_token.decode('utf-8'),
                },
            }
            routes, args = setup_rest(config)
            self.server = RestServer(**args)
            for r in routes:
                self.server.add_route(*r)
            self.server.startup(port=self.port)
            self.token = Auth('secret').create_token('foo', type='user', payload={'role':'admin','username':'admin'})
        except Exception:
            logger.info('failed setup', exc_info=True)


    @unittest_reporter(name='REST GET    /datasets')
    def test_100_datasets(self):
        client = AsyncHTTPClient()
        r = yield client.fetch('http://localhost:%d/datasets'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(ret, {})

    @patch('tornado.httpclient.AsyncHTTPClient.fetch', autospec=True)
    @unittest_reporter(name='REST POST   /datasets')
    def test_110_datasets(self, fetch):
        # need to mock the REST auth interface
        def mocked(self, url, *args, **kwargs):
            if 'auth' in url:
                return tornado.gen.maybe_future(HTTPResponse(HTTPRequest(url), 200))
            else:
                return orig_fetch(self, url, *args, **kwargs)
        fetch.side_effect = mocked

        client = AsyncHTTPClient()
        data = {
            'description': 'blah',
            'jobs_submitted': 1,
            'tasks_submitted': 4,
            'group': 'foo',
        }
        r = yield client.fetch('http://localhost:%d/datasets'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        uri = ret['result']
        dataset_id = uri.split('/')[-1]
        
        r = yield client.fetch('http://localhost:%d/datasets'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertIn(dataset_id, ret)
        for k in data:
            self.assertIn(k, ret[dataset_id])
            self.assertEqual(data[k], ret[dataset_id][k])
        
        r = yield client.fetch('http://localhost:%d/datasets?status=suspended'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertNotIn(dataset_id, ret)
        
        r = yield client.fetch('http://localhost:%d/datasets?keys=dataset_id|dataset'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertIn(dataset_id, ret)
        self.assertCountEqual(['dataset_id','dataset'], ret[dataset_id])

        r = yield client.fetch('http://localhost:%d/datasets/%s'%(self.port,dataset_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        for k in data:
            self.assertIn(k, ret)
            self.assertEqual(data[k], ret[k])

    @unittest_reporter(name='REST GET    /datasets/<dataset_id>')
    def test_120_datasets(self):
        client = AsyncHTTPClient()
        with self.assertRaises(HTTPError) as e:
            r = yield client.fetch('http://localhost:%d/datasets/bar'%self.port,
                    headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(e.exception.code, 404)

    @patch('tornado.httpclient.AsyncHTTPClient.fetch', autospec=True)
    @unittest_reporter(name='REST PUT    /datasets/<dataset_id>/description')
    def test_200_datasets(self, fetch):
        # need to mock the REST auth interface
        def mocked(self, url, *args, **kwargs):
            if 'auth' in url:
                return tornado.gen.maybe_future(HTTPResponse(HTTPRequest(url), 200))
            else:
                return orig_fetch(self, url, *args, **kwargs)
        fetch.side_effect = mocked

        client = AsyncHTTPClient()
        data = {
            'description': 'blah',
            'jobs_submitted': 1,
            'tasks_submitted': 4,
            'group': 'foo',
        }
        r = yield client.fetch('http://localhost:%d/datasets'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        uri = ret['result']
        dataset_id = uri.split('/')[-1]

        data = {'description': 'foo bar baz'}
        r = yield client.fetch('http://localhost:%d/datasets/%s/description'%(self.port,dataset_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(ret, {})
        
        r = yield client.fetch('http://localhost:%d/datasets/%s'%(self.port,dataset_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(ret['description'], data['description'])

    @patch('tornado.httpclient.AsyncHTTPClient.fetch', autospec=True)
    @unittest_reporter(name='REST PUT    /datasets/<dataset_id>/status')
    def test_210_datasets(self, fetch):
        # need to mock the REST auth interface
        def mocked(self, url, *args, **kwargs):
            if 'auth' in url:
                return tornado.gen.maybe_future(HTTPResponse(HTTPRequest(url), 200))
            else:
                return orig_fetch(self, url, *args, **kwargs)
        fetch.side_effect = mocked

        client = AsyncHTTPClient()
        data = {
            'description': 'blah',
            'jobs_submitted': 1,
            'tasks_submitted': 4,
            'group': 'foo',
        }
        r = yield client.fetch('http://localhost:%d/datasets'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        uri = ret['result']
        dataset_id = uri.split('/')[-1]

        data = {'status': 'suspended'}
        r = yield client.fetch('http://localhost:%d/datasets/%s/status'%(self.port,dataset_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(ret, {})
        
        r = yield client.fetch('http://localhost:%d/datasets/%s'%(self.port,dataset_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(ret['status'], data['status'])

    @patch('tornado.httpclient.AsyncHTTPClient.fetch', autospec=True)
    @unittest_reporter(name='REST GET    /dataset_summaries/status')
    def test_300_datasets(self, fetch):
        # need to mock the REST auth interface
        def mocked(self, url, *args, **kwargs):
            if 'auth' in url:
                return tornado.gen.maybe_future(HTTPResponse(HTTPRequest(url), 200))
            else:
                return orig_fetch(self, url, *args, **kwargs)
        fetch.side_effect = mocked

        client = AsyncHTTPClient()
        data = {
            'description': 'blah',
            'jobs_submitted': 1,
            'tasks_submitted': 4,
            'group': 'foo',
        }
        r = yield client.fetch('http://localhost:%d/datasets'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        uri = ret['result']
        dataset_id = uri.split('/')[-1]
        
        r = yield client.fetch('http://localhost:%d/dataset_summaries/status'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(ret, {'processing': [dataset_id]})

def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    alltests = glob_tests(loader.getTestCaseNames(rest_datasets_test))
    suite.addTests(loader.loadTestsFromNames(alltests,rest_datasets_test))
    return suite
