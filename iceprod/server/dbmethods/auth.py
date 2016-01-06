"""
Authorization and security database methods
"""

import logging
from datetime import datetime,timedelta
from functools import partial
import uuid

from iceprod.core.dataclasses import Number,String

from iceprod.server.dbmethods import dbmethod,_Methods_Base,datetime2str,str2datetime

logger = logging.getLogger('dbmethods.auth')

class auth(_Methods_Base):
    """
    The authorization / security DB methods.

    Takes a handle to a subclass of iceprod.server.modules.db.DBAPI
    as an argument.
    """
    @dbmethod
    def auth_get_site_auth(self,callback=None):
        """Get current site's id and key for authentication and authorization with other sites.
        Returns (site_id,key) tuple"""
        sql = 'select site.site_id,site.auth_key from site join setting on site.site_id = setting.site_id'
        bindings = tuple()
        cb = partial(self._auth_get_site_auth_callback,callback=callback)
        self.db.sql_read_task(sql,bindings,callback=cb)
    def _auth_get_site_auth_callback(self,ret,callback=None):
        if callback:
            if isinstance(ret,Exception):
                callback(ret)
            else:
                if len(ret) < 1:
                    callback(Exception('No site match for current site name'))
                elif len(ret) > 1:
                    callback(Exception('More than one site match for current site name'))
                elif len(ret[0]) < 2 or ret[0][1] is None:
                    # DB will return None if column is empty
                    callback(Exception('Row does not have both site and key'))
                else:
                    r = {'site_id':ret[0][0],
                         'auth_key':ret[0][1]}
                    callback(r)

    @dbmethod
    def auth_authorize_site(self,site,key,callback=None):
        """Validate site and key for authorization.
        Returns True/Exception"""
        sql = 'select site_id,auth_key from site where site_id = ?'
        bindings = (site,)
        cb = partial(self._auth_authorize_site_callback,key,callback=callback)
        self.db.sql_read_task(sql,bindings,callback=cb)
    def _auth_authorize_site_callback(self,key,ret,callback=None):
        if callback:
            if isinstance(ret,Exception):
                callback(ret)
            else:
                if len(ret) < 1:
                    callback(Exception('No site match for current site id'))
                elif len(ret) > 1:
                    callback(Exception('More than one site match for current site id'))
                elif len(ret[0]) < 2 or ret[0][1] is None:
                    # DB will return None if column is empty
                    callback(Exception('Row does not have both site and key'))
                else:
                    callback(key == ret[0][1])

    @dbmethod
    def auth_authorize_task(self,key,callback=None):
        """Validate key for authorization.
        Returns True/Exception"""
        sql = 'select key,expire from passkey where key = ?'
        bindings = (key,)
        cb = partial(self._auth_authorize_task_callback,key,callback=callback)
        self.db.sql_read_task(sql,bindings,callback=cb)
    def _auth_authorize_task_callback(self,key,ret,callback=None):
        if callback:
            if isinstance(ret,Exception):
                callback(ret)
            else:
                if len(ret) < 1:
                    callback(Exception('No match for passkey'))
                elif len(ret) > 1:
                    callback(Exception('More than one match for passkey'))
                elif len(ret[0]) < 2 or ret[0][1] is None:
                    # DB will return None if column is empty
                    callback(Exception('Row does not have both key and expiration time'))
                else:
                    k = ret[0][0]
                    d = str2datetime(ret[0][1])
                    if k != key:
                        callback(Exception('Passkey returned from db does not match key'))
                    elif d < datetime.now():
                        callback(Exception('Passkey is expired'))
                    else:
                        callback(True)

    @dbmethod
    def auth_new_passkey(self,expiration=3600,callback=None):
        """Make a new passkey.  Default expiration in 1 hour."""
        if isinstance(expiration,Number):
            expiration = datetime.utcnow()+timedelta(seconds=expiration)
        elif not isinstance(expiration,datetime):
            raise Exception('bad expiration')

        passkey_id = self.db.increment_id('passkey')
        passkey = uuid.uuid4().hex
        sql = 'insert into passkey (passkey_id,key,expire) '
        sql += ' values (?,?,?)'
        bindings = (passkey_id,passkey,datetime2str(expiration))
        cb = partial(self._auth_new_passkey_callback,passkey,callback=callback)
        self.db.sql_write_task(sql,bindings,callback=cb)
    def _auth_new_passkey_callback(self,passkey,ret,callback=None):
        if isinstance(ret,Exception):
            callback(ret)
        else:
            callback(passkey)

    @dbmethod
    def auth_get_passkey(self,passkey,callback=None):
        """Get the expiration datetime of a passkey"""
        if not passkey:
            raise Exception('bad expiration')

        sql = 'select * from passkey where key = ?'
        bindings = (passkey,)
        cb = partial(self._auth_get_passkey_callback,callback=callback)
        self.db.sql_read_task(sql,bindings,callback=cb)
    def _auth_get_passkey_callback(self,ret,callback=None):
        if isinstance(ret,Exception):
            callback(ret)
        elif not ret or len(ret) < 1 or len(ret[0]) < 3:
            callback(Exception('get_passkey did not return a passkey'))
        else:
            try:
                expiration = str2datetime(ret[0][2])
            except Exception as e:
                callback(e)
            else:
                callback(expiration)

    @dbmethod
    def add_site_to_master(self,site_id,callback=None):
        """Add a remote site to the master and return a new passkey"""
        passkey = uuid.uuid4().hex
        sql = 'insert into site (site_id,auth_key) values (?,?)'
        bindings = (site_id,passkey)
        cb = partial(self._add_site_to_master_callback,passkey,
                     callback=callback)
        self.db.sql_write_task(sql,bindings,callback=cb)
    def _add_site_to_master_callback(self,passkey,ret=None,callback=None):
        if isinstance(ret,Exception):
            callback(ret)
        else:
            callback(passkey)

    @dbmethod
    def join_pool(self,passkey,callback=None):
        """Join this site with a pool"""
        cb = partial(self._join_pool_blocking,passkey,callback=callback)
        self.db.blocking_task('join',cb)
    def _join_pool_blocking(self,passkey,callback=None):
        conn,archive_conn = self.db._dbsetup()
        sql = 'select site_id from setting'
        bindings = tuple()
        try:
            ret = self.db._db_read(conn,sql,bindings,None,None,None)
        except Exception as e:
            ret = e
        if isinstance(ret,Exception):
            callback(ret)
            return
        if not ret or not ret[0]:
            callback(Exception('could not find site_id'))
            return
        site_id = ret[0][0]
        sql = 'update site set auth_key = ?'
        bindings = (passkey,)
        try:
            self.db._db_write(conn,sql,bindings,None,None,None)
        except Exception as e:
            callback(e)
        else:
            callback(None)
