"""
  Interface for configuring and submitting jobs on a computing cluster. 
  Do not use this class directly. Instead use one of the implementations
  that inherit from this class.
"""

import os
import sys
import random
import math
import logging
from io import BytesIO
from datetime import datetime,timedelta

from iceprod.core import dataclasses
from iceprod.core import functions
from iceprod.core import serialization
from iceprod.server import GlobalID
from iceprod.server import module

logger = logging.getLogger('grid')


class grid(object):
    """
    Interface for a generic job distribution system.
    Do not use this class directly.  Use one of the plugins.
    """
    
    # use only these grid states when defining job status
    GRID_STATES = ('queued','processing','completed','error','unknown')
    
    def __init__(self,args):
        if not isinstance(args,(list,tuple)) or len(args) < 5:
            raise Exception('Bad args - not enough of them')
        self.gridspec = args[0]
        (self.grid_id,self.name) = self.gridspec.split('.')
        self.queue_cfg = args[1]
        self.cfg = args[2]
        self.check_run = args[3]
        if not callable(self.check_run):
            raise Exception('Bad args - check_run (args[3]) is not a function')
        self.db = args[4]
        
        self.submit_dir = os.path.expanduser(os.path.expandvars(
                self.cfg['queue']['submit_dir']))
        if not os.path.exists(self.submit_dir):
            try:
                os.makedirs(self.submit_dir)
            except Exception as e:
                logger.warn('error making submit dir %s',self.submit_dir,
                            exc_info=True)
        
        # get website address
        if ('monitor_address' in self.queue_cfg and 
            self.queue_cfg['monitor_address']):
            self.web_address = self.queue_cfg['monitor_address']
        else:
            self.web_address = functions.gethostname()
            if ('webserver' in self.cfg and 'port' in self.cfg['webserver'] and
                self.cfg['webserver']['port']):
                self.web_address += ':'+str(self.cfg['webserver']['port'])
        
        self.x509 = None # fill with path to proxy cert
        
        self.tasks_queued = 0
        self.tasks_processing = 0
        
        self.submit_multi = False
    
    ### Public Functions ###

    def check_and_clean(self):
        """Check and Clean the Grid"""
        with self.check_run():
            self.check_iceprod()
        with self.check_run():
            self.check_grid()
        with self.check_run():
            self.clean()

    def queue(self):
        """Queue tasks to the grid"""
        tasks = None
        with self.check_run():
            # calculate num tasks to queue
            tasks_on_queue = self.queue_cfg['tasks_on_queue']
            min_tasks = tasks_on_queue[0]
            max_tasks = tasks_on_queue[1]
            change = min_tasks
            if len(tasks_on_queue) > 2:
                change = tasks_on_queue[2]
            
            if max_tasks <= self.tasks_processing + self.tasks_queued:
                change = 0 # already at max
            elif self.tasks_queued >= min_tasks:
                change = 0 # min jobs already queued
            else:
                num_to_queue = max_tasks - self.tasks_processing
                if num_to_queue > min_tasks:
                    num_to_queue = min_tasks - self.tasks_queued
                change = min(change,num_to_queue)
        
            # get queueing datasets from database
            datasets = self.db.get_queueing_datasets(self.gridspec,async=False)
            if isinstance(datasets,Exception):
                raise datasets
            elif not datasets:
                logger.warn('no datasets to queue')
                return
            elif not isinstance(datasets,dict):
                raise Exception('db.get_queueing_datasets(%s) did not return a dict'%self.gridspec)
            
        with self.check_run():
            # assign each dataset a priority
            dataset_prios = {dataset_id:self.calc_dataset_prio(datasets[dataset_id]) for dataset_id in datasets}
            logger.debug('dataset prios: %r',dataset_prios)
            # normalize
            total_prio = math.fsum(dataset_prios.values())
            if total_prio <= 0:
                # datasets do not have priority, so assign all equally
                for d in dataset_prios:
                    dataset_prios[d] = 1.0/len(dataset_prios)
            else:
                for d in dataset_prios:
                    dataset_prios[d] /= total_prio
            
        with self.check_run():
            # get tasks to queue
            tasks = self.db.get_queueing_tasks(dataset_prios,self.gridspec,change,async=False)
            if isinstance(tasks,Exception):
                raise tasks
            if not tasks:
                logger.warn('no tasks to queue, but a dataset can be queued')
                return
            elif not isinstance(tasks,dict):
                raise Exception('db.get_queueing_tasks(%s) did not return a dict'%self.gridspec)
            
        if tasks is not None:
            if self.submit_multi:
                with self.check_run():
                    for t in tasks:
                        # set up submit directory
                        self.setup_submit_directory(tasks[t])
                with self.check_run():
                    # submit to queueing system
                    self.submit(tasks)
            else:
                for t in tasks:
                    with self.check_run():
                        # set up submit directory
                        self.setup_submit_directory(tasks[t])
                        # submit to queueing system
                        self.submit(tasks[t])
            # mark as queued
            self.db.set_task_status([tasks[t]['task_id'] for t in tasks],
                                    'queued',async=False)
            self.tasks_queued += len(tasks)


    ### Private Functions ###

    def check_iceprod(self):
        """check if any task is in a state for too long"""
        tasks = self.db.get_active_tasks(self.gridspec,async=False)
        logger.debug('active tasks: %r',tasks)
        if tasks is None:
            raise Exception('db.get_active_tasks(%s) returned none'%self.gridspec)
        elif isinstance(tasks,Exception):
            raise tasks
        elif not isinstance(tasks,dict):
            raise Exception('db.get_active_tasks(%s) did not return a dict'%self.gridspec)
        
        now = datetime.utcnow()
        reset_tasks = []
        
        # check the queued status
        tasks_queued = 0
        if 'queued' in tasks:
            max_task_queued_time = self.queue_cfg['max_task_queued_time']
            for t in tasks['queued'].values():
                try:
                    if now - t['status_changed'] > timedelta(seconds=max_task_queued_time):
                        reset_tasks.append(t)
                    else:
                        tasks_queued += 1
                except:
                    pass
        self.tasks_queued = tasks_queued
        
        # check the processing status
        tasks_processing = 0
        if 'processing' in tasks:
            max_task_processing_time = self.queue_cfg['max_task_processing_time']
            for t in tasks['processing'].values():
                try:
                    if now - t['status_changed'] > timedelta(seconds=max_task_processing_time):
                        reset_tasks.append(t)
                    else:
                        tasks_processing += 1
                except:
                    pass
        self.tasks_processing = tasks_processing
        
        # check the resume,reset status
        max_task_reset_time = self.queue_cfg['max_task_reset_time']
        if 'reset' in tasks:
            for t in tasks['reset'].values():
                try:
                    if now - t['status_changed'] > timedelta(seconds=max_task_reset_time):
                        reset_tasks.append(t)
                except:
                    pass
        if 'resume' in tasks:
            for t in tasks['resume'].values():
                try:
                    if now - t['status_changed'] > timedelta(seconds=max_task_reset_time):
                        reset_tasks.append(t)
                except:
                    pass
        
        if len(reset_tasks) > 0:
            # reset some tasks
            max_resets = self.cfg['queue']['max_resets']
            failures = []
            resets = []
            for t in reset_tasks:
                if t['failures'] >= max_resets:
                    failures.append(t['task_id'])
                else:
                    resets.append(t['task_id'])
            ret = self.db.reset_tasks(reset=resets,fail=failures,async=False)
            if isinstance(ret,Exception):
                raise ret
    
    def check_grid(self):
        """check the queueing system for problems"""
        # check if any task is in a state for too long
        tasks = self.get_task_status()
        if tasks is None:
            raise Exception('get_task_status() on %s returned none'%self.gridspec)
        elif not isinstance(tasks,dict):
            raise Exception('get_task_status() on %s did not return a dict'%self.gridspec)
        if tasks is None:
            raise Exception('get_task_status() on %s returned none'%self.gridspec)
        elif isinstance(tasks,Exception):
            raise tasks
        elif not isinstance(tasks,dict):
            raise Exception('get_task_status() on %s did not return a dict'%self.gridspec)
        
        now = datetime.utcnow()
        reset_tasks = []
        
        # check the queued status
        if 'queued' in tasks:
            max_task_queued_time = self.queue_cfg['max_task_queued_time']
            for t in tasks['queued'].values():
                try:
                    if now - t['status_changed'] > timedelta(seconds=max_task_queued_time):
                        reset_tasks.append(t)
                except:
                    pass
        
        # check the processing status
        if 'processing' in tasks:
            max_task_processing_time = self.queue_cfg['max_task_processing_time']
            for t in tasks['processing'].values():
                try:
                    if now - t['status_changed'] > timedelta(seconds=max_task_processing_time):
                        reset_tasks.append(t)
                except:
                    pass
        
        # check the error status
        if 'error' in tasks:
            for t in tasks['error'].values():
                reset_tasks.append(t)
        if 'unknown' in tasks:
            for t in tasks['unknown'].values():
                reset_tasks.append(t)
        
        if len(reset_tasks) > 0:
            # reset some tasks
            max_resets = self.cfg['queue']['max_resets']
            failures = []
            resets = []
            for t in reset_tasks:
                if t['failures'] >= max_resets:
                    failures.append(t['task_id'])
                else:
                    resets.append(t['task_id'])
            ret = self.db.reset_tasks(reset=resets,fail=failures,async=False)
            if isinstance(ret,Exception):
                raise ret
    
    def clean(self):
        """Clean submit dirs and the grid system. Reset tasks."""
        submit_dir = self.submit_dir
        suspend_time = self.queue_cfg['suspend_submit_dir_time']
        now = datetime.utcnow()
        
        delete_list = set()
        tasks = {}
        reset_tasks = set()
        
        # get active tasks
        active_tasks = self.db.get_active_tasks(self.gridspec,async=False)
        if active_tasks is None:
            raise Exception('db.get_active_tasks(%s) returned none'%self.gridspec)
        elif isinstance(active_tasks,Exception):
            raise active_tasks
        elif not isinstance(active_tasks,dict):
            raise Exception('db.get_active_tasks(%s) did not return a dict'%self.gridspec)
        
        if 'queued' in active_tasks:
            tasks.update(active_tasks['queued'])
        if 'processing' in active_tasks:
            tasks.update(active_tasks['processing'])
        if 'reset' in active_tasks:
            tasks.update(active_tasks['reset'])
            reset_tasks.update(active_tasks['reset'])
            for t in active_tasks['reset'].values():
                delete_list.add(t['submit_dir'])
        if 'resume' in active_tasks:
            tasks.update(active_tasks['resume'])
            reset_tasks.update(active_tasks['resume'])
            for t in active_tasks['resume'].values():
                delete_list.add(t['submit_dir'])
        
        # check for directories that don't have an active task run in the last day
        for x in os.listdir(submit_dir):
            d = os.path.join(submit_dir,x)
            if os.path.isdir(d) and '_' in x:
                logger.debug('found submit_dir %s',d)
                key = x.split('_')[0]
                if key in tasks and tasks[key]['submit_dir'] == d:
                    logger.debug('skip submit_dir for active task')
                    continue # skip for active task
                mtime = datetime.utcfromtimestamp(os.path.getmtime(d))
                if mtime >= now-timedelta(seconds=suspend_time):
                    logger.debug('skip submit_dir for recent suspended task')
                    continue # skip for suspended or failed tasks
                delete_list.add(d)
        
        # delete dirs that need deleting
        for t in delete_list:
            if not t.startswith(submit_dir):
                # some security against nefarious things
                raise Exception('directory %s not in submit_dir %s'%(t,submit_dir))
            try:
                logger.info('deleting submit_dir %s',t)
                functions.removedirs(t)
            except:
                logger.warn('could not delete submit dir %s',t,exc_info=True)
                continue
        
        # check grid system
        grid_tasks = self.get_task_status()
        if grid_tasks is None:
            raise Exception('get_task_status() on %s returned none'%self.gridspec)
        elif not isinstance(grid_tasks,dict):
            raise Exception('get_task_status() on %s did not return a dict'%self.gridspec)
        
        # resolve mixups between grid system and iceprod
        grid_reset_list = {}
        for s in grid_tasks:
            if s in ('error','unknown'):
                grid_reset_list.update(grid_tasks[s])
        for t in tasks:
            for s in grid_tasks:
                if s in ('error','unknown') and t in grid_tasks[s]:
                    if tasks[t]['status'] in ('queued','processing'):
                        logger.warn('resetting task %s',t)
                        reset_tasks.add(t)
                    grid_reset_list[t] = grid_tasks[s][t]
        if grid_reset_list:
            self.remove(grid_reset_list)
        
        if reset_tasks:
            # reset some tasks
            ret = self.db.set_task_status(reset_tasks,'waiting',async=False)
            if isinstance(ret,Exception):
                raise ret

    def setup_submit_directory(self,task):
        """Set up submit directory"""
        # create directory for task
        submit_dir = self.submit_dir
        task_dir = os.path.join(submit_dir,task['task_id']+'_'+str(random.randint(0,1000000)))
        while os.path.exists(task_dir):
            task_dir = os.path.join(submit_dir,task['task_id']+'_'+str(random.randint(0,1000000)))
        task_dir = os.path.abspath(os.path.expanduser(os.path.expandvars(task_dir)))
        os.makedirs(task_dir)
        task['submit_dir'] = task_dir
        
        # symlink or copy the .sh file
        src = os.path.expanduser(os.path.expandvars(
                  os.path.join('$I3PREFIX','bin','loader.sh')))
        try:
            os.symlink(src,os.path.join(task_dir,'loader.sh'))
        except Exception as e:
            try:
                functions.copy(src,os.path.join(task_dir,'loader.sh'))
            except Exception as e:
                logger.error('Error creating symlink or copy of .sh file: %s',e,exc_info=True)
                raise
        
        # get passkey
        expiration = datetime.utcnow()
        expiration += timedelta(seconds=self.queue_cfg['max_task_queued_time'])
        expiration += timedelta(seconds=self.queue_cfg['max_task_processing_time'])
        expiration += timedelta(seconds=self.queue_cfg['max_task_reset_time'])
        ret = self.db.new_passkey(expiration,async=False)
        if isinstance(ret,Exception):
            logger.error('error getting passkey for task_id %r',
                         task['task_id'])
            raise ret
        passkey = ret
        
        cfg = None
        if task['task_id'] != 'pilot':
            # write cfg
            cfg = self.write_cfg(task)
            
            # update DB
            logger.info('task %s has new submit_dir %s',task['task_id'],task_dir)
            ret = self.db.set_submit_dir(task['task_id'],task_dir,async=False)
            if isinstance(ret,Exception):
                logger.error('error updating DB with submit_dir')
                raise ret
        
        # create submit file
        try:
            self.generate_submit_file(task,cfg=cfg,passkey=passkey)
        except Exception as e:
            logger.error('Error generating submit file: %s',e,exc_info=True)
            raise
    
    def write_cfg(self,task):
        """Write the config file for a task"""
        filename = os.path.join(task['submit_dir'],'task.cfg')
        
        # get config from database
        ret = self.db.get_cfg_for_task(task['task_id'],async=False)
        if isinstance(ret,Exception):
            logger.error('error getting task cfg for task_id %r',
                         task['task_id'])
            raise ret
        config = serialization.serialize_json.loads(ret)
        
        # add server options
        config['options']['task_id'] = task['task_id']
        config['options']['task'] = task['name']
        config['options']['stillrunninginterval'] = self.queue_cfg['ping_interval']
        config['options']['debug'] = task['debug']
        config['options']['upload'] = 'logging'
        if ('download' in self.cfg and 'http_username' in self.cfg['download']
            and self.cfg['download']['http_username']):
            config['options']['http_username'] = self.cfg['download']['http_username']
        if ('download' in self.cfg and 'http_password' in self.cfg['download']
            and self.cfg['download']['http_password']):
            config['options']['http_password'] = self.cfg['download']['http_password']
        if self.x509:
            config['options']['x509'] = self.x509
        
        # write to file
        serialization.serialize_json.dump(config,filename)
        
        return config
    
    def calc_dataset_prio(self,dataset):
        """Calculate the dataset priority.  Takes a dataset with 'dataset_id', 'priority' and 'tasks_submitted'"""
        # get priority factors
        qf_p = self.queue_cfg['queueing_factor_priority']
        qf_d = self.queue_cfg['queueing_factor_dataset']
        qf_t = self.queue_cfg['queueing_factor_tasks']
        
        # get dataset info
        p = dataset['priority']
        if p < 0 or p > 100:
            # do not allow negative or overly large priorities (they skew things)
            p = 0
            logger.warning('Priority for dataset %s is invalid, using default',dataset['dataset_id'])
        d = GlobalID.localID_ret(dataset['dataset_id'],type='int')
        if d < 0:
            d = 0
            logger.warning('Dataset for dataset %s is invalid, using default',dataset['dataset_id'])
        t = dataset['tasks_submitted']
        
        # return prio
        if t < 1:
            prio = (qf_p/10.0*p-qf_d/10000.0*d)
        else:
            prio = (qf_p/10.0*p-qf_d/10000.0*d-qf_t/10.0*math.log10(t))
        if prio < 0:
            prio = 0
            logger.error('Dataset prio for dataset %s is <0',dataset['dataset_id'])
        return prio
    
    
    ### Plugin Overrides ###
    
    def get_task_status(self,task_id=None):
        """Get task status from queueing system.
           Get all task statuses if id is not specified.
           Returns {status:{task_id:task}}
        """
        # the DB method get_task_by_grid_queue_id() may be useful
        return {}
    
    def generate_submit_file(self,task,cfg=None,passkey=None):
        """Generate queueing system submit file for task in dir."""
        raise NotImplementedError()
    
    def submit(self,task):
        """Submit task(s) to queueing system."""
        raise NotImplementedError()
    
    def remove(self,tasks=None):
        """Remove task(s) from queueing system.  Remove all tasks if tasks is None."""
        pass
    
    def task_to_grid_name(self,task):
        """Convert from task to grid_name"""
        # default queued task name: i(task_id)
        # starts with i to be first-char alphabetic (required by pbs)
        return 'i%s'%(task['task_id'])
    
    def grid_name_to_task_id(self,grid_name):
        """Convert from grid name to task_id"""
        if grid_name[0] == 'i':
            task_id = grid_name[1:]
            return task_id
        else:
            raise Exception('bad grid name')
