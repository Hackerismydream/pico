from artifact_locator import locate_artifacts


def test_absolute_and_parent_paths_are_rejected(tmp_path):
    for value in ['/tmp/x', '../x']:
        try:
            locate_artifacts(tmp_path, {'evidence_paths': [value]})
        except ValueError:
            pass
        else:
            raise AssertionError(f'{value} should fail')
