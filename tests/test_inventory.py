"""Inventory tests. The showroom leak test is the one that matters --
cost and margin must never reach a buyer-facing page."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.inventory import Base, Listing, Status, portfolio_summary, public_listings

D = Decimal


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        yield s


def make(**kw):
    base = dict(
        make="Nissan",
        model="Roox",
        year=2023,
        engine_cc=659,
        total_cost_lkr=D("3500000"),
        asking_price_lkr=D("4200000"),
    )
    base.update(kw)
    return Listing(**base)


def test_profit_and_margin_use_asking_price_until_sold(session):
    unit = make(status=Status.FOR_SALE)
    assert unit.profit == D("700000")
    assert unit.margin_pct == D("16.67")


def test_profit_switches_to_sold_price_once_sold(session):
    unit = make(status=Status.SOLD, sold_price_lkr=D("4000000"))
    assert unit.profit == D("500000")


def test_showroom_only_shows_sellable_units(session):
    session.add_all(
        [
            make(status=Status.FOR_SALE, model="Roox"),
            make(status=Status.IN_TRANSIT, model="Dayz"),
            make(status=Status.SOLD, model="Sakura"),
            make(status=Status.RESERVED, model="Ekcross"),
        ]
    )
    session.commit()
    models = {x.model for x in public_listings(session)}
    assert models == {"Roox", "Ekcross"}


def test_summary_separates_realised_from_projected(session):
    units = [
        make(status=Status.SOLD, sold_price_lkr=D("4000000")),
        make(status=Status.FOR_SALE),
    ]
    summary = portfolio_summary(units)
    assert summary["units_sold"] == 1
    assert summary["realised_profit"] == D("500000")
    assert summary["projected_profit"] == D("700000")
    assert summary["capital_tied_up"] == D("3500000")
