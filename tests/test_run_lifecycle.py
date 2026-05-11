import inspect


def test_run_lifecycle_boundary_exists():
    from pico.core.run_lifecycle import RunLifecycle

    lifecycle = RunLifecycle()
    assert lifecycle is not None
    assert callable(lifecycle.execute_tool_step)
    assert callable(lifecycle.finish_run)


def test_pico_lifecycle_methods_are_wrappers():
    import pico.core.agent as agent_module

    execute_source = inspect.getsource(agent_module.Pico._execute_tool_step)
    finish_source = inspect.getsource(agent_module.Pico._finish_run)

    assert "RunLifecycle" in execute_source or "run_lifecycle" in execute_source
    assert "RunLifecycle" in finish_source or "run_lifecycle" in finish_source
    assert len(execute_source.splitlines()) <= 30
    assert len(finish_source.splitlines()) <= 30
