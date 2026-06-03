from worker_state import WorkerState

def test_unknown_state_rejected():
    state = WorkerState()
    try:
        state.transition('paused')
    except ValueError:
        pass
    else:
        raise AssertionError('unknown state should fail')
