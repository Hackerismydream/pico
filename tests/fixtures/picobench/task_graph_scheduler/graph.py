class TaskGraph:
    def __init__(self):
        self.deps = {}

    def add(self, task, depends_on=None):
        self.deps[task] = list(depends_on or [])
