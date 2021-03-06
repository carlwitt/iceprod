"""
Test script for REST/jobs
"""

import logging
logger = logging.getLogger('rest_jobs_test')

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

class rest_jobs_test(AsyncTestCase):
    def setUp(self):
        super(rest_jobs_test,self).setUp()
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
                    'jobs': {
                        'database': {'port':self.mongo_port},
                    }
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

    @unittest_reporter(name='REST POST   /jobs')
    def test_105_jobs(self):
        client = AsyncHTTPClient()
        data = {
            'dataset_id': 'foo',
            'job_index': 0,
        }
        r = yield client.fetch('http://localhost:%d/jobs'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        self.assertIn('result', ret)

    @unittest_reporter(name='REST GET    /jobs/<job_id>')
    def test_110_jobs(self):
        client = AsyncHTTPClient()
        data = {
            'dataset_id': 'foo',
            'job_index': 0,
        }
        r = yield client.fetch('http://localhost:%d/jobs'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        job_id = ret['result']

        r = yield client.fetch('http://localhost:%d/jobs/%s'%(self.port,job_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        for k in data:
            self.assertIn(k, ret)
            self.assertEqual(data[k], ret[k])
        for k in ('status','status_changed'):
            self.assertIn(k, ret)
        self.assertEqual(ret['status'], 'processing')

    @unittest_reporter(name='REST PATCH  /jobs/<job_id>')
    def test_120_jobs(self):
        client = AsyncHTTPClient()
        data = {
            'dataset_id': 'foo',
            'job_index': 0,
        }
        r = yield client.fetch('http://localhost:%d/jobs'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        job_id = ret['result']

        new_data = {
            'status': 'processing',
        }
        r = yield client.fetch('http://localhost:%d/jobs/%s'%(self.port,job_id),
                method='PATCH', body=json.dumps(new_data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        for k in new_data:
            self.assertIn(k, ret)
            self.assertEqual(new_data[k], ret[k])

    @unittest_reporter(name='REST GET    /datasets/<dataset_id>/jobs')
    def test_200_jobs(self):
        client = AsyncHTTPClient()
        data = {
            'dataset_id': 'foo',
            'job_index': 0,
        }
        r = yield client.fetch('http://localhost:%d/jobs'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        job_id = ret['result']

        r = yield client.fetch('http://localhost:%d/datasets/%s/jobs'%(self.port,data['dataset_id']),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertIn(job_id, ret)
        for k in data:
            self.assertIn(k, ret[job_id])
            self.assertEqual(data[k], ret[job_id][k])

    @unittest_reporter(name='REST GET    /datasets/<dataset_id>/jobs/<job_id>')
    def test_210_jobs(self):
        client = AsyncHTTPClient()
        data = {
            'dataset_id': 'foo',
            'job_index': 0,
        }
        r = yield client.fetch('http://localhost:%d/jobs'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        job_id = ret['result']

        r = yield client.fetch('http://localhost:%d/datasets/%s/jobs/%s'%(self.port,data['dataset_id'],job_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        for k in data:
            self.assertIn(k, ret)
            self.assertEqual(data[k], ret[k])
        for k in ('status','status_changed'):
            self.assertIn(k, ret)
        self.assertEqual(ret['status'], 'processing')

    @unittest_reporter(name='REST PUT    /datasets/<dataset_id>/jobs/<job_id>/status')
    def test_220_jobs(self):
        client = AsyncHTTPClient()
        data = {
            'dataset_id': 'foo',
            'job_index': 0,
        }
        r = yield client.fetch('http://localhost:%d/jobs'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        job_id = ret['result']

        data2 = {'status':'failed'}
        r = yield client.fetch('http://localhost:%d/datasets/%s/jobs/%s/status'%(self.port,data['dataset_id'],job_id),
                method='PUT', body=json.dumps(data2),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:%d/datasets/%s/jobs/%s'%(self.port,data['dataset_id'],job_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertIn('status', ret)
        self.assertEqual(ret['status'], 'failed')

    @unittest_reporter(name='REST GET    /datasets/<dataset_id>/job_summaries/status')
    def test_300_jobs(self):
        client = AsyncHTTPClient()
        data = {
            'dataset_id': 'foo',
            'job_index': 0,
        }
        r = yield client.fetch('http://localhost:%d/jobs'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        job_id = ret['result']

        r = yield client.fetch('http://localhost:%d/datasets/%s/job_summaries/status'%(self.port,data['dataset_id']),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(ret, {'processing': [job_id]})

    @unittest_reporter(name='REST GET    /datasets/<dataset_id>/job_counts/status')
    def test_400_jobs(self):
        client = AsyncHTTPClient()
        data = {
            'dataset_id': 'foo',
            'job_index': 0,
        }
        r = yield client.fetch('http://localhost:%d/jobs'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        ret = json.loads(r.body)
        job_id = ret['result']

        r = yield client.fetch('http://localhost:%d/datasets/%s/job_counts/status'%(self.port,data['dataset_id']),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(ret, {'processing': 1})

def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    alltests = glob_tests(loader.getTestCaseNames(rest_jobs_test))
    suite.addTests(loader.loadTestsFromNames(alltests,rest_jobs_test))
    return suite
