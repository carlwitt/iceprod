"""
Database server module
"""

from threading import Thread, Event, Condition
import logging
import time
import random
from itertools import izip
from functools import partial
from contextlib import contextmanager
from collections import OrderedDict, Iterable

from iceprod.server.pool import PriorityThreadPool,SingleGrouping
from iceprod.server import module
from iceprod.server import dbmethods
from iceprod.server import GlobalID

logger = logging.getLogger('modules_db')

class db(module.module):
    """
    Handle all interaction with the local database
    """
    def __init__(self,*args,**kwargs):
        # run default init
        super(db,self).__init__(*args,**kwargs)
        self.service_class = DBService(self)
        self.db = None
        self.start()
        
    def start(self):
        """Start thread"""
        super(db,self).start(callback=self._start)
    
    def _start(self):
        try:
            t = self.cfg['db']['type']
            if t.lower() == 'mysql':
                logger.info('attempting to start MySQL db')
                self.db = MySQL(self.cfg)
            elif t.lower() == 'sqlite':
                logger.info('attempting to start SQLite db')
                self.db = SQLite(self.cfg)
            else:
                logger.critical('Unknown database type: %s',t)
                raise Exception('Unknown database type: %s'%t)
            self.db.start()
        except Exception:
            logger.critical('failed to start db',exc_info=True)

    def stop(self):
        if self.db:
            self.db.stop()
        super(db,self).stop()
    
    def kill(self):
        if self.db:
            self.db.stop(force=True)
        super(db,self).kill()
    
    def update_cfg(self,new_cfg):
        self.cfg = new_cfg
        if self.db:
            self.db.update_cfg(new_cfg)

class DBService(module.Service):
    """
    Override the basic :class:`Service` handler to provide a more
    effecient reload method and a backup method. Other methods
    that are not defined are assumed to be DB-specific and are routed
    appropriately.
    """
    def reload(self,cfg,callback=None):
        self.mod.update_cfg(cfg)
        if callback:
            callback()
    def backup(self,callback=None):
        if self.mod.db:
            self.mod.db.backup()
        if callback:
            callback()
    def __nonzero__(self):
        return True
    def __getattr__(self,name):
        logger.debug('getattr('+name+')')
        if self.mod.db and self.mod.db.dbmethods:
            try:
                return getattr(self.mod.db.dbmethods,name)
            except AttributeError:
                logger.warn('method %s not in dbmethods',name,exc_info=True)
        else:
            raise Exception('db is not running')

class Text(str):
    """Define a text type for long strings up to 2^16 char"""
    pass
class MediumText(Text):
    """Define a text type for long strings up to 2^24 char"""
    pass

class DBAPI(object):
    """
    API for database interaction
    """
    
    # define tables
    tables = {'site':OrderedDict([('site_id',str),
                                  ('name',str),
                                  ('institution',str),
                                  ('queues',Text), # json of {gridspec:(type,description)}
                                  ('auth_key',str),
                                  ('website_url',str),
                                  ('version',str),
                                  ('last_update',str), # datetime
                                  ('admin_name',str),
                                  ('admin_email',str),
                                 ]),
              'node':OrderedDict([('node_id',str),
                                  ('hostname',str),
                                  ('domain',str),
                                  ('last_update',str), # datetime
                                  ('stats',Text), # json of {name:value}
                                 ]),
              'dataset':OrderedDict([('dataset_id',str),
                                     ('name',str),
                                     ('description',str),
                                     ('gridspec',Text), # json of {task:[gridspec]}
                                     ('status',str), # possible statuses: {processing, complete, suspended, errors}
                                     ('username',str),
                                     ('institution',str),
                                     ('submit_host',str),
                                     ('priority',int),
                                     ('jobs_submitted',int),
                                     ('trays',int),
                                     ('tasks_submitted',int),
                                     ('start_date',str), # datetime
                                     ('end_date',str), # datetime
                                     ('temporary_storage',Text),
                                     ('global_storage',Text),
                                     ('parent_id',str),
                                     ('stat_keys',Text), # json of [key1,key2]
                                     ('categoryvalue_ids',Text), # list of categoryvalues
                                     ('debug',bool),
                                    ]),
              'dataset_notes':OrderedDict([('dataset_nodes_id',str),
                                           ('dataset_id',str),
                                           ('username',str),
                                           ('date',str), # datetime
                                           ('comment',MediumText),
                                          ]),
              'dataset_stat':OrderedDict([('dataset_stat_id',str),
                                          ('dataset_id',str),
                                          ('stat',MediumText), # json of {name:value}
                                         ]),
              'job':OrderedDict([('job_id',str),
                                 ('status',str), # possible statuses: {processing, complete, suspended, errors}
                                 ('status_changed',str), # datetime
                                ]),
              'job_stat':OrderedDict([('job_stat_id',str),
                                      ('job_id',str),
                                      ('stat',MediumText), # json of {name:value}
                                     ]),
              'task':OrderedDict([('task_id',str),
                                  ('status',str), # possible statuses: {waiting, queued, processing, complete, suspended, failed, resume, reset}
                                  ('prev_status',str),
                                  ('error_message',Text),
                                  ('status_changed',str), # datetime
                                  ('submit_dir',Text),
                                  ('grid_queue_id',str),
                                  ('failures',int),
                                  ('evictions',int),
                                  ('depends',Text), # list of task_ids
                                 ]),
              'task_stat':OrderedDict([('task_stat_id',str),
                                       ('task_id',str),
                                       ('stat',MediumText), # json of {name:value}
                                      ]),
              'task_log':OrderedDict([('task_log_id',str),
                                      ('task_id',str),
                                      ('name',str),
                                      ('data',MediumText),
                                     ]),
              'config':OrderedDict([('config_id',str),
                                    ('dataset_id',str),
                                    ('config_data',MediumText), # serialized
                                    ('difplus_data',MediumText), # serialized
                                   ]),
              'data':OrderedDict([('data_id',str),
                                  ('task_id',str),
                                  ('url',Text),
                                  ('compression',str),
                                  ('type',str),
                                 ]),
              'resource':OrderedDict([('resource_id',str),
                                      ('url',Text),
                                      ('compression',str),
                                      ('arch',str),
                                     ]),
              'categorydef':OrderedDict([('categorydef_id',str),
                                         ('name',str),
                                         ('description',str),
                                        ]),
              'categoryvalue':OrderedDict([('categoryvalue_id',str),
                                           ('categorydef_id',str),
                                           ('name',str),
                                           ('description',Text),
                                          ]),
              'search':OrderedDict([('task_id',str),
                                    ('job_id',str),
                                    ('dataset_id',str),
                                    ('gridspec',str),
                                    ('name',str), # identifies the task in job by name or number
                                    ('task_status',str), # a replica of task:status
                                   ]),
              'history':OrderedDict([('history_id',str),
                                     ('username',str),
                                     ('cmd',Text),
                                     ('timestamp',str), # datetime
                                    ]),
              'passkey':OrderedDict([('passkey_id',str),
                                     ('key',str),
                                     ('expire',str), # datetime
                                    ]),
              'user':OrderedDict([('user_id',str),
                                  ('username',str),
                                  ('password',str),
                                  ('email',str),
                                  ('admin',bool),
                                  ('last_login_time',str), # datetime
                                 ]),
              'session':OrderedDict([('session_id',str),
                                     ('session_key',str),
                                     ('pass_key',str),
                                     ('last_time',str), # datetime
                                    ]),
              'webstat':OrderedDict([('webstat_id',str),
                                     ('name',str),
                                     ('value',MediumText),
                                     ('last_update_time',str), # datetime
                                    ]),
              'webnote':OrderedDict([('webnote_id',str),
                                     ('page',str),
                                     ('username',str),
                                     ('timestamp',str), # datetime
                                     ('note',Text),
                                    ]),
              'graph':OrderedDict([('graph_id',str),
                                   ('name',str),
                                   ('value',Text),
                                   ('timestamp',str), # datetime
                                  ]),
              'cache':OrderedDict([('cache_id',str),
                                   ('permanent_url',Text),
                                   ('uid',str),
                                   ('size',int),
                                   ('checksum',str),
                                   ('checksum_type',str),
                                   ('delete_priority',int),
                                  ]),
              'download':OrderedDict([('download_id',str),
                                      ('permanent_url',Text),
                                      ('size',int),
                                      ('delete_priority',int),
                                     ]),
              'upload':OrderedDict([('upload_id',str),
                                   ('permanent_url',Text),
                                   ('uid',str),
                                   ('size',int),
                                   ('checksum',str),
                                   ('checksum_type',str),
                                   ('status',str),
                                   ('delete_priority',int),
                                  ]),
              'setting':OrderedDict([('setting_id',str),
                                     ('site_id',str),
                                     ('node_offset',str),  # these tables have the site+offset id type
                                     ('dataset_offset',str),
                                     ('dataset_notes_offset',str),
                                     ('dataset_stat_offset',str),
                                     ('job_offset',str),
                                     ('job_stat_offset',str),
                                     ('task_offset',str),
                                     ('task_stat_offset',str),
                                     ('task_log_offset',str),
                                     ('config_offset',str),
                                     ('data_offset',str),
                                     ('resource_offset',str),
                                     ('categorydef_offset',str),
                                     ('categoryvalue_offset',str),
                                     ('history_offset',str),
                                     ('passkey_last',str),
                                     ('user_offset',str),
                                     ('session_last',str),
                                     ('webstat_last',str),
                                     ('webnote_last',str),
                                     ('graph_offset',str),
                                     ('cache_last',str),
                                     ('download_last',str),
                                     ('upload_last',str),
                                    ]),
             }
    archive_tables = ('site','node','dataset','dataset_notes',
                      'dataset_stat','job','job_stat','task','task_stat',
                      'task_log','config','resource','data')
    
    
    ### basic functions ###
    
    def __init__(self, cfg):
        # set cfg
        self.cfg = cfg
        self.dbmethods = None
        
        # thread pools
        self.write_pool = None
        self.read_pool = None
        self.blocking_pool = None # self-imposed blocking of certain sections
        self.non_blocking_pool = None # things that need to run somewhere else
        
        # set up status variables
        self.backup_in_progress = False
        
        self._setup_tables()
        try:
            self.init()
        except:
            logger.error('settings table init failed',exc_info=True)
            raise
    
    def start(self):
        # start thread pools
        self._start_db()
        
        # set up RPCServer
        logger.info('setting dbmethods')
        self.dbmethods = dbmethods.DBMethods(self)
        
    def stop(self,force=False):
        self._stop_db(force=force)
    
    def backup(self):
        if not self.backup_in_progress:
            self.backup_in_progress = True
            logger.warn('Starting backup')
            Thread(target=self._backup_worker).start()
        else:
            logger.warn('Attempted to backup, but backup already in progress')
    
    def update_cfg(self,newcfg):
        """Update config in real time"""
        stop = None
        if (self.cfg['db']['name'] != newcfg['db']['name'] or
            self.cfg['db']['backup_name'] != newcfg['db']['backup_name'] or
            self.cfg['db']['sqlite_cachesize'] != newcfg['db']['sqlite_cachesize']):
            # fundamental db change, need to reset db connection
            stop = 'db'
        if (self.cfg['db']['numthreads'] != newcfg['db']['numthreads']):
            # change in number of threads
            stop = 'dbpools'
        
        if stop == 'db':
            # db pause and resume for read and write pool
            self.write_pool.pause()
            self.read_pool.pause()
            self.cfg = self.newcfg
            self.write_pool.start()
            self.read_pool.start()
        elif stop == 'dbpools':
            # db pause and resume
            self.write_pool.pause()
            self.read_pool.pause()
            self.blocking_pool.pause()
            self.non_blocking_pool.pause()
            self.cfg = self.newcfg
            numthreads = self.cfg['db']['numthreads']
            self.write_pool.start()
            self.read_pool.start(numthreads)
            self.blocking_pool.start()
            self.non_blocking_pool.start(numthreads)
    
    def init(self):
        """Initialize the settings table if there is nothing there"""
        conn,archive_conn = self._dbsetup()
        with conn:
            sql = 'select * from setting where setting_id = 0'
            bindings = tuple()
            ret = self._db_read(conn,sql,bindings,None,None,None)
            if isinstance(ret,Exception):
                raise ret
            elif ret and len(ret) >= 1:
                return
            # table is not initialized, so do so
            sql = 'insert into setting ('
            sql += ','.join(self.tables['setting'].keys())
            sql += ') values ('
            sql += ','.join(['?' for _ in self.tables['setting'].keys()])
            sql += ')'
            bindings = tuple()
            site_id = GlobalID.siteID_gen()
            for key in self.tables['setting']:
                if key == 'setting_id':
                    bindings += (0,)
                elif key == 'site_id':
                    bindings += (site_id,)
                elif key.endswith('_last'):
                    bindings += (GlobalID.int2char(0),)
                elif key.endswith('_offset'):
                    bindings += (GlobalID.globalID_gen(0,site_id),)
                else:
                    raise Exception('unexpected settings key: %s'%key)
            ret = self._db_write(conn,sql,bindings,None,None,None)
            if isinstance(ret,Exception):
                raise ret
    
    def increment_id(self,table):
        """Increment the id of the table, returning the id"""
        return self._increment_id_helper(table)
    
    
    ### Threadpool Tasks ###
    
    def sql_read_task(self,sql=None,bindings=None,archive_sql=None,archive_bindings=None,callback=None):
        """Add task to the read pool"""
        self.read_pool.add_task(self._sql_read_helper,sql,bindings,archive_sql,archive_bindings,callback=callback)
    
    def _sql_read_helper(self,sql=None,bindings=None,archive_sql=None,archive_bindings=None,init=None):
        """
        Read sql from database by calling _db_read()
        
        init = (db_conn,archive_db_conn)
        either read from sql or sql_archive, not both, returning result
        """
        conn, archive_conn = init
        return self._db_read(conn,sql,bindings,archive_conn,archive_sql,archive_bindings)
    
    def sql_write_task(self,sql=None,bindings=None,archive_sql=None,archive_bindings=None,callback=None):
        self.write_pool.add_task(self._sql_write_helper,sql,bindings,archive_sql,archive_bindings,callback=callback)
    
    def _sql_write_helper(self,sql=None,bindings=None,archive_sql=None,archive_bindings=None,tasks=None,init=None):
        """
        Write sql to database by calling _db_write()
        
        init = (db_conn,archive_db_conn)
        if singular, sql and/or sql_archive has executable instructions
        if multiple, tasks has multiple executable instructions
        """
        conn, archive_conn = init
        def w(sql=None,bindings=None,archive_sql=None,archive_bindings=None):
            self._db_write(conn,sql,bindings,archive_conn,archive_sql,archive_bindings)
            
        if sql is not None or archive_sql is not None:
            w(sql,bindings,archive_sql,archive_bindings)
        if tasks is not None:
            for args,kwargs in tasks:
                w(*args,**kwargs)
    
    def blocking_task(self,func,*args,**kwargs):
        self.blocking_pool.add_task(func,*args,**kwargs)
    
    def non_blocking_task(self,func,*args,**kwargs):
        self.non_blocking_pool.add_task(func,*args,**kwargs)
    
    
    ### Functions that can be overwritten in subclasses ###
    
    def _start_db(self):
        # set up threadpools
        numthreads = 1
        if ('db' in self.cfg and 'numthreads' in self.cfg['db'] and
            isinstance(self.cfg['db']['numthreads'],int)):
            numthreads = self.cfg['db']['numthreads']
        logger.info('start %d threadpools',int(numthreads))
        self.write_pool = SingleGrouping(init=self._dbsetup)
        self.write_pool.finish()
        self.write_pool.disable_output_queue()
        self.write_pool.start()
        self.read_pool = PriorityThreadPool(numthreads,init=self._dbsetup)
        self.read_pool.finish()
        self.read_pool.disable_output_queue()
        self.read_pool.start()
        self.blocking_pool = PriorityThreadPool(1)
        self.blocking_pool.finish()
        self.blocking_pool.disable_output_queue()
        self.blocking_pool.start()
        self.non_blocking_pool = PriorityThreadPool(numthreads)
        self.non_blocking_pool.finish()
        self.non_blocking_pool.disable_output_queue()
        self.non_blocking_pool.start()
        logger.debug('started threadpools')
    
    def _stop_db(self,force=False):
        logger.info('stop threadpools')
        self.write_pool.finish(not force)
        self.read_pool.finish(not force)
        self.blocking_pool.finish(not force)
        self.non_blocking_pool.finish(not force)
    
    
    ### Functions that must be overwritten in subclasses ###
    
    def _setup_tables(self):
        """Set up tables if they are not present"""
        raise NotImplementedError()
    
    def _backup_worker(self):
        """Back up databases"""
        raise NotImplementedError()
    
    def _dbsetup(self):
        """Set up database connections.  Should return (conn,archive_conn)"""
        raise NotImplementedError()
    
    def _db_read(self,sql,bindings,archive_sql,archive_bindings):
        """Do a read query from the database"""
        raise NotImplementedError()
    def _db_write(self,sql,bindings,archive_sql,archive_bindings):
        """Do a write query from the database"""
        raise NotImplementedError()
    
    def _increment_id_helper(self,table,conn=None):
        """Increment the id of the table, returning the id"""
        raise NotImplementedError()

try:
    import apsw
except:
    logging.warn('Cannot import apsw. SQLite db not available')
else:
    class SQLite(DBAPI):
        """SQLite 3 implementation of DBAPI"""
        
        def _setup_tables(self):
            """Setup tables, or modify existing tables to match new config"""
            (conn,archive_conn) = self._dbsetup()
            def _create(table_name):
                sql_create = ' ('
                sql_select = ' '
                sep = ''
                cols = self.tables[table_name].keys()
                for col in cols:
                    sql_create += sep+col
                    sql_select += sep+col
                    if sep == '':
                        sql_create += ' PRIMARY KEY' # make first column the primary key
                        sep = ', '
                sql_create += ')'
                scols = set(cols)
                with conn:
                    cur = conn.cursor()  
                    try:
                        curcols = set()
                        for cid,name,type,notnull,dflt,pk in cur.execute("pragma table_info("+table_name+")"):
                            curcols.add(name)
                        if not curcols or len(curcols) < 1:
                            # table does not exist
                            logger.info('create table '+table_name)
                            cur.execute('create table '+table_name+sql_create)
                        elif curcols != scols:
                            # table not the same
                            logger.info('modify table '+table_name)
                            
                            # get similar cols
                            keepcols = curcols & scols
                            
                            full_sql = 'create temporary table '+table_name+'_backup '+sql_create+';'
                            full_sql += 'insert into '+table_name+'_backup select '+','.join(keepcols)+' from '+table_name+';'
                            full_sql += 'drop table '+table_name+';'
                            full_sql += 'create table '+table_name+sql_create+';'
                            full_sql += 'insert into '+table_name+' select '+sql_select+' from '+table_name+'_backup;'
                            full_sql += 'drop table '+table_name+'_backup;'
                            cur.execute(full_sql)
                        else:
                            # table is good
                            logger.info('table '+table_name+' already exists')
                    except apsw.Error, e:
                        # something went wrong
                        logger.warning(e)
                        raise 
            
            for table_name in self.tables.keys():
                _create(table_name)
            for table_name in self.archive_tables:
                _create(table_name)
        
        def _backup_worker(self):
            """Back up databases"""
            try:
                # backup main db
                dbname = self.cfg['db']['name']
                backup_name = self.cfg['db']['backup_name']
                source = apsw.Connection(dbname)
                db = apsw.Connection(backup_name)
                try:
                    with db.backup("main", source, "main") as b:
                        while not b.done:
                            b.step(100)
                finally:
                    source.close()
                    db.close()
                # backup archive db
                dbname = self.cfg['db']['name']+"_archive"
                backup_name = self.cfg['db']['backup_name']+"_archive"
                source = apsw.Connection(dbname)
                db = apsw.Connection(backup_name)
                try:
                    with db.backup("main", source, "main") as b:
                        while not b.done:
                            b.step(100)
                finally:
                    source.close()
                    db.close()
            except Exception as e:
                logger.warning('backup failed with message %s',str(e))
            finally:
                self.backup_in_progress = False
        
        def _dbsetup(self):
            """Set up database connections. Should return (conn,archive_conn)"""
            logger.debug('_dbsetup()')
            name = self.cfg['db']['name']
            kwargs = {}
            if ('db' in self.cfg and 'sqlite_cachesize' in self.cfg['db'] and
                isinstance(self.cfg['db']['sqlite_cachesize'],int)):
                kwargs['statementcachesize'] = self.cfg['db']['sqlite_cachesize']
            conn = apsw.Connection(name,**kwargs)
            archive_conn = apsw.Connection(name+'_archive',**kwargs)
            conn.setbusytimeout(1000)
            archive_conn.setbusytimeout(1000)
            return (conn,archive_conn)
        
        def _db_query(self,con,sql,bindings=None):
            """Make a db query and do error handling"""
            logger.debug('running query %s',sql)
            for i in xrange(27):
                try:
                    if bindings is not None:
                        con.execute(sql,bindings)
                    else:
                        con.execute(sql)
                except (apsw.BusyError,apsw.LockedError):
                    # try again for transient errors, but with random exponential backoff up to 134 sec
                    backoff = random.uniform(0.0,0.000001*(math.pow(2,i)-1))
                    logger.debug('transient error, backoff %d')
                    time.sleep(backoff)
                    continue
                except apsw.Error:
                    raise # just kill for other db errors
                return True
            return False
        
        def _db_read(self,conn,sql,bindings,archive_conn,archive_sql,archive_bindings):
            """Do a read query from the database"""
            ret = None
            try:
                if sql is not None:
                    with conn:
                        cur = conn.cursor()
                        self._db_query(cur,sql,bindings)
                        ret = cur.fetchall()
                elif archive_sql is not None:
                    with archive_conn:
                        archive_cur = archive_conn.cursor()
                        self._db_query(archive_cur,archive_sql,archive_bindings)
                        ret = archive_cur.fetchall()
            except apsw.Error, e:
                if sql is not None:
                    logger.debug('sql: %r',sql)
                    logger.debug('bindings: %r',bindings)
                if archive_sql is not None:
                    logger.debug('archive_sql: %r',archive_sql)
                    logger.debug('archive_bindings: %r',archive_bindings)
                logger.warning(e)
                return e
            logger.debug('_db_read returns %r',ret)
            return ret
        
        def _db_write(self,conn,sql,bindings,archive_conn,archive_sql,archive_bindings):
            """Do a write query from the database"""
            try:
                if sql is not None and archive_sql is not None:
                    with conn,archive_conn:
                        cur = conn.cursor()
                        archive_cur = archive_conn.cursor()
                        if isinstance(sql,basestring):
                            self._db_query(cur,sql,bindings)
                            self._db_query(archive_cur,archive_sql,archive_bindings)
                        elif isinstance(sql,Iterable):
                            for s,b,a_s,a_b in izip(sql,bindings,archive_sql,archive_bindings):
                                self._db_query(cur,s,b)
                                self._db_query(archive_cur,a_s,a_b)
                        else:
                            raise Exception('sql is an unknown type')
                elif sql is not None:
                    with conn:
                        cur = conn.cursor()
                        if isinstance(sql,basestring):
                            self._db_query(cur,sql,bindings)
                        elif isinstance(sql,Iterable):
                            for s,b in izip(sql,bindings):
                                self._db_query(cur,s,b)
                        else:
                            raise Exception('sql is an unknown type')
                elif archive_sql is not None:
                    with archive_conn:
                        archive_cur = archive_conn.cursor()
                        if isinstance(archive_sql,basestring):
                            self._db_query(archive_cur,archive_sql,archive_bindings)
                        elif isinstance(archive_sql,Iterable):
                            for s,b in izip(archive_sql,archive_bindings):
                                self._db_query(archive_cur,s,b)
                        else:
                            raise Exception('archive_sql is an unknown type')
            except apsw.Error, e:
                logger.debug('sql: %r',sql)
                logger.debug('bindings: %r',bindings)
                if archive_sql is not None:
                    logger.debug('archive_sql: %r',archive_sql)
                    logger.debug('archive_bindings: %r',archive_bindings)
                logger.warning(e)
                raise
        
        def _increment_id_helper(self,table,conn=None):
            """Increment the id of the table, returning the id"""
            if not conn:
                conn,archive_conn = self._dbsetup()
            new_id = None
            if table+'_offset' in self.tables['setting']:
                # global id
                with conn:
                    cur = conn.cursor()
                    self._db_query(cur,'select site_id, '+table+'_offset from setting',tuple())
                    ret = cur.fetchall()
                    site_id = ret[0][0]
                    old_id = ret[0][1]
                    old_id = GlobalID.localID_ret(old_id,type='int')
                    new_id = GlobalID.globalID_gen(old_id+1,site_id)
                    self._db_query(cur,'update setting set '+table+'_offset = ?',(new_id,))
            elif table+'_last' in self.tables['setting']:
                # local id
                with conn:
                    cur = conn.cursor()
                    self._db_query(cur,'select '+table+'_last from setting',tuple())
                    ret = cur.fetchall()
                    old_id = ret[0][0]
                    new_id = GlobalID.int2char(GlobalID.char2int(old_id)+1)
                    self._db_query(cur,'update setting set '+table+'_last = ?',(new_id,))
            else:
                raise Exception('not in setting table')
            return new_id

try:
    import MySQLdb
except:
    logging.warn('Cannot import MySQLdb. MySQL db not available')
else:
    class MySQL(DBAPI):
        """MySQL 5 implementation of DBAPI"""
        
        def _setup_tables(self):
            """Setup tables, or modify existing tables to match new config"""
            (conn,archive_conn) = self._dbsetup()
            dbname = self.cfg['db']['name']
            def _create(con,table_name):
                sql_create = ' ('
                sql_select = ' '
                sep = ''
                cols = self.tables[table_name].keys()
                for col in cols:
                    sql_create += sep+col
                    sql_select += sep+col
                    t = self.tables[table_name][col]
                    if t == str:
                        sql_create += ' VARCHAR(255) NOT NULL DEFAULT "" '
                    elif t == int:
                        sql_create += ' INT NOT NULL DEFAULT 0 '
                    elif t == bool:
                        sql_create += ' BOOL NOT NULL DEFAULT 0 '
                    elif t == float:
                        sql_create += ' DOUBLE NOT NULL DEFAULT 0.0 '
                    elif t == Text:
                        sql_create += ' TEXT NOT NULL DEFAULT "" '
                    elif t == MediumText:
                        sql_create += ' MEDIUMTEXT NOT NULL DEFAULT "" '
                    if sep == '':
                        sql_create += ' PRIMARY KEY' # make first column the primary key
                        sep = ', '
                sql_create += ')'
                scols = set(cols)
                try:
                    cur = con.cursor()  
                    try:
                        curcols = set()
                        curdatatypes = {}
                        cur.execute("""select column_name, column_type from information_schema.columns where table_name = '"""+table_name+"""' and table_schema = '"""+dbname+"""'""")
                        for name,datatype in cur.fetchall():
                            curcols.add(name)
                            curdatatypes[name] = datatype
                        if not curcols or len(curcols) < 1:
                            # table does not exist
                            logger.info('create table '+table_name)
                            cur.execute('create table '+table_name+sql_create+' CHARACTER SET utf8 COLLATE utf8_general_ci')
                        elif curcols != scols:
                            # table not the same
                            logger.info('modify table '+table_name)
                            
                            # differences
                            rmcols = curcols - scols
                            addcols = []
                            for x in cols:
                                if x not in curcols:
                                    t = self.tables[table_name][x]
                                    if t == str:
                                        x += ' VARCHAR(255) NOT NULL DEFAULT "" '
                                    elif t == int:
                                        x += ' INT NOT NULL DEFAULT 0 '
                                    elif t == bool:
                                        x += ' BOOL NOT NULL DEFAULT 0 '
                                    elif t == float:
                                        x += ' DOUBLE NOT NULL DEFAULT 0.0 '
                                    elif t == Text:
                                        x += ' TEXT NOT NULL DEFAULT "" '
                                    elif t == MediumText:
                                        sql_create += ' MEDIUMTEXT NOT NULL DEFAULT "" '
                                addcols.append(x)
                            
                            full_sql = 'alter table '+table_name+' add column ('+','.join(addcols)+'), drop column '+', drop column '.join(rmcols)
                            cur.execute(full_sql)
                        else:
                            # table is good
                            logger.info('table '+table_name+' already exists')
                    except MySQLdb.MySQLError, e:
                        # something went wrong
                        logger.warning(e)
                        raise
                except:
                    try:
                        con.rollback()
                    except:
                        pass
                    raise
                else:
                    con.commit()
            
            for table_name in self.tables.keys():
                _create(conn,table_name)
            for table_name in self.archive_tables:
                _create(archive_conn,table_name)
            
        
        def _backup_worker(self):
            """Back up databases"""
            try:
                # backup main db
                name = self.cfg['db']['name']
                mysql_address = self.cfg['db']['mysql_address']
                mysql_port = None
                if ':' in mysql_address:
                    mysql_port = int(mysql_address.rsplit(':',1)[1])
                    mysql_address = mysql_address.rsplit(':',1)[0]
                mysql_username = self.cfg['db']['mysql_username']
                mysql_password = self.cfg['db']['mysql_password']
                kwargs = {'host':mysql_address,
                      'db':name,
                      'user':mysql_username,
                      'passwd':mysql_password,
                      'connect_timeout':10,
                      'use_unicode':True,
                      'charset':'utf8'}
                if mysql_port is not None:
                    kwargs['port'] = mysql_port
                conn = MySQLdb.Connection(**kwargs)
                backup_name = self.cfg['db']['backup_name']
                backup_mysql_address = self.cfg['db']['backup_mysql_address']
                if backup_mysql_address == '':
                    backup_mysql_port = mysql_port
                    backup_mysql_address = mysql_address
                else:
                    mysql_port = None
                    if ':' in mysql_address:
                        backup_mysql_port = int(mysql_address.rsplit(':',1)[1])
                        backup_mysql_address = mysql_address.rsplit(':',1)[0]
                backup_mysql_username = self.cfg['db']['backup_mysql_username']
                if backup_mysql_username == '':
                    backup_mysql_username = mysql_username
                backup_mysql_password = self.cfg['db']['backup_mysql_password']
                if backup_mysql_password == '':
                    backup_mysql_password = mysql_password
                backup_kwargs = {'host':backup_mysql_address,
                      'db':backup_name,
                      'user':backup_mysql_username,
                      'passwd':backup_mysql_password,
                      'connect_timeout':10,
                      'use_unicode':True,
                      'charset':'utf8'}
                if backup_mysql_port is not None:
                    backup_kwargs['port'] = backup_mysql_port
                backup_conn = MySQLdb.Connection(**backup_kwargs)
                self._backup_worker_helper(conn,backup_conn)
                conn.close()
                backup_conn.close()
                # backup archive db
                kwargs['db'] = name+'_archive'
                backup_kwargs['db'] = backup_name+'_archive'
                archive_conn = MySQLdb.Connection(**kwargs)
                backup_archive_conn = MySQLdb.Connection(**kwargs)
                self._backup_worker_helper(archive_conn,backup_archive_conn)
            except Exception as e:
                logger.warning('backup failed',exc_info=True)
            finally:
                self.backup_in_progress = False
        
        def _backup_worker_helper(self,conn,backup_conn):
            """Iterate over tables and backup conn to backup_conn"""
            cursor = conn.cursor()
            backup_cursor = backup_conn.cursor()
            tables = []
            
            def grouper(l):
                try:
                    i = 0
                    step = 100
                    while i < len(l):
                        yield l[i:i+step]
                        i += step
                except:
                    pass
            
            backup_cursor.execute('show tables')
            for row in backup_cursor.fetchall():
                tables.append(row[0])
            
            for table in tables:
                if table not in self.tables:
                    # drop tables that have been deleted
                    backup_cursor.execute('drop table '+table)
                    backup_conn.commit()
                    continue
                
                # update existing tables
                cols = self.tables[table].keys()
                scols = set(cols)
                curcols = set()
                curdatatypes = {}
                backup_cursor.execute("""select column_name, column_type from information_schema.columns where table_name = '"""+table+"""' and table_schema = '"""+dbname+"""'""")
                for name,datatype in backup_cursor.fetchall():
                    curcols.add(name)
                    curdatatypes[name] = datatype
                
                if curcols != scols:
                    # table not the same
                    logger.info('modify table '+table)
                    
                    # differences
                    rmcols = curcols - scols
                    addcols = []
                    for x in cols:
                        if x not in curcols:
                            t = self.tables[table][x]
                            if t == str:
                                x += ' VARCHAR(255) NOT NULL DEFAULT "" '
                            elif t == int:
                                x += ' INT NOT NULL DEFAULT 0 '
                            elif t == bool:
                                x += ' BOOL NOT NULL DEFAULT 0 '
                            elif t == float:
                                x += ' DOUBLE NOT NULL DEFAULT 0.0 '
                            elif t == Text:
                                x += ' TEXT NOT NULL DEFAULT "" '
                            elif t == MediumText:
                                sql_create += ' MEDIUMTEXT NOT NULL DEFAULT "" '
                        addcols.append(x)
                    
                    full_sql = 'alter table '+table+' add column ('+','.join(addcols)+'), drop column '+', drop column '.join(rmcols)
                    cur.execute(full_sql)
                
                ind = cols[0]             
                rowids = set()
                cursor.execute('select '+ind+' from '+table)
                for row in cursor.fetchall():
                    rowids.add(row[0])     
                backup_rowids = set()
                backup_cursor.execute('select '+ind+' from '+table)
                for row in backup_cursor.fetchall():
                    backup_rowids.add(row[0])
                
                delids = backup_rowids - rowids
                addids = rowids - backup_rowids
                updateids = rowids & backup_rowids
                
                # delete old rows
                for d in gen(list(delids)):
                    backup_cursor.execute('delete from '+table+' where '+ind+' in ('+','.join(map(str,d))+')')
                backup_conn.commit()
                
                # insert new rows
                for a in gen(list(addids)):
                    cursor.execute('select * from '+table+' where '+ind+' in ('+','.join(map(str,a))+')')
                    for row in cursor.fetchall():
                        backup_cursor.execute('insert into '+table+' ('+','.join(cols)+') values (\''+'\',\''.join(map(str,row))+'\')')
                    backup_conn.commit()
                
                # update remaining rows
                for a in gen(list(updateids)):
                    cursor.execute('select * from '+table+' where '+ind+' in ('+','.join(map(str,a))+')')
                    for row in cursor.fetchall():
                        backup_cursor.execute('update '+table+' set '+','.join(map(lambda a,b:str(a)+'=\''+str(b)+'\'',cols,row))+' where '+ind+' = '+str(row[0]))
                    backup_conn.commit()
                
            # add tables that don't exist yet
            for table in [x for x in self.tables if x not in tables]:
                sql_create = ' ('
                sep = ''
                cols = self.tables[table].keys()
                for col in cols:
                    sql_create += sep+col
                    t = self.tables[table][col]
                    if t == str:
                        sql_create += ' VARCHAR(255) NOT NULL DEFAULT "" '
                    elif t == int:
                        sql_create += ' INT NOT NULL DEFAULT 0 '
                    elif t == bool:
                        sql_create += ' BOOL NOT NULL DEFAULT 0 '
                    elif t == float:
                        sql_create += ' DOUBLE NOT NULL DEFAULT 0.0 '
                    elif t == Text:
                        sql_create += ' TEXT NOT NULL DEFAULT "" '
                    elif t == MediumText:
                        sql_create += ' MEDIUMTEXT NOT NULL DEFAULT "" '
                    if sep == '':
                        sql_create += ' PRIMARY KEY' # make first column the primary key
                        sep = ', '
                sql_create += ')'
                backup_cursor.execute('create table '+table+sql_create+' CHARACTER SET utf8 COLLATE utf8_general_ci')
                backup_conn.commit()
                
                rowids = []
                ind = cols[0]
                cursor.execute('select '+ind+' from '+table)
                for row in cursor.fetchall():
                    rowids.append(row[0])
                
                for a in gen(rowids):
                    cursor.execute('select * from '+table+' where '+ind+' in ('+','.join(map(str,a))+')')
                    for row in cursor.fetchall():
                        backup_cursor.execute('insert into '+table+' ('+','.join(cols)+') values (\''+'\',\''.join(map(str,row))+'\')')
                    backup_conn.commit()        
        
        def _dbsetup(self):
            """Set up database connections.  Should return (conn,archive_conn)"""
            name = self.cfg['db']['name']
            mysql_address = self.cfg['db']['mysql_address']
            mysql_port = None
            if ':' in mysql_address:
                mysql_port = int(mysql_address.rsplit(':',1)[1])
                mysql_address = mysql_address.rsplit(':',1)[0]
            mysql_username = self.cfg['db']['mysql_username']
            mysql_password = self.cfg['db']['mysql_password']
            kwargs = {'host':mysql_address,
                      'db':name,
                      'user':mysql_username,
                      'passwd':mysql_password,
                      'connect_timeout':10,
                      'use_unicode':True,
                      'charset':'utf8'}
            if mysql_port is not None:
                kwargs['port'] = mysql_port
            conn = MySQLdb.Connection(**kwargs)
            kwargs['db'] = name+'_archive'
            archive_conn = MySQLdb.Connection(**kwargs)
            return (conn,archive_conn)
        
        def _convert_to_mysql(self,sql,bindings):
            num = sql.count('?')
            if num < 1:
                return sql,bindings
                
            if bindings is None:
                raise Exception('bindings is None, but expected %d bindings'%(num,))
            elif num != len(bindings):
                raise Exception('wrong number of bindings - expected %d and got %d'%(num,len(bindings)))
            
            newsql = ''
            pieces = sql.replace('%','%%').split('?')
            for i,s in enumerate(pieces[:-1]):
                b = bindings[i]
                newsql += s
                if isinstance(b,basestring):
                    newsql += '\'%s\''
                elif isinstance(b,(int,long,float)):
                    newsql += '%s'
                else:
                    newsql += '\'%s\''
                    bindings[i] = str(b)
            newsql += pieces[-1]
            
            return newsql,bindings
        
        def _db_query(self,con,sql,bindings=None):
            """Make a db query and do error handling"""
            sql,bindings = self._convert_to_mysql(sql,bindings)
            try:
                if bindings is not None:
                    con.execute(sql,bindings)
                else:
                    con.execute(sql)
            except MySQLdb.MySQLError:
                raise # just kill for other db errors
            return True
        
        def _db_read(self,conn,sql,bindings,archive_conn,archive_sql,archive_bindings):
            """Do a read query from the database"""
            ret = None
            try:
                if sql is not None:
                    try:
                        cur = conn.cursor()
                        self._db_query(cur,sql,bindings)
                        ret = cur.fetchall()
                    except:
                        try:
                            conn.rollback()
                        except:
                            pass
                        raise
                    else:
                        conn.commit()
                elif archive_sql is not None:
                    try:
                        archive_cur = archive_conn.cursor()
                        self._db_query(archive_cur,archive_sql,archive_bindings)
                        ret = archive_cur.fetchall()
                    except:
                        try:
                            archive_conn.rollback()
                        except:
                            pass
                        raise
                    else:
                        archive_conn.commit()
            except MySQLdb.MySQLError, e:
                logger.warning(e)
                return e
            return ret
        
        def _db_write(self,conn,sql,bindings,archive_conn,archive_sql,archive_bindings):
            """Do a write query from the database"""            
            try:
                if sql is not None and archive_sql is not None:
                    try:
                        cur = conn.cursor()
                        archive_cur = archive_conn.cursor()
                        if isinstance(sql,basestring):
                            self._db_query(cur,sql,bindings)
                            self._db_query(archive_cur,archive_sql,archive_bindings)
                        elif isinstance(sql,Iterable):
                            for s,b,a_s,a_b in izip(sql,bindings,archive_sql,archive_bindings):
                                self._db_query(cur,s,b)
                                self._db_query(archive_cur,a_s,a_b)
                        else:
                            raise Exception('sql is an unknown type')
                    except:
                        try:
                            conn.rollback()
                            archive_conn.rollback()
                        except:
                            pass
                        raise
                    else:
                        conn.commit()
                        archive_conn.commit()
                elif sql is not None:
                    try:
                        cur = conn.cursor()
                        if isinstance(sql,basestring):
                            self._db_query(cur,sql,bindings)
                        elif isinstance(sql,Iterable):
                            for s,b in izip(sql,bindings):
                                self._db_query(cur,s,b)
                        else:
                            raise Exception('sql is an unknown type')
                    except:
                        try:
                            conn.rollback()
                        except:
                            pass
                        raise
                    else:
                        conn.commit()
                elif archive_sql is not None:
                    try:
                        archive_cur = archive_conn.cursor()
                        if isinstance(archive_sql,basestring):
                            self._db_query(archive_cur,archive_sql,archive_bindings)
                        elif isinstance(archive_sql,Iterable):
                            for s,b in izip(archive_sql,archive_bindings):
                                self._db_query(archive_cur,s,b)
                        else:
                            raise Exception('sql is an unknown type')
                    except:
                        try:
                            archive_conn.rollback()
                        except:
                            pass
                        raise
                    else:
                        archive_conn.commit()
            except MySQLdb.MySQLError, e:
                logger.warning(e)
                raise
        
        def _increment_id_helper(self,table,conn=None):
            """Increment the id of the table, returning the id"""
            if not conn:
                (conn,archive_conn) = self._dbsetup()
            new_id = None
            if table+'_offset' in self.tables['setting']:
                # global id
                try:
                    cur = conn.cursor()
                    self._db_query(cur,'select site_id, '+table+'_offset from setting',tuple())
                    ret = cur.fetchall()
                    site_id = ret[0][0]
                    old_id = ret[0][1]
                    new_id = GlobalID.globalID_gen(GlobalID.char2int(old_id)+1,site_id)
                    self._db_query(cur,'update setting set '+table+'_offset = ?',(new_id,))
                except:
                    try:
                        conn.rollback()
                    except:
                        pass
                    raise
                else:
                    conn.commit()
            elif table+'_last' in self.tables['setting']:
                # local id
                try:
                    cur = conn.cursor()
                    self._db_query(cur,'select '+table+'_last from setting',tuple())
                    ret = cur.fetchall()
                    old_id = ret[0][0]
                    new_id = GlobalID.int2char(GlobalID.char2int(old_id)+1)
                    self._db_query(cur,'update setting set '+table+'_last = ?',(new_id,))
                except:
                    try:
                        conn.rollback()
                    except:
                        pass
                    raise
                else:
                    conn.commit()
            else:
                raise Exception('not in setting table')
            return new_id
    
    