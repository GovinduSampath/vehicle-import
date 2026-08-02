"""Tests for FX conversion, dutiable vs non-dutiable costs, and margin.

The margin tests matter more than they look. Confusing margin with markup is
the most common way a small importer thinks they made 20% and actually made
16.7%, and no amount of correct tax maths saves you from it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.pricing import FX, CostItem, build_costing
from app.tax.loader import ruleset_for

D = Decimal
RULES = ruleset_for(date(2026, 5, 20))


def costing(cif_jpy="877996", rate="2.05", costs=None, cc=659):
    return build_costing(
        cif_foreign=D(cif_jpy),
        fx=FX("JPY", D(rate)),
        fuel="petrol",
        engine_cc=cc,
        costs=costs or [],
        ruleset=RULES,
    )


def test_yen_converts_to_rupees_at_the_given_rate():
    c = costing("1000000", "2.05")
    assert c.quote.cif == D("2050000.00")


def test_dutiable_cost_increases_the_tax_bill():
    plain = costing(costs=[])
    with_commission = costing(
        costs=[CostItem("supplier_commission", "Supplier", D("200000"), dutiable=True)]
    )
    assert with_commission.quote.total_tax > plain.quote.total_tax
    assert with_commission.quote.cif == plain.quote.cif + D("200000")


def test_non_dutiable_cost_does_not_change_the_tax_bill():
    plain = costing(costs=[])
    with_agent = costing(costs=[CostItem("clearing_agent", "Agent", D("150000"), dutiable=False)])
    assert with_agent.quote.total_tax == plain.quote.total_tax
    assert with_agent.total_cost == plain.total_cost + D("150000")


def test_dutiable_extras_are_not_counted_twice():
    """They are already inside CIF, so total_cost must not add them again."""
    c = costing(costs=[CostItem("supplier_commission", "Supplier", D("200000"), True)])
    assert c.total_cost == c.quote.landed_cost
    assert c.non_dutiable_extras == D("0.00")


def test_margin_is_on_selling_price_not_markup_on_cost():
    c = costing(costs=[])
    price = c.price_at_margin(D("20"))
    # 20% margin means profit / price == 0.20, NOT cost * 1.20
    assert c.margin_at_price(price) == D("20.00")
    assert price > c.total_cost * D("1.2")


def test_margin_round_trips():
    c = costing(costs=[])
    for pct in ("5", "12.5", "25", "40"):
        price = c.price_at_margin(D(pct))
        assert c.margin_at_price(price) == D(pct).quantize(D("0.01"))


def test_impossible_margin_is_rejected():
    with pytest.raises(ValueError):
        costing(costs=[]).price_at_margin(D("100"))


def test_profit_is_price_minus_total_cost():
    c = costing(costs=[CostItem("bank_charges", "Bank", D("50000"), False)])
    assert c.profit_at_price(D("5000000")) == D("5000000") - c.total_cost
