from datetime import date
import pytest
from dates import parse_iso_date


def test_parse_iso_date_returns_date():
    assert parse_iso_date("2026-05-22") == date(2026, 5, 22)


def test_parse_iso_date_rejects_invalid():
    with pytest.raises(ValueError):
        parse_iso_date("2026-99-99")
