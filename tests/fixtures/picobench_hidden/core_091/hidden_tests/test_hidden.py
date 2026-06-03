from dep_graph import topo_sort


def test_cycle_is_rejected():
    try:
        topo_sort({'a': ['b'], 'b': ['a']})
    except ValueError:
        pass
    else:
        raise AssertionError('cycle should fail')
