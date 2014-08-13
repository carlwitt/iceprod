"""
The queue module is responsible for interacting with the local batch or
queueing system, putting tasks on the queue and removing them as necessary.
"""

import time
from threading import Thread,Event,Condition
import logging
from contextlib import contextmanager
from itertools import izip

import iceprod.server
from iceprod.server import module
import iceprod.core.functions

class StopException(Exception):
    pass

logger = logging.getLogger('modules_queue')

class queue(module.module):
    """
    Run the queue module, which queues jobs onto the local grid system(s).
    """
    
    def __init__(self,*args,**kwargs):
        # run default init
        super(queue,self).__init__(*args,**kwargs)
        
        # set up local variables
        self.queue_stop = Event()
        self.queue_thread = None
        self.thread_running = 0
        self.thread_running_cv = Condition()
        
        self.start()
    
    def start(self):
        """Start thread if not already running"""
        # start messaging
        super(queue,self).start(callback=self._start)
    
    def stop(self):
        """Stop queue loop"""
        # set the exit flag
        self.queue_stop.set()
        
        # wait until current threads have finished
        self.thread_running_cv.acquire()
        i = 0
        while self.thread_running > 0 and i < 300: # wait a max of 5 min
            self.thread_running_cv.wait(1) 
            i += 1
        self.thread_running_cv.release()
        
        # stop messaging
        super(queue,self).stop()
    
    def kill(self):
        """Kill queue loop"""
        self.queue_stop.set()
        # let process eat any hanging thread
        
        # stop messaging
        super(queue,self).kill()
    
    def _start(self):
        if self.queue_thread is None or not self.queue_thread.is_alive():
            # start queueing thread
            self.queue_stop.clear()
            self.thread_running = 0
            self.queue_thread = Thread(target=self.queue_loop)
            self.queue_thread.start()
    
    @contextmanager
    def check_run(self):
        """A context manager which keeps track of # of running threads"""
        if self.queue_stop.is_set():
            raise StopException('stop requested')
        self.thread_running_cv.acquire()
        self.thread_running += 1
        self.thread_running_cv.release()
        try:
            yield
        finally:
            self.thread_running_cv.acquire()
            self.thread_running -= 1
            self.thread_running_cv.notify_all()
            self.thread_running_cv.release()
    
    def queue_loop(self):
        """Run the queueing loop"""
        # get site_id
        site_id = self.cfg['site_id']
        
        # some setup
        plugins = []
        plugin_names = [x for x in self.cfg['queue'] if isinstance(self.cfg['queue'][x],dict)]
        plugin_cfg = [self.cfg['queue'][x] for x in plugin_names]
        plugin_types = [x['type'] for x in plugin_cfg]
        logger.info('queueing plugins in cfg: %r',{x:y for x,y in izip(plugin_names,plugin_types)})
        if not plugin_names:
            logger.debug('%r',self.cfg['queue'])
            logger.warn('no queueing plugins found. deactivating queue')
            self.stop()
            return
        
        # try to find plugins
        raw_types = iceprod.server.listmodules('iceprod.server.plugins')
        logger.info('available modules: %r',raw_types)
        plugins_tmp = []
        for i,t in enumerate(plugin_types):
            t = t.lower()
            p = None
            for r in raw_types:
                r_name = r.rsplit('.',1)[1].lower()
                if r_name == t:
                    # exact match
                    logger.debug('exact plugin match - %s',r)
                    p = r
                    break
                elif t.startswith(r_name):
                    # partial match
                    if p is None:
                        logger.debug('partial plugin match - %s',r)
                        p = r
                    else:
                        name2 = p.rsplit('.',1)[1]
                        if len(r_name) > len(name2):
                            logger.debug('better plugin match - %s',r)
                            p = r
            if p is not None:
                plugins_tmp.append((p,plugin_names[i],plugin_cfg[i]))
            else:
                logger.error('Cannot find plugin for grid %s of type %s',plugin_names[i],t)
        
        # instantiate all plugins that are required
        gridspec_types = {}
        for p,p_name,p_cfg in plugins_tmp:
            logger.warn('queueing plugin found: %s = %s',p_name,p_cfg['type'])
            # try instantiating the plugin
            args = (site_id+'.'+p_name, p_cfg, self.cfg,
                    self.check_run, self.messaging.db)
            try:
                plugins.append(iceprod.server.run_module(p,args))
            except Exception as e:
                logger.error('Error importing plugin',exc_info=True)
            else:
                gridspec_types[site_id+'.'+p_name] = [p_cfg['type'],p_cfg['description']]
        
        # add gridspec and types to the db
        try:
            self.messaging.db.set_site_queues(site_id,gridspec_types,async=False)
        except:
            logger.warn('error setting site queues',exc_info=True)
        
        # the queueing loop
        # give 10 second initial delay to let the rest of iceprod start
        timeout = 10
        if 'queue' in self.cfg and 'init_queue_interval' in self.cfg['queue']:
            timeout = self.cfg['queue']['init_queue_interval']
        try:
            while not self.queue_stop.wait(timeout):
                # check and clean grids
                for p in plugins:
                    with self.check_run():
                        try:
                            p.check_and_clean()
                        except Exception:
                            logger.error('plugin %s.check_and_clean() raised exception',
                                         p.__class__.__name__,exc_info=True)
                
                with self.check_run():
                    # check proxy cert
                    try:
                        self.check_proxy()
                    except Exception:
                        logger.error('error checking proxy',exc_info=True)
                
                with self.check_run():
                    # make sure active datasets have jobs and tasks defined
                    gridspecs = [p.gridspec for p in plugins]
                    try:
                        self.buffer_jobs_tasks(gridspecs)
                    except Exception:
                        logger.error('error buffering jobs and tasks',
                                     exc_info=True)
                
                # queue tasks to grids
                for p in plugins:
                    with self.check_run():
                        try:
                            p.queue()
                        except Exception:
                            logger.error('plugin %s.queue() raised exception',
                                         p.__class__.__name__,exc_info=True)
                
                with self.check_run():
                    # do global queueing
                    # TODO: implement this
                    pass
                
                # set timeout
                timeout = self.cfg['queue']['queue_interval']
                if timeout <= 0:
                    timeout = 300
        except StopException:
            logger.info('queue_loop stopped normally')
        except Exception as e:
            logger.warn('queue_loop stopped because of exception',
                               exc_info=True)
    
    def check_proxy(self):
        """Check the proxy"""
        # TODO: implement this
        pass
    
    def buffer_jobs_tasks(self,gridspecs):
        """Make sure active datasets have jobs and tasks defined"""
        buffer = self.cfg['queue']['task_buffer']
        if buffer <= 0:
            buffer = 200
        ret = self.messaging.db.buffer_jobs_tasks(gridspecs,buffer,async=False)
        if isinstance(ret,Exception):
            raise ret