from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation

HUNDRED = Decimal(100)


def subtract(current: Decimal, prior: Decimal) -> Decimal:
    return current - prior


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    try:
        if denominator == 0:
            return None
        return numerator / denominator
    except (DivisionByZero, InvalidOperation):
        return None


def margin(profit: Decimal, revenue: Decimal) -> Decimal | None:
    value = ratio(profit, revenue)
    return value * HUNDRED if value is not None else None


def growth(current: Decimal, prior: Decimal) -> Decimal | None:
    if prior == 0:
        return None
    return (current - prior) / abs(prior) * HUNDRED


def cagr(end_value: Decimal, start_value: Decimal, years: int) -> Decimal | None:
    if years <= 0 or start_value <= 0 or end_value < 0:
        return None
    return ((end_value / start_value) ** (Decimal(1) / Decimal(years)) - 1) * HUNDRED


def share(part: Decimal, whole: Decimal) -> Decimal | None:
    value = ratio(part, whole)
    return value * HUNDRED if value is not None else None


def quantize_for_display(value: Decimal, places: int = 2) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum)
