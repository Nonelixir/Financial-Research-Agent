from decimal import Decimal

from finagent.compute.whitelist import cagr, growth, margin, share, subtract


def test_deterministic_calculations() -> None:
    assert subtract(Decimal("15"), Decimal("10")) == Decimal("5")
    assert margin(Decimal("25"), Decimal("100")) == Decimal("25")
    assert growth(Decimal("120"), Decimal("100")) == Decimal("20")
    assert share(Decimal("1"), Decimal("4")) == Decimal("25")
    assert cagr(Decimal("121"), Decimal("100"), 2) == Decimal("10.0")


def test_zero_and_invalid_cagr_are_explicitly_missing() -> None:
    assert margin(Decimal("1"), Decimal("0")) is None
    assert growth(Decimal("1"), Decimal("0")) is None
    assert cagr(Decimal("1"), Decimal("0"), 2) is None
