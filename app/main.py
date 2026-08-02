"""FastAPI entrypoint. Deliberately thin -- the real logic lives in
app/tax/ (what the government takes) and app/pricing.py (what you pay and
what you charge)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import inventory as inv
from app.pricing import FX, CostItem, build_costing, default_costs
from app.tax.loader import RuleError, ruleset_for

app = FastAPI(title="Vehicle Import", version="0.2.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.on_event("startup")
def _startup() -> None:
    inv.init_db()


def _dec(value: str | None, default: str = "0") -> Decimal:
    """Parse a form field into Decimal, tolerating commas and blanks."""
    raw = (value or "").replace(",", "").replace(" ", "").strip()
    return Decimal(raw or default)


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------
@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness. Dependency-free so it answers even if the DB is down."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> JSONResponse:
    """Readiness. Fails if the rule files are broken, so a bad deploy never
    receives traffic."""
    try:
        ruleset_for(date.today())
    except RuleError as exc:
        return JSONResponse({"status": "not ready", "reason": str(exc)}, status_code=503)
    return JSONResponse({"status": "ready"})


# --------------------------------------------------------------------------
# calculator
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "index.html", {"costs": default_costs(), "today": date.today().isoformat()}
    )


@app.post("/quote", response_class=HTMLResponse)
async def quote(request: Request) -> HTMLResponse:
    """HTMX posts the whole form here and swaps the returned fragment in."""
    form = await request.form()

    def field(name: str, default: str = "") -> str:
        return str(form.get(name, default))

    try:
        costs = [
            CostItem(
                code=item.code,
                label=item.label,
                amount=_dec(field(f"cost_{item.code}")),
                dutiable=field(f"dutiable_{item.code}") == "on",
            )
            for item in default_costs()
        ]
        fx = FX(currency=field("currency", "JPY"), rate=_dec(field("fx_rate"), "2.05"))
        as_of = field("as_of") or date.today().isoformat()

        costing = build_costing(
            cif_foreign=_dec(field("cif_foreign")),
            fx=fx,
            fuel=field("fuel", "petrol"),
            engine_cc=int(_dec(field("engine_cc"))),
            motor_kw=int(_dec(field("motor_kw"))),
            year=int(_dec(field("year"))),
            costs=costs,
            ruleset=ruleset_for(date.fromisoformat(as_of)),
        )
        target_margin = _dec(field("target_margin"), "15")
    except (InvalidOperation, ValueError):
        return templates.TemplateResponse(
            request, "_result.html", {"error": "Enter plain numbers, no letters or symbols."}
        )
    except RuleError as exc:
        return templates.TemplateResponse(request, "_result.html", {"error": str(exc)})

    return templates.TemplateResponse(
        request,
        "_result.html",
        {
            "c": costing,
            "target_margin": target_margin,
            "suggested_price": costing.price_at_margin(target_margin),
            "error": None,
        },
    )


# --------------------------------------------------------------------------
# inventory -- your side of the business
# --------------------------------------------------------------------------
@app.get("/inventory", response_class=HTMLResponse)
def inventory_page(request: Request) -> HTMLResponse:
    with inv.get_session() as session:
        listings = inv.all_listings(session)
        return templates.TemplateResponse(
            request,
            "inventory.html",
            {
                "listings": listings,
                "summary": inv.portfolio_summary(listings),
                "statuses": list(inv.Status),
            },
        )


@app.post("/inventory")
def create_listing(
    make: str = Form(...),
    model: str = Form(...),
    year: int = Form(...),
    grade: str = Form(""),
    chassis_no: str = Form(""),
    engine_cc: int = Form(0),
    fuel: str = Form("petrol"),
    mileage_km: int = Form(0),
    auction_grade: str = Form(""),
    cif_jpy: str = Form("0"),
    fx_rate: str = Form("0"),
    total_cost_lkr: str = Form("0"),
    asking_price_lkr: str = Form("0"),
    status: str = Form("sourcing"),
    notes: str = Form(""),
) -> RedirectResponse:
    with inv.get_session() as session:
        session.add(
            inv.Listing(
                make=make,
                model=model,
                year=year,
                grade=grade,
                chassis_no=chassis_no,
                engine_cc=engine_cc,
                fuel=fuel,
                mileage_km=mileage_km,
                auction_grade=auction_grade,
                cif_jpy=_dec(cif_jpy),
                fx_rate=_dec(fx_rate),
                total_cost_lkr=_dec(total_cost_lkr),
                asking_price_lkr=_dec(asking_price_lkr),
                status=inv.Status(status),
                notes=notes,
            )
        )
        session.commit()
    return RedirectResponse("/inventory", status_code=303)


@app.post("/inventory/{listing_id}/status")
def update_status(
    listing_id: int, status: str = Form(...), sold_price_lkr: str = Form("0")
) -> RedirectResponse:
    with inv.get_session() as session:
        listing = session.get(inv.Listing, listing_id)
        if listing:
            listing.status = inv.Status(status)
            if listing.status is inv.Status.SOLD:
                listing.sold_price_lkr = _dec(sold_price_lkr)
            session.commit()
    return RedirectResponse("/inventory", status_code=303)


@app.get("/showroom", response_class=HTMLResponse)
def showroom(request: Request) -> HTMLResponse:
    """What a buyer sees. Cost and margin never appear here."""
    with inv.get_session() as session:
        return templates.TemplateResponse(
            request, "showroom.html", {"listings": inv.public_listings(session)}
        )
