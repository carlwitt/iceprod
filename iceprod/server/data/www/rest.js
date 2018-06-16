/*
 * Helper functions that use REST API
 */

async function fetch_json(url, passkey, json=null, post=false) {
    try {
        var payload = {
                headers: new Headers({
                                'Authorization': 'Bearer ' + passkey,
                                'Content-Type': 'application/json',
                            }),
        };
        if (json) {
            payload['body'] = JSON.stringify(json);
            payload['method'] = post ? 'POST' : 'PUT';
        }
        var response = await fetch(url, payload);
        return await response.json();
    } catch(err) {
        alert(err);
    }
}

function set_dataset_status(dataset_id, stat, passkey, task_status_filters=[''], propagate=true) {
    if (propagate) {
        let jobs = fetch_json('/datasets/' + dataset_id + '/jobs', passkey);
        set_jobs_status(jobs.keys(), stat, passkey, task_status_filters);
    }
    fetch_json('/datasets/' + dataset_id + '/status', passkey, {'status':stat});
}

function set_jobs_status(job_ids, stat, passkey, task_status_filters=['']) {
    for (jid in job_ids) {
        var job = fetch_json('/jobs/' + jid, passkey);
        for (status_filter in task_status_filters) {
            let filter = status_filter ? '&task_status=' + status_filter : '';
            let tasks = fetch_json('/datasets/' + job['dataset_id'] + '/tasks?job_id=' + job['job_id'] + filter, passkey);
            set_tasks_status(tasks.keys(), stat, passkey);
        }
        fetch_json('/datasets/' + job['dataset_id'] + '/jobs/' + jid + '/status', passkey, {'status':stat});
    }
}

function set_tasks_status(task_ids, stat, passkey) {
    for (tid in task_ids) {
        let task = fetch_json('/tasks/' + tid, passkey);
        fetch_json('/datasets/' + task['dataset_id'] + '/tasks/' + task['task_id'] + '/status', passkey, {'status':stat});
    }
}

function set_tasks_and_jobs_status(task_ids, stat, passkey) {
    for (tid in task_ids) {
        let task = fetch_json('/tasks/' + tid, passkey);
        fetch_json('/datasets/' + task['dataset_id'] + '/tasks/' + task['task_id'] + '/status', passkey, {'status':stat});
        fetch_json('/datasets/' + task['dataset_id'] + '/jobs/' + task['job_id'] + '/status', passkey, {'status':stat});
    }
}
