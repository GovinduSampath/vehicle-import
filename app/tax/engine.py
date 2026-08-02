"""Landed-cost calculation engine.

Design rule you must never break: no tax rate is ever written in this file.
Rates live in app/tax/rules/*.yaml, each file scoped to the dates its gazette
was in force. This module only knows *how* levies compose, not *what* they are.

Money is Decimal throughout. Never float. A float rounding error on a
Rs. 12,000,000 quote is a real complaint from a real customer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENTS = Decimal("0.01")


def money(value: Any) -> Decimal:
    """Coerce anything to a 2dp Decimal without going through float."""
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Vehicle:
    """What the user tells us about the car.

    fob/freight/insurance are already in LKR. Currency conversion happens
    before this point on purpose -- the engine stays currency-agnostic so the
    golden tests never depend on an exchange rate that moves daily.
    """

    fob: Decimal
    freight: Decimal
    insurance: Decimal
    fuel: str  # petrol | diesel | hybrid | electric
    engine_cc: int = 0  # 0 for electric
    motor_kw: int = 0  # 0 for combustion
    year: int = 0

    @property
    def cif(self) -> Decimal:
        return money(self.fob + self.freight + self.insurance)


@dataclass
class LevyLine:
    code: str
    name: str
    rate: Decimal
    base: Decimal
    amount: Decimal
    per_unit: bool = False  # True => rate is LKR per unit, base is unit count
    unit: str = ""  # "cc", "kW"


@dataclass
class Quote:
    cif: Decimal
    lines: list[LevyLine] = field(default_factory=list)
    gazette: str = ""
    ruleset_id: str = ""

    @property
    def total_tax(self) -> Decimal:
        return money(sum((line.amount for line in self.lines), Decimal("0")))

    @property
    def landed_cost(self) -> Decimal:
        """CIF plus duty. Excludes clearing agent, port, and registration fees."""
        return money(self.cif + self.total_tax)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cif": str(self.cif),
            "gazette": self.gazette,
            "ruleset_id": self.ruleset_id,
            "lines": [
                {
                    "code": line.code,
                    "name": line.name,
                    "rate": str(line.rate),
                    "base": str(line.base),
                    "amount": str(line.amount),
                }
                for line in self.lines
            ],
            "total_tax": str(self.total_tax),
            "landed_cost": str(self.landed_cost),
        }


def _levy_applies(levy: dict[str, Any], vehicle: Vehicle) -> bool:
    """A levy can be gated on vehicle attributes, e.g. excise only on petrol."""
    conditions = levy.get("applies_when")
    if not conditions:
        return True
    return all(getattr(vehicle, attr) in allowed for attr, allowed in conditions.items())


def _band_value(bands: dict[str, Any], vehicle: Vehicle, key: str) -> Decimal:
    """Walk a banded schedule and return the matching band's value."""
    value = getattr(vehicle, bands["field"])
    for band in bands["bands"]:
        ceiling = band.get("up_to")
        if ceiling is None or value <= ceiling:
            return Decimal(str(band[key]))
    raise ValueError(f"No band matched {bands['field']}={value}")


def _resolve_rate(levy: dict[str, Any], vehicle: Vehicle) -> Decimal:
    """Flat rate, or a banded rate looked up by a vehicle attribute."""
    if "rate" in levy:
        return Decimal(str(levy["rate"]))
    return _band_value(levy["rate_bands"], vehicle, "rate")


def _resolve_per_unit(levy: dict[str, Any], vehicle: Vehicle) -> tuple[Decimal, Decimal]:
    """Return (rupees per unit, number of units) for a specific-rate levy.

    Sri Lanka charges excise on motor cars as a rupee amount PER CUBIC
    CENTIMETRE, not as a percentage of value. A 660cc kei car and a 660cc
    supercar pay identical excise. This is the single biggest reason a
    percentage-based calculator gets cheap cars badly wrong: on a low-value
    import the excise can be many times the CIF itself.
    """
    spec = levy["per_unit"]
    units = Decimal(str(getattr(vehicle, spec["field"])))
    if "amount" in spec:
        return Decimal(str(spec["amount"])), units
    return _band_value(spec, vehicle, "amount"), units


def calculate(vehicle: Vehicle, ruleset: dict[str, Any]) -> Quote:
    """Apply every levy in a ruleset, in declared order.

    Order matters: later levies name earlier ones in their `base`, which is how
    the Sri Lankan cascade works -- VAT is charged on a base that already
    includes the duty charged before it.
    """
    components: dict[str, Decimal] = {"CIF": vehicle.cif}
    quote = Quote(
        cif=vehicle.cif,
        gazette=ruleset.get("gazette", ""),
        ruleset_id=ruleset.get("id", ""),
    )

    for levy in ruleset["levies"]:
        if not _levy_applies(levy, vehicle):
            continue

        base = money(sum((components[c] for c in levy["base"]), Decimal("0")))

        # Luxury tax and similar only bite on the portion above a threshold.
        excess_over = levy.get("excess_over")
        if excess_over is not None:
            base = money(max(Decimal("0"), base - Decimal(str(excess_over))))

        # Two kinds of levy: ad valorem (a % of a value base) and specific
        # (a rupee amount per cc / per kW). Excise on cars is specific.
        if "per_unit" in levy:
            per_unit, units = _resolve_per_unit(levy, vehicle)
            amount = money(per_unit * units)
            rate, base = per_unit, units
        else:
            rate = _resolve_rate(levy, vehicle)
            amount = money(base * rate)

        components[levy["code"]] = amount
        quote.lines.append(
            LevyLine(
                code=levy["code"],
                name=levy["name"],
                rate=rate,
                base=base,
                amount=amount,
                per_unit="per_unit" in levy,
                unit=levy.get("per_unit", {}).get("unit", ""),
            )
        )

    return quote
