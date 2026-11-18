"""Unit conversion never silently drops or invents a unit."""
import pytest

from reviewer.ingest import units


def test_convert_hours_to_minutes():
    assert units.convert(0.5, "hours", "minutes") == 30


def test_no_source_unit_means_field_unit():
    assert units.convert(25, None, "minutes") == 25


def test_unit_on_unitless_field_is_an_error():
    with pytest.raises(units.UnitError):
        units.convert(5, "minutes", None)


def test_unknown_unit_is_an_error():
    with pytest.raises(units.UnitError):
        units.convert(5, "fortnights", "minutes")
