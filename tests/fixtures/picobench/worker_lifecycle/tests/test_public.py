from worker_state import WorkerState

def test_worker_lifecycle_rejects_restarting_completed():
    state = WorkerState()
    assert state.transition('queued') == 'queued'
    assert state.transition('running') == 'running'
    assert state.transition('completed') == 'completed'
    try:
        state.transition('running')
    except ValueError:
        pass
    else:
        raise AssertionError('completed worker must be terminal')

def test_worker_lifecycle_rejects_unknown_state():
    state = WorkerState()
    try:
        state.transition('paused')
    except ValueError:
        pass
    else:
        raise AssertionError('unknown state should fail')
