"""
Monitor the datasets.

Send monitoring data to graphite.

Initial delay: rand(1 minute)
Periodic delay: 5 minutes
"""

import logging
import random
import time

from tornado.ioloop import IOLoop

from iceprod.server import GlobalID

logger = logging.getLogger('dataset_monitor')

def dataset_monitor(module):
    """
    Initial entrypoint.

    Args:
        module (:py:class:`iceprod.server.modules.schedule`): schedule module
    """
    # initial delay
    IOLoop.current().call_later(random.randint(5,60), run,
                                module.rest_client, module.statsd)

async def run(rest_client, statsd, debug=False):
    """
    Actual runtime / loop.

    Args:
        rest_client (:py:class:`iceprod.core.rest_client.Client`): rest client
        statsd (:py:class:`statsd.StatsClient`): statsd (graphite) client
        debug (bool): debug flag to propagate exceptions
    """
    start_time = time.time()
    try:
        datasets = await rest_client.request('GET', '/dataset_summaries/status')
        for status in datasets:
            for dataset_id in datasets[status]:
                dataset = await rest_client.request('GET', '/datasets/{}'.format(dataset_id))
                dataset_num = dataset['dataset']
                jobs = await rest_client.request('GET', '/datasets/{}/job_counts/status'.format(dataset_id))
                for status in jobs:
                    statsd.gauge('datasets.{}.jobs.{}'.format(dataset_num,status), jobs[status])
                tasks = await rest_client.request('GET', '/datasets/{}/task_counts/name_status'.format(dataset_id))
                for name in tasks:
                    for status in tasks[name]:
                        statsd.gauge('datasets.{}.tasks.{}.{}'.format(dataset_num,name,status), tasks[name][status])
    except Exception:
        logger.error('error monitoring datasets', exc_info=True)
        if debug:
            raise

    # run again after 60 minute delay
    stop_time = time.time()
    delay = max(60*5 - (stop_time-start_time), 60)
    IOLoop.current().call_later(delay, run, rest_client, statsd)
