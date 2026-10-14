"""Readable presentation without changing registered financial values."""

from decimal import ROUND_HALF_UP, Decimal, localcontext


def display_result(value: Decimal, unit: str, decimal_places: int = 2) -> dict:
    if type(decimal_places) is not int or not 0 <= decimal_places <= 4:
        raise ValueError("Display decimal places must be an integer between 0 and 4")
    scale = Decimal(1)
    display_unit = unit
    if unit == "USD":
        if abs(value) >= 1_000_000_000:
            scale, display_unit = Decimal(1_000_000_000), "USD billion"
        elif abs(value) >= 1_000_000:
            scale, display_unit = Decimal(1_000_000), "USD million"
    with localcontext() as context:
        context.prec = max(34, value.adjusted() + decimal_places + 4)
        rounded = (value / scale).quantize(
            Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_UP
        )
        if rounded == 0:
            rounded = abs(rounded)
        amount = format(rounded, f",.{decimal_places}f")
        was_rounded = rounded * scale != value
    if unit == "USD":
        suffix = display_unit.removeprefix("USD").strip()
        text = f"USD {amount}" + (f" {suffix}" if suffix else "")
    else:
        text = f"{amount}%" if unit == "percent" else f"{amount} {display_unit}"
    return {
        "text": text,
        "amount": amount,
        "unit": display_unit,
        "scale": str(scale),
        "decimal_places": decimal_places,
        "rounded": was_rounded,
    }
