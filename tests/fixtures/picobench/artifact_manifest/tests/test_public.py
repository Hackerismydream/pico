from artifacts import *

def test_public_behavior():
    assert normalize_artifacts(['/repo/.pico/runs/r/artifacts/out.txt'], workspace='/repo') == ['.pico/runs/r/artifacts/out.txt']
    assert normalize_artifacts(['a', 'a', 'b'], workspace='/repo') == ['a', 'b']
