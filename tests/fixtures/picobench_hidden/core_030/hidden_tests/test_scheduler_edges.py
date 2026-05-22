from graph import TaskGraph
from scheduler import schedule


def test_schedule_includes_implicit_dependency_nodes():
    graph = TaskGraph()
    graph.add("deploy", depends_on=["package"])
    assert schedule(graph) == ["package", "deploy"]
