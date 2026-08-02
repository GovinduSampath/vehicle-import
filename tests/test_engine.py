"""Golden tests: the safety net that lets you change tax rules fearlessly.

Each case is a vehicle, a date, and the exact rupee figure the engine must
produce. Work each one out by hand once, write it down, and never let it drift.
When a gazette changes the rules you add a NEW dated case -- the old ones must
keep passing, because history does not change.

Replace these with figures you have verified against a real customs
assessment. Right now they only prove the engine composes levies correctly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.tax.engine import Vehicle, calculate
from app.tax.loader import RuleError, load_rulesets, ruleset_for

D = Decimal


def quote_for(vehicle: Vehicle, as_of: date):
    return calculate(vehicle, ruleset_for(as_of))


GOLDEN_CASES = [
    (
        "kei 659cc -- PiXAMP worked example, CIF 20,000 JPY @ 2.03",
        Vehicle(
            fob=D("40600"),
            freight=D("0"),
            insurance=D("0"),
            fuel="petrol",
            engine_cc=659,
            motor_kw=0,
        ),
        date(2026, 5, 20),
        D("2480525.86"),
    ),
    (
        "1800cc petrol inside the surcharge window",
        Vehicle(
            fob=D("8200000"),
            freight=D("0"),
            insurance=D("0"),
            fuel="petrol",
            engine_cc=1800,
            motor_kw=0,
        ),
        date(2026, 5, 20),
        D("30854345.00"),
    ),
    (
        "same car six days earlier, no surcharge",
        Vehicle(
            fob=D("8200000"),
            freight=D("0"),
            insurance=D("0"),
            fuel="petrol",
            engine_cc=1800,
            motor_kw=0,
        ),
        date(2026, 5, 10),
        D("29366660.00"),
    ),
    (
        "100kW EV above the luxury threshold",
        Vehicle(
            fob=D("6000000"),
            freight=D("0"),
            insurance=D("0"),
            fuel="electric",
            engine_cc=0,
            motor_kw=100,
        ),
        date(2026, 5, 20),
        D("14876850.00"),
    ),
]


@pytest.mark.parametrize(
    "label,vehicle,as_of,expected", GOLDEN_CASES, ids=[c[0] for c in GOLDEN_CASES]
)
def test_golden_landed_cost(label, vehicle, as_of, expected):
    assert quote_for(vehicle, as_of).landed_cost == expected


def test_surcharge_only_applies_inside_its_window():
    car = Vehicle(fob=D("2000000"), freight=D("0"), insurance=D("0"), fuel="petrol", engine_cc=1500)
    before = {line.code for line in quote_for(car, date(2026, 5, 15)).lines}
    during = {line.code for line in quote_for(car, date(2026, 5, 16)).lines}
    assert "SUR" not in before
    assert "SUR" in during


def test_ev_excise_is_charged_per_kw_not_per_cc():
    ev = Vehicle(fob=D("2000000"), freight=D("0"), insurance=D("0"), fuel="electric", motor_kw=40)
    excise = [ln for ln in quote_for(ev, date(2026, 5, 20)).lines if ln.code == "XID"]
    assert len(excise) == 1
    assert excise[0].per_unit and excise[0].unit == "kW"
    assert excise[0].amount == D("15000") * 40


def test_excise_is_specific_not_ad_valorem():
    """Two 659cc cars, one cheap one expensive, pay IDENTICAL excise.

    This is the whole point of a specific duty and the thing a
    percentage-based calculator gets structurally wrong.
    """
    cheap = Vehicle(fob=D("40600"), freight=D("0"), insurance=D("0"), fuel="petrol", engine_cc=659)
    dear = Vehicle(fob=D("4060000"), freight=D("0"), insurance=D("0"), fuel="petrol", engine_cc=659)
    x1 = next(ln for ln in quote_for(cheap, date(2026, 5, 20)).lines if ln.code == "XID")
    x2 = next(ln for ln in quote_for(dear, date(2026, 5, 20)).lines if ln.code == "XID")
    assert x1.amount == x2.amount


def test_kei_excise_dwarfs_the_car_itself():
    """CIF 40,600 attracts roughly 2m of excise. If this ever stops being
    true, someone has reverted the specific-duty model."""
    kei = Vehicle(fob=D("40600"), freight=D("0"), insurance=D("0"), fuel="petrol", engine_cc=659)
    excise = next(ln for ln in quote_for(kei, date(2026, 5, 20)).lines if ln.code == "XID")
    assert excise.amount > kei.cif * 40


def test_luxury_tax_only_bites_above_the_threshold():
    under = Vehicle(
        fob=D("4999999"), freight=D("0"), insurance=D("0"), fuel="petrol", engine_cc=1300
    )
    lines = {ln.code: ln.amount for ln in quote_for(under, date(2026, 5, 20)).lines}
    assert lines["LXT"] == D("0.00")


def test_key_dates_are_all_covered():
    """Gaps are as dangerous as overlaps -- both mean a quote you cannot issue."""
    assert load_rulesets()
    for day in (date(2026, 4, 1), date(2026, 5, 15), date(2026, 5, 16), date(2026, 8, 14)):
        assert ruleset_for(day)


def test_missing_ruleset_fails_loudly():
    with pytest.raises(RuleError):
        ruleset_for(date(2020, 1, 1))


def test_money_never_touches_float():
    car = Vehicle(
        fob=D("1234567"), freight=D("89012"), insurance=D("3456"), fuel="petrol", engine_cc=1490
    )
    quote = quote_for(car, date(2026, 5, 20))
    assert quote.landed_cost == quote.landed_cost.quantize(D("0.01"))
    assert isinstance(quote.total_tax, Decimal)
