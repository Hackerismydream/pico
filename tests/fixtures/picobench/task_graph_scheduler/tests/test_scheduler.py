import pytest
from graph import TaskGraph
from scheduler import schedule


def test_schedule_respects_dependencies():
    graph = TaskGraph()
    graph.add("test", depends_on=["build"])
    graph.add("build", depends_on=["lint"])
    graph.add("lint")
    assert schedule(graph) == ["lint", "build", "test"]


def test_schedule_rejects_cycles():
    graph = TaskGraph()
    graph.add("a", depends_on=["b"])
    graph.add("b", depends_on=["a"])
    with pytest.raises(ValueError):
        schedule(graph)
