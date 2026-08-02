"""The selling side: vehicles you are actually bringing in and moving on.

A calculator answers "what would this cost?". This answers "what did unit
CHASSIS-1234 cost me, what is it listed at, and how much did I make?" -- which
is the part that turns the project into a business tool rather than a toy.

Storage is SQLAlchemy 2.0. SQLite by default so it runs with zero setup;
point DATABASE_URL at Postgres and the same code works. Schema is created with
create_all for now -- swap to Alembic when you reach the migrations step, and
make running migrations a job in the deploy pipeline.
"""

from __future__ import annotations

import enum
import os
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Enum, Integer, Numeric, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./inventory.db")


class Base(DeclarativeBase):
    pass


class Status(str, enum.Enum):  # noqa: UP042
    """Where the unit is in the pipeline. Drives the showroom filter."""

    SOURCING = "sourcing"
    WON_AT_AUCTION = "won_at_auction"
    IN_TRANSIT = "in_transit"
    AT_PORT = "at_port"
    FOR_SALE = "for_sale"
    RESERVED = "reserved"
    SOLD = "sold"


PUBLIC_STATUSES = {Status.FOR_SALE, Status.RESERVED}


class Listing(Base):
    """One physical vehicle. Money columns are Numeric, never Float."""

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    make: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(80))
    year: Mapped[int] = mapped_column(Integer)
    grade: Mapped[str] = mapped_column(String(80), default="")
    chassis_no: Mapped[str] = mapped_column(String(40), default="", index=True)
    engine_cc: Mapped[int] = mapped_column(Integer, default=0)
    fuel: Mapped[str] = mapped_column(String(20), default="petrol")
    mileage_km: Mapped[int] = mapped_column(Integer, default=0)
    auction_grade: Mapped[str] = mapped_column(String(10), default="")  # 4.5, R, RA...

    cif_jpy: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    total_cost_lkr: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    asking_price_lkr: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    sold_price_lkr: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)

    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.SOURCING)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    @property
    def title(self) -> str:
        return f"{self.year} {self.make} {self.model} {self.grade}".strip()

    @property
    def realised_price(self) -> Decimal:
        """Sold price if sold, otherwise what you are asking."""
        return self.sold_price_lkr if self.status is Status.SOLD else self.asking_price_lkr

    @property
    def profit(self) -> Decimal:
        return Decimal(self.realised_price or 0) - Decimal(self.total_cost_lkr or 0)

    @property
    def margin_pct(self) -> Decimal:
        price = Decimal(self.realised_price or 0)
        if price <= 0:
            return Decimal("0.00")
        return (self.profit / price * 100).quantize(Decimal("0.01"))

    @property
    def is_public(self) -> bool:
        return self.status in PUBLIC_STATUSES


_engine = create_engine(DATABASE_URL, future=True)


def init_db() -> None:
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    return Session(_engine, future=True)


def all_listings(session: Session) -> list[Listing]:
    return list(session.scalars(select(Listing).order_by(Listing.created_at.desc())))


def public_listings(session: Session) -> list[Listing]:
    stmt = (
        select(Listing)
        .where(Listing.status.in_(PUBLIC_STATUSES))
        .order_by(Listing.asking_price_lkr)
    )
    return list(session.scalars(stmt))


def portfolio_summary(listings: list[Listing]) -> dict[str, Decimal | int]:
    """Numbers you would actually want on a dashboard."""
    sold = [x for x in listings if x.status is Status.SOLD]
    live = [x for x in listings if x.status is not Status.SOLD]
    return {
        "units_total": len(listings),
        "units_sold": len(sold),
        "capital_tied_up": sum((Decimal(x.total_cost_lkr or 0) for x in live), Decimal("0")),
        "realised_profit": sum((x.profit for x in sold), Decimal("0")),
        "projected_profit": sum((x.profit for x in live), Decimal("0")),
    }
