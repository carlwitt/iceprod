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
from tornado.httpclient import AsyncHTTPClient
from tornado.testing import AsyncTestCase

from rest_tools.server import Auth, RestServer

from iceprod.server.modules.rest_api import setup_rest

class rest_auth_test(AsyncTestCase):
    def setUp(self):
        super(rest_auth_test,self).setUp()
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
            time.sleep(0.05)

            config = {
                'auth': {
                    'secret': 'secret'
                },
                'rest': {
                    'auth': {
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



    @unittest_reporter(name='REST GET    /roles')
    def test_100_role(self):
        client = AsyncHTTPClient()
        r = yield client.fetch('http://localhost:%d/roles'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertIn('results', data)
        self.assertEqual(data['results'], [])

    @unittest_reporter(name='REST PUT    /roles/<role_name>')
    def test_110_role(self):
        client = AsyncHTTPClient()
        data = {
            'name': 'foo'
        }
        r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:%d/roles'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertIn('results', data)
        self.assertEqual(data['results'], [{'name': 'foo'}])

    @unittest_reporter(name='REST GET    /roles/<role_name>')
    def test_120_role(self):
        client = AsyncHTTPClient()
        data = {
            'name': 'foo'
        }
        r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port,data['name']),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data, {'name': 'foo'})

    @unittest_reporter(name='REST DELETE /roles/<role_name>')
    def test_130_role(self):
        client = AsyncHTTPClient()
        data = {
            'name': 'foo'
        }
        r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port,data['name']),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data, {'name': 'foo'})

        r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port,data['name']),
                method='DELETE',
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        with self.assertRaises(Exception):
            r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port,data['name']),
                    headers={'Authorization': b'bearer '+self.token})

        r = yield client.fetch('http://localhost:%d/roles'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertIn('results', data)
        self.assertEqual(data['results'], [])

    @unittest_reporter(name='REST bad access to PUT /roles/<role_name>')
    def test_140_role(self):
        client = AsyncHTTPClient()
        data = {
            'name': 'foo'
        }
        user_token = Auth('secret').create_token('foo', type='user', payload={'role':'user'})
        with self.assertRaises(Exception):
            r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port,data['name']),
                    method='PUT', body=json.dumps(data),
                    headers={'Authorization': b'bearer '+user_token})

    @unittest_reporter(name='REST GET    /groups')
    def test_200_group(self):
        client = AsyncHTTPClient()
        r = yield client.fetch('http://localhost:%d/groups'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertIn('results', data)
        self.assertEqual(data['results'], [])

    @unittest_reporter(name='REST PUT    /groups/<group_name>')
    def test_210_group(self):
        client = AsyncHTTPClient()
        data = {
            'name': 'foo/bar'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port, data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:%d/groups'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertIn('results', data)
        self.assertEqual(data['results'], [{'name': 'foo/bar'}])

    @unittest_reporter(name='REST GET    /groups/<group_name>')
    def test_220_group(self):
        client = AsyncHTTPClient()
        data = {
            'name': 'foo/bar'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port, data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port, data['name']),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data, {'name': 'foo/bar'})

    @unittest_reporter(name='REST DELETE /groups/<group_id>')
    def test_230_group(self):
        client = AsyncHTTPClient()
        data = {
            'name': 'foo/bar'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port, data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port, data['name']),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data, {'name': 'foo/bar'})

        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port, data['name']),
                method='DELETE',
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        with self.assertRaises(Exception):
            yield client.fetch('http://localhost:{}/groups/{}'.format(self.port, data['name']),
                    headers={'Authorization': b'bearer '+self.token})
        
        r = yield client.fetch('http://localhost:%d/groups'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertIn('results', data)
        self.assertEqual(data['results'], [])

    @unittest_reporter(name='REST bad access to PUT /groups')
    def test_240_group(self):
        client = AsyncHTTPClient()
        data = {
            'name': '/foo/bar'
        }
        user_token = Auth('secret').create_token('foo', type='user', payload={'role':'user'})
        with self.assertRaises(Exception):
            yield client.fetch('http://localhost:{}/groups/{}'.format(self.port, data['name']),
                    method='PUT', body=json.dumps(data),
                    headers={'Authorization': b'bearer '+user_token})

    @unittest_reporter(name='REST GET    /users')
    def test_300_user(self):
        client = AsyncHTTPClient()
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertIn('results', data)
        self.assertEqual(data['results'], [])

    @unittest_reporter(name='REST POST   /users')
    def test_310_user(self):
        client = AsyncHTTPClient()
        data = {
            'username': 'foo'
        }
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        data = json.loads(r.body)
        self.assertIn('result', data)
        self.assertEqual(data['result'], r.headers['Location'])
        user_id = data['result'].rsplit('/')[-1]

        r = yield client.fetch('http://localhost:%d/users'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertIn('results', data)
        self.assertGreater(len(data['results']), 0)
        for k,v in {'user_id':user_id, 'username':'foo'}.items():
            self.assertIn(k, data['results'][0])
            self.assertEqual(data['results'][0][k], v)

    @unittest_reporter(name='REST GET    /users/<user_id>')
    def test_320_user(self):
        client = AsyncHTTPClient()
        data = {
            'username': 'foo'
        }
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        data = json.loads(r.body)
        self.assertIn('result', data)
        self.assertEqual(data['result'], r.headers['Location'])
        user_id = data['result'].rsplit('/')[-1]

        r = yield client.fetch('http://localhost:%d/users/%s'%(self.port, user_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        for k,v in {'user_id':user_id, 'username':'foo'}.items():
            self.assertIn(k, data)
            self.assertEqual(data[k], v)

    @unittest_reporter(name='REST DELETE /users/<user_id>')
    def test_330_user(self):
        client = AsyncHTTPClient()
        data = {
            'username': 'foo'
        }
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        data = json.loads(r.body)
        self.assertIn('result', data)
        self.assertEqual(data['result'], r.headers['Location'])
        user_id = data['result'].rsplit('/')[-1]

        r = yield client.fetch('http://localhost:%d/users/%s'%(self.port, user_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        for k,v in {'user_id':user_id, 'username':'foo'}.items():
            self.assertIn(k, data)
            self.assertEqual(data[k], v)

        r = yield client.fetch('http://localhost:%d/users/%s'%(self.port, user_id),
                method='DELETE',
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        with self.assertRaises(Exception):
            yield client.fetch('http://localhost:%d/users/%s'%(self.port, user_id),
                    headers={'Authorization': b'bearer '+self.token})
        
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertIn('results', data)
        self.assertEqual(data['results'], [])

    @unittest_reporter(name='REST bad access to POST /users')
    def test_340_user(self):
        client = AsyncHTTPClient()
        data = {
            'username': 'foo'
        }
        user_token = Auth('secret').create_token('foo', type='user', payload={'role':'user'})
        with self.assertRaises(Exception):
            r = yield client.fetch('http://localhost:%d/users'%self.port,
                    method='POST', body=json.dumps(data),
                    headers={'Authorization': b'bearer '+user_token})

    @unittest_reporter(name='REST POST   /users/<user_id>/groups')
    def test_410_user(self):
        client = AsyncHTTPClient()
        data = {
            'username': 'foo',
            'groups': ['bar']
        }
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        data = json.loads(r.body)
        self.assertIn('result', data)
        self.assertEqual(data['result'], r.headers['Location'])
        user_id = data['result'].rsplit('/')[-1]

        r = yield client.fetch('http://localhost:%d/users/%s/groups'%(self.port, user_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data, {'results': ['bar']})

        # now add the new group
        data = {
            'name': 'baz'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        data = {'group': data['name']}
        r = yield client.fetch('http://localhost:%d/users/%s/groups'%(self.port, user_id),
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:%d/users/%s/groups'%(self.port, user_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data, {'results': ['bar','baz']})

    @unittest_reporter(name='REST PUT    /users/<user_id>/groups')
    def test_420_user(self):
        client = AsyncHTTPClient()
        data = {
            'username': 'foo',
            'groups': ['bar']
        }
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        data = json.loads(r.body)
        self.assertIn('result', data)
        self.assertEqual(data['result'], r.headers['Location'])
        user_id = data['result'].rsplit('/')[-1]

        r = yield client.fetch('http://localhost:%d/users/%s/groups'%(self.port, user_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data, {'results': ['bar']})

        # now add the new group
        data = {
            'name': 'baz'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        data = {
            'name': 'blah'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        data = {'groups': ['baz', 'blah']}
        r = yield client.fetch('http://localhost:%d/users/%s/groups'%(self.port, user_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:%d/users/%s/groups'%(self.port, user_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data, {'results': ['baz', 'blah']})

    @unittest_reporter(name='REST PUT    /users/<user_id>/roles')
    def test_500_user(self):
        client = AsyncHTTPClient()
        data = {
            'username': 'foo',
            'roles': ['bar']
        }
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)
        data = json.loads(r.body)
        self.assertIn('result', data)
        self.assertEqual(data['result'], r.headers['Location'])
        user_id = data['result'].rsplit('/')[-1]

        r = yield client.fetch('http://localhost:%d/users/%s'%(self.port, user_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data['roles'], ['bar'])

        # now add the new role
        data = {
            'name': 'baz'
        }
        r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port, 'baz'),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        data = {
            'name': 'blah'
        }
        r = yield client.fetch('http://localhost:%d/roles/%s'%(self.port, 'blah'),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        data = {'roles': ['baz','blah']}
        r = yield client.fetch('http://localhost:%d/users/%s/roles'%(self.port, user_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        r = yield client.fetch('http://localhost:%d/users/%s'%(self.port, user_id),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)
        self.assertEqual(data['roles'], ['baz','blah'])

    @patch('ldap3.Connection')
    @unittest_reporter(name='REST POST   /ldap')
    def test_700_ldap(self, ldap_mock):
        client = AsyncHTTPClient()
        data = {
            'username': 'foo',
            'password': 'bar',
        }
        r = yield client.fetch('http://localhost:%d/ldap'%self.port,
                method='POST', body=json.dumps(data))
        self.assertEqual(r.code, 200)
        tok = json.loads(r.body)['token']
        data = Auth('secret').validate(tok)
        self.assertEqual(data['username'], 'foo')
        self.assertIn('role',data)
        self.assertIn('groups',data)

    @unittest_reporter(name='REST POST   /create_token')
    def test_800_auths(self):
        client = AsyncHTTPClient()

        # test temp token
        data = {
            'username': 'bar',
            'roles': ['foo','user']
        }
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)

        data = {
            'type': 'temp',
            'role': 'foo',
        }
        token2 = Auth('secret').create_token('bar', type='user',
                payload={'username':'bar','role':'user','groups':['baz']})
        r = yield client.fetch('http://localhost:%d/create_token'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+token2})
        self.assertEqual(r.code, 200)
        tok = json.loads(r.body)['result']
        data = Auth('secret').validate(tok)
        self.assertEqual(data['type'], 'temp')
        self.assertEqual(data['username'], 'bar')
        self.assertIn('role',data)
        self.assertEqual(data['role'], 'user')
        self.assertIn('groups',data)

        # test switching roles
        data = {
            'username': 'foo',
            'roles': ['admin','user']
        }
        r = yield client.fetch('http://localhost:%d/users'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 201)

        data = {
            'type': 'user',
            'role': 'admin',
            'exp': 10
        }
        token2 = Auth('secret').create_token('foo', type='user',
                payload={'username':'foo','role':'user','groups':['baz']})
        r = yield client.fetch('http://localhost:%d/create_token'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+token2})
        self.assertEqual(r.code, 200)
        tok = json.loads(r.body)['result']
        data = Auth('secret').validate(tok)
        self.assertEqual(data['type'], 'user')
        self.assertEqual(data['username'], 'foo')
        self.assertIn('role',data)
        self.assertEqual(data['role'], 'admin')
        self.assertIn('groups',data)
        self.assertLess(data['exp'], time.time()+10)

        # test internal token
        data = {
            'type': 'system',
            'role': 'pilot',
        }
        token2 = Auth('secret').create_token('foo', type='system',
                payload={'username':'foo','role':'client','groups':[]})
        r = yield client.fetch('http://localhost:%d/create_token'%self.port,
                method='POST', body=json.dumps(data),
                headers={'Authorization': b'bearer '+token2})
        self.assertEqual(r.code, 200)
        tok = json.loads(r.body)['result']
        data = Auth('secret').validate(tok)
        self.assertEqual(data['type'], 'system')
        self.assertEqual(data['username'], 'foo')
        self.assertIn('role',data)
        self.assertEqual(data['role'], 'pilot')

    @unittest_reporter(name='REST PUT    /auths/<dataset_id>')
    def test_900_auths(self):
        client = AsyncHTTPClient()

        # add group
        data = {
            'name': 'foo/bar'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        # add dataset auth
        data = {
            'read_groups': ['foo/bar'],
            'write_groups': []
        }
        dataset_id = '123'
        r = yield client.fetch('http://localhost:%d/auths/%s'%(self.port,dataset_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        data = json.loads(r.body)

    @unittest_reporter(name='REST GET    /auths/<dataset_id>')
    def test_901_auths(self):
        client = AsyncHTTPClient()

        # add group
        data = {
            'name': 'foo/bar'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)

        # add dataset auth
        data = {
            'read_groups': ['foo/bar'],
            'write_groups': []
        }
        dataset_id = '123'
        r = yield client.fetch('http://localhost:%d/auths/%s'%(self.port,dataset_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        
        # get dataset auth
        r = yield client.fetch('http://localhost:%d/auths/%s'%(self.port,dataset_id),
                method='GET',
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        self.assertEqual(data, ret)

    @unittest_reporter(name='REST GET    /auths/<dataset_id>/actions/read')
    def test_902_auths(self):
        client = AsyncHTTPClient()

        # add group
        data = {
            'name': 'foo/bar'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        
        token2 = Auth('secret').create_token('foo', type='user',
                payload={'role':'user','groups':['foo/bar']})

        # add dataset auth
        data = {
            'read_groups': ['foo/bar'],
            'write_groups': []
        }
        dataset_id = '123'
        r = yield client.fetch('http://localhost:%d/auths/%s'%(self.port,dataset_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        
        # get authorization
        r = yield client.fetch('http://localhost:%d/auths/%s/actions/read'%(self.port,dataset_id),
                method='GET',
                headers={'Authorization': b'bearer '+token2})
        self.assertEqual(r.code, 200)

        # add bad dataset auth
        data = {
            'read_groups': [],
            'write_groups': ['foo/bar']
        }
        dataset_id = '456'
        r = yield client.fetch('http://localhost:%d/auths/%s'%(self.port,dataset_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        
        # get authorization
        with self.assertRaises(tornado.httpclient.HTTPError) as e:
            r = yield client.fetch('http://localhost:%d/auths/%s/actions/read'%(self.port,dataset_id),
                    method='GET',
                    headers={'Authorization': b'bearer '+token2})
        self.assertEqual(e.exception.code, 403)

    @unittest_reporter(name='REST GET    /auths/<dataset_id>/actions/write')
    def test_903_auths(self):
        client = AsyncHTTPClient()

        # add group
        data = {
            'name': 'foo/bar'
        }
        r = yield client.fetch('http://localhost:{}/groups/{}'.format(self.port,data['name']),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        
        token2 = Auth('secret').create_token('foo', type='user',
                payload={'role':'user','groups':['foo/bar']})

        # add dataset auth
        data = {
            'read_groups': [],
            'write_groups': ['foo/bar']
        }
        dataset_id = '123'
        r = yield client.fetch('http://localhost:%d/auths/%s'%(self.port,dataset_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        
        # get authorization
        r = yield client.fetch('http://localhost:%d/auths/%s/actions/write'%(self.port,dataset_id),
                method='GET',
                headers={'Authorization': b'bearer '+token2})
        self.assertEqual(r.code, 200)

        # add bad dataset auth
        data = {
            'read_groups': ['foo/bar'],
            'write_groups': []
        }
        dataset_id = '456'
        r = yield client.fetch('http://localhost:%d/auths/%s'%(self.port,dataset_id),
                method='PUT', body=json.dumps(data),
                headers={'Authorization': b'bearer '+self.token})
        self.assertEqual(r.code, 200)
        ret = json.loads(r.body)
        
        # get authorization
        with self.assertRaises(tornado.httpclient.HTTPError) as e:
            r = yield client.fetch('http://localhost:%d/auths/%s/actions/write'%(self.port,dataset_id),
                    method='GET',
                    headers={'Authorization': b'bearer '+token2})
        self.assertEqual(e.exception.code, 403)


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    alltests = glob_tests(loader.getTestCaseNames(rest_auth_test))
    suite.addTests(loader.loadTestsFromNames(alltests,rest_auth_test))
    return suite
