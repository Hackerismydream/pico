from dep_graph import topo_sort


def test_dependencies_come_before_dependents():
    assert topo_sort({'test': ['build'], 'build': []}) == ['build', 'test']
