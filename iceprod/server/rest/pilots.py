import logging
import json
import uuid

import tornado.web
import pymongo
import motor

from iceprod.server.rest import RESTHandler, RESTHandlerSetup, authorization
from iceprod.server.util import nowstr

logger = logging.getLogger('rest.pilots')

def setup(config):
    """
    Setup method for Pilots REST API.

    Sets up any database connections or other prerequisites.

    Args:
        config (dict): an instance of :py:class:`iceprod.server.config`.

    Returns:
        list: Routes for logs, which can be passed to :py:class:`tornado.web.Application`.
    """
    cfg_auth = config.get('rest',{}).get('pilots',{})
    db_name = cfg_auth.get('database','mongodb://localhost:27017')

    # add indexes
    db = pymongo.MongoClient(db_name).pilots
    if 'pilot_id_index' not in db.pilots.index_information():
        db.pilots.create_index('pilot_id', name='pilot_id_index', unique=True)

    handler_cfg = RESTHandlerSetup(config)
    handler_cfg.update({
        'database': motor.motor_tornado.MotorClient(db_name).pilots,
    })

    return [
        (r'/pilots', MultiPilotsHandler, handler_cfg),
        (r'/pilots/(?P<pilot_id>\w+)', PilotsHandler, handler_cfg),
    ]

class BaseHandler(RESTHandler):
    def initialize(self, database=None, **kwargs):
        super(BaseHandler, self).initialize(**kwargs)
        self.db = database

class MultiPilotsHandler(BaseHandler):
    """
    Handle multi pilots requests.
    """
    @authorization(roles=['admin','client','system'])
    async def get(self):
        """
        Get pilot entries.

        Returns:
            dict: {'uuid': {pilot_data}}
        """
        ret = {}
        async for row in self.db.pilots.find(projection={'_id':False}):
            ret[row['pilot_id']] = row
        self.write(ret)
        self.finish()

    @authorization(roles=['admin','client'])
    async def post(self):
        """
        Create a pilot entry.

        Body should contain the pilot data.

        Returns:
            dict: {'result': <pilot_id>}
        """
        data = json.loads(self.request.body)

        # validate first
        req_fields = {
            'queue_host': str,
            'queue_version': str, # iceprod version
            'resources': dict, # min resources requested
        }
        for k in req_fields:
            if k not in data:
                raise tornado.web.HTTPError(400, reason='missing key: '+k)
            if not isinstance(data[k], req_fields[k]):
                r = 'key {} should be of type {}'.format(k, req_fields[k])
                raise tornado.web.HTTPError(400, reason=r)

        # set some fields
        data['pilot_id'] = uuid.uuid1().hex
        data['submit_time'] = nowstr()
        data['start_date'] = nowstr()
        data['last_update'] = data['start_date']
        if 'tasks' not in data:
            data['tasks'] = []
        if 'host' not in data:
            data['host'] = ''
        if 'version' not in data:
            data['version'] = ''
        if 'grid_queue_id' not in data:
            data['grid_queue_id'] = ''

        ret = await self.db.pilots.insert_one(data)
        self.set_status(201)
        self.write({'result': data['pilot_id']})
        self.finish()

class PilotsHandler(BaseHandler):
    """
    Handle single pilot requests.
    """
    @authorization(roles=['admin','client','pilot'])
    async def get(self, pilot_id):
        """
        Get a pilot entry.

        Args:
            pilot_id (str): the pilot id

        Returns:
            dict: pilot entry
        """
        ret = await self.db.pilots.find_one({'pilot_id':pilot_id},
                projection={'_id':False})
        if not ret:
            self.send_error(404, reason="Pilot not found")
        else:
            self.write(ret)
            self.finish()

    @authorization(roles=['admin','client','pilot'])
    async def patch(self, pilot_id):
        """
        Update a pilot entry.

        Body should contain the pilot data to update.  Note that this will
        perform a merge (not replace).

        Args:
            pilot_id (str): the pilot id

        Returns:
            dict: updated pilot entry
        """
        data = json.loads(self.request.body)
        if not data:
            raise tornado.web.HTTPError(400, reason='Missing update data')
        data['last_update'] = nowstr()

        ret = await self.db.pilots.find_one_and_update({'pilot_id':pilot_id},
                {'$set':data},
                projection={'_id':False},
                return_document=pymongo.ReturnDocument.AFTER)
        if not ret:
            self.send_error(404, reason="Pilot not found")
        else:
            self.write(ret)
            self.finish()

    @authorization(roles=['admin','client','pilot'])
    async def delete(self, pilot_id):
        """
        Delete a pilot entry.

        Args:
            pilot_id (str): the pilot id

        Returns:
            dict: empty dict
        """
        ret = await self.db.pilots.delete_one({'pilot_id':pilot_id})
        if (not ret) or (ret.deleted_count < 1):
            self.send_error(404, reason="Pilot not found")
        else:
            self.write({})
