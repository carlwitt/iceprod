import logging
import json
import uuid
import io
from functools import partial
import asyncio
from concurrent.futures import ThreadPoolExecutor

import tornado.web
import pymongo
import motor

try:
    import boto3
    import botocore.client
except ImportError:
    boto3 = None

from iceprod.server.util import nowstr
from iceprod.server.rest import RESTHandler, RESTHandlerSetup, authorization, catch_error

logger = logging.getLogger('rest.logs')


class S3:
    """S3 wrapper for uploading and downloading objects"""
    def __init__(self, config):
        self.s3 = None
        self.bucket = 'iceprod2-logs'
        if (boto3 and 's3' in config and 'access_key' in config['s3'] and
            'secret_key' in config['s3']):
            try:
                self.s3 = boto3.client('s3','us-east-1',
                    aws_access_key_id=config['s3']['access_key'],
                    aws_secret_access_key=config['s3']['secret_key'],
                    config=botocore.client.Config(max_pool_connections=101))
            except Exception:
                logger.warning('failed to connect to s3: %r',
                            config['s3'], exc_info=True)
        self.executor = ThreadPoolExecutor(max_workers=20)

    async def get(self, key):
        """Download object from S3"""
        ret = ''
        with io.BytesIO() as f:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self.executor,
                    partial(self.s3.download_fileobj, Bucket=self.bucket,
                            Key=key, Fileobj=f))
            ret = f.getvalue()
        return ret.decode('utf-8')

    async def put(self, key, data):
        """Upload object to S3"""
        with io.BytesIO(data.encode('utf-8')) as f:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self.executor,
                    partial(self.s3.upload_fileobj, f, self.bucket, key))


def setup(config, *args, **kwargs):
    """
    Setup method for Logs REST API.

    Sets up any database connections or other prerequisites.

    Args:
        config (dict): an instance of :py:class:`iceprod.server.config`.

    Returns:
        list: Routes for logs, which can be passed to :py:class:`tornado.web.Application`.
    """
    cfg_rest = config.get('rest',{}).get('logs',{})
    db_cfg = cfg_rest.get('database',{})

    # add indexes
    db = pymongo.MongoClient(**db_cfg).logs
    if 'log_id_index' not in db.logs.index_information():
        db.logs.create_index('log_id', name='log_id_index', unique=True)
    if 'task_id_index' not in db.logs.index_information():
        db.logs.create_index('task_id', name='task_id_index', unique=False)
    if 'dataset_id_index' not in db.logs.index_information():
        db.logs.create_index('dataset_id', name='dataset_id_index', unique=False)

    # S3
    s3 = S3(config) if boto3 and 's3' in config else None

    handler_cfg = RESTHandlerSetup(config, *args, **kwargs)
    handler_cfg.update({
        'database': motor.motor_tornado.MotorClient(**db_cfg).logs,
        's3': s3,
    })

    return [
        (r'/logs', MultiLogsHandler, handler_cfg),
        (r'/logs/(?P<log_id>\w+)', LogsHandler, handler_cfg),
        (r'/datasets/(?P<dataset_id>\w+)/logs', DatasetMultiLogsHandler, handler_cfg),
        (r'/datasets/(?P<dataset_id>\w+)/logs/(?P<log_id>\w+)', DatasetLogsHandler, handler_cfg),
        (r'/datasets/(?P<dataset_id>\w+)/tasks/(?P<task_id>\w+)/logs', DatasetTaskLogsHandler, handler_cfg),
    ]


class BaseHandler(RESTHandler):
    def initialize(self, database=None, s3=None, **kwargs):
        super(BaseHandler, self).initialize(**kwargs)
        self.db = database
        self.s3 = s3

class MultiLogsHandler(BaseHandler):
    """
    Handle logs requests.
    """
    @authorization(roles=['admin','pilot'])
    async def post(self):
        """
        Create a log entry.

        Body should contain the following fields:
            data: str

        Optional fields:
            dataset_id: str
            task_id: str
            name: str

        Returns:
            dict: {'result': <log_id>}
        """
        data = json.loads(self.request.body)
        if 'data' not in data:
            raise tornado.web.HTTPError(400, reason='data field not in body')
        if 'name' not in data:
            data['name'] = 'log'
        data['log_id'] = uuid.uuid1().hex
        data['timestamp'] = nowstr()
        if self.s3 and len(data['data']) > 1000000:
            await self.s3.put(data['log_id'], data['data'])
            del data['data']
        ret = await self.db.logs.insert_one(data)
        self.set_status(201)
        self.write({'result': data['log_id']})
        self.finish()

class LogsHandler(BaseHandler):
    """
    Handle logs requests.
    """
    @authorization(roles=['admin'])
    async def get(self, log_id):
        """
        Get a log entry.

        Args:
            log_id (str): the log id of the entry

        Returns:
            dict: all body fields
        """
        ret = await self.db.logs.find_one({'log_id':log_id},
                projection={'_id':False})
        if not ret:
            self.send_error(404, reason="Log not found")
        else:
            if 'data' not in ret:
                if self.s3:
                    ret['data'] = await self.s3.get(ret['log_id'])
                else:
                    raise tornado.web.HTTPError(500, reason='no data field and s3 disabled')
            self.write(ret)
            self.finish()

class DatasetMultiLogsHandler(BaseHandler):
    """
    Handle logs requests.
    """
    @authorization(roles=['admin'], attrs=['dataset_id:write'])
    async def post(self, dataset_id):
        """
        Create a log entry.

        Body should contain the following fields:
            data: str

        Optional fields:
            task_id: str
            name: str

        Args:
            dataset_id (str): the dataset id

        Returns:
            dict: {'result': <log_id>}
        """
        data = json.loads(self.request.body)
        if 'data' not in data:
            raise tornado.web.HTTPError(400, reason='data field not in body')
        data['log_id'] = uuid.uuid1().hex
        data['dataset_id'] = dataset_id
        data['timestamp'] = nowstr()
        if self.s3 and len(data['data']) > 1000000:
            await self.s3.put(data['log_id'], data['data'])
            del data['data']
        ret = await self.db.logs.insert_one(data)
        self.set_status(201)
        self.write({'result': data['log_id']})
        self.finish()

class DatasetLogsHandler(BaseHandler):
    """
    Handle logs requests.
    """
    @authorization(roles=['admin'], attrs=['dataset_id:read'])
    async def get(self, dataset_id, log_id):
        """
        Get a log.

        Args:
            dataset_id (str): the dataset id
            log_id (str): the log id of the entry

        Returns:
            dict: all body fields
        """
        ret = await self.db.logs.find_one({'dataset_id':dataset_id,'log_id':log_id},
                projection={'_id':False})
        if not ret:
            self.send_error(404, reason="Log not found")
        else:
            if 'data' not in ret:
                if self.s3:
                    ret['data'] = await self.s3.get(ret['log_id'])
                else:
                    raise tornado.web.HTTPError(500, reason='no data field and s3 disabled')
            self.write(ret)
            self.finish()

class DatasetTaskLogsHandler(BaseHandler):
    """
    Handle log requests for a task
    """
    @authorization(roles=['admin'], attrs=['dataset_id:read'])
    async def get(self, dataset_id, task_id):
        """
        Get logs for a dataset and task.

        Note: "num" and "group" are generally not used together.

        Params (optional):
            num (int): number of logs, or groups of logs, to return
            group {true, false}: group by log name
            order {asc, desc}: order by time
            keys: | separated list of keys to return for each log

        Args:
            dataset_id (str): the dataset id
            task_id (str): the task id

        Returns:
            dict: {'logs': [log entry dict, log entry dict]}
        """
        filters = {'dataset_id': dataset_id, 'task_id': task_id}

        num = self.get_argument('num', None)
        if num:
            try:
                num = int(num)
            except Exception:
                raise tornado.web.HTTPError(400, reason='bad num param. must be int')

        group = self.get_argument('group', 'false').lower() == 'true'
        order = self.get_argument('order', 'desc').lower()
        if order not in ('asc', 'desc'):
            raise tornado.web.HTTPError(400, reason='bad order param. should be "asc" or "desc".')
        
        projection = {'_id': False}
        keys = self.get_argument('keys', None)
        if keys:
            projection.update({x:True for x in keys.split('|') if x})
        
        steps = [
            {'$match': filters},
            {'$sort': {'timestamp': -1 if order == 'desc' else 1}},
        ]
        if group:
            if not keys:
                keys = 'log_id|name|task_id|dataset_id|data|timestamp'
            grouping = {x:{'$first':'$'+x} for x in keys.split('|') if x}
            grouping['_id'] = '$name'
            if 'timestamp' not in grouping:
                grouping['timestamp'] = {'$first': '$timestamp'}
            steps.extend([
                {'$group': grouping},
                {'$sort': {'timestamp': -1 if order == 'desc' else 1}},
            ])
        steps.append({'$project': projection})
        if num:
            steps.append({'$limit': num})
        logger.debug('steps: %r', steps)

        cur = self.db.logs.aggregate(steps, allowDiskUse=True)
        ret = []
        async for entry in cur:
            ret.append(entry)
        if not ret:
            self.send_error(404, reason="Log not found")
        else:
            for log in ret:
                if 'data' not in log:
                    if self.s3:
                        log['data'] = await self.s3.get(log['log_id'])
                    else:
                        raise Exception('no data field and s3 disabled')
            self.write({'logs':ret})
            self.finish()
