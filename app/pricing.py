"""Everything between the auction price in yen and the price you sell at.

Kept separate from app/tax/engine.py on purpose. The engine stays
currency-agnostic and rate-free so the golden tests never break when the yen
moves. This module owns FX, non-duty costs, and margin.

The important idea here that most calculators get wrong: some costs are
DUTIABLE and some are not. Under WTO customs valuation a selling commission
paid to the exporter's agent forms part of the transaction value and gets
taxed; a buying commission you pay your own agent does not. So supplier
commission usually goes INTO the CIF before duty is assessed, while your own
importer commission and the clearing agent's fee sit outside it. Getting this
backwards on a Rs. 10m car is a six-figure error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.tax.engine import Quote, Vehicle, calculate, money


@dataclass(frozen=True)
class CostItem:
    """One line of cost that is not a government levy.

    dutiable=True means it gets folded into CIF and therefore attracts duty,
    surcharge, excise, SSCL and VAT on top. dutiable=False means it is simply
    added to what the car costs you after clearance.
    """

    code: str
    label: str
    amount: Decimal
    dutiable: bool = False


def default_costs() -> list[CostItem]:
    """The cost lines a Sri Lankan importer actually sees. Amounts start at zero.

    Defaults for `dutiable` reflect the common case. Confirm each one with your
    clearing agent -- the classification, not the amount, is what gets disputed.
    """
    return [
        CostItem("supplier_commission", "Supplier / exporter commission", Decimal("0"), True),
        CostItem("inland_japan", "Inland transport in Japan", Decimal("0"), True),
        CostItem("bank_charges", "Bank charges (L/C, TT)", Decimal("0"), False),
        CostItem("clearing_agent", "Clearing agent fees", Decimal("0"), False),
        CostItem("port_charges", "Port and terminal handling", Decimal("0"), False),
        CostItem("importer_commission", "Your commission / margin buffer", Decimal("0"), False),
        CostItem("registration", "Registration and number plates", Decimal("0"), False),
        CostItem("recondition", "Recondition, detailing, repairs", Decimal("0"), False),
    ]


@dataclass(frozen=True)
class FX:
    """One unit of `currency` buys `rate` rupees."""

    currency: str
    rate: Decimal

    def to_lkr(self, amount: Decimal) -> Decimal:
        return money(Decimal(str(amount)) * self.rate)


@dataclass
class Costing:
    """The full picture: yen in, selling price out."""

    cif_foreign: Decimal
    fx: FX
    quote: Quote
    costs: list[CostItem] = field(default_factory=list)

    @property
    def dutiable_extras(self) -> Decimal:
        return money(sum((c.amount for c in self.costs if c.dutiable), Decimal("0")))

    @property
    def non_dutiable_extras(self) -> Decimal:
        return money(sum((c.amount for c in self.costs if not c.dutiable), Decimal("0")))

    @property
    def total_cost(self) -> Decimal:
        """What the car actually costs you, on the road, ready to sell.

        Dutiable extras are already inside quote.cif, so they are not added
        again here -- adding them twice is the classic bug in this kind of app.
        """
        return money(self.quote.landed_cost + self.non_dutiable_extras)

    def price_at_margin(self, margin_pct: Decimal) -> Decimal:
        """Selling price that yields `margin_pct` profit ON THE SELLING PRICE.

        Margin, not markup. If you want 20% margin you divide by 0.8, you do
        not multiply by 1.2 -- that gives 16.7% and quietly eats your profit.
        """
        pct = Decimal(str(margin_pct)) / Decimal("100")
        if pct >= 1:
            raise ValueError("Margin must be under 100%")
        return money(self.total_cost / (Decimal("1") - pct))

    def margin_at_price(self, selling_price: Decimal) -> Decimal:
        """Margin percentage implied by a selling price you have in mind."""
        price = Decimal(str(selling_price))
        if price <= 0:
            return Decimal("0.00")
        return money((price - self.total_cost) / price * Decimal("100"))

    def profit_at_price(self, selling_price: Decimal) -> Decimal:
        return money(Decimal(str(selling_price)) - self.total_cost)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cif_foreign": str(self.cif_foreign),
            "currency": self.fx.currency,
            "fx_rate": str(self.fx.rate),
            "cif_lkr": str(self.quote.cif),
            "dutiable_extras": str(self.dutiable_extras),
            "non_dutiable_extras": str(self.non_dutiable_extras),
            "tax": self.quote.as_dict(),
            "total_cost": str(self.total_cost),
        }


def build_costing(
    *,
    cif_foreign: Decimal,
    fx: FX,
    fuel: str,
    engine_cc: int = 0,
    motor_kw: int = 0,
    year: int = 0,
    costs: list[CostItem] | None = None,
    ruleset: dict[str, Any],
) -> Costing:
    """Convert to rupees, fold dutiable extras into CIF, assess duty, total it up."""
    costs = costs if costs is not None else default_costs()
    cif_lkr = fx.to_lkr(cif_foreign)
    dutiable = money(sum((c.amount for c in costs if c.dutiable), Decimal("0")))

    vehicle = Vehicle(
        fob=money(cif_lkr + dutiable),  # already a CIF figure; extras ride along
        freight=Decimal("0"),
        insurance=Decimal("0"),
        fuel=fuel,
        engine_cc=engine_cc,
        motor_kw=motor_kw,
        year=year,
    )
    return Costing(cif_foreign=cif_foreign, fx=fx, quote=calculate(vehicle, ruleset), costs=costs)
