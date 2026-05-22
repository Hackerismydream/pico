import pytest
from dates import parse_iso_date


def test_parse_iso_date_requires_exact_shape():
    with pytest.raises(ValueError):
        parse_iso_date("2026/05/22")
