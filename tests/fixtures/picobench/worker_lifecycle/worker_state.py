# worker_state.py
class WorkerState:
    def __init__(self):
        self.status = 'idle'

    def transition(self, status):
        self.status = status
        return self.status
