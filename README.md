# Vehicle Import Calculator

Japan → Sri Lanka landed-cost calculator. Built as a hands-on CI/CD and hosting
project: every tax change is a pull request, every merge is a tested deploy.

---

## ⚠️ Read this before anything else

**The tax rates in `app/tax/rules/*.yaml` are placeholders.** Public calculators
disagree with each other on the CID rate and on which levies form the base for
excise. Before this app is worth anything:

1. Get the actual gazettes from `customs.gov.lk` (start with 2434/04 and 2488/56).
2. Take one vehicle you know the real assessed duty for — ideally one you have
   imported — and work it through by hand on paper.
3. Correct the YAML until the engine reproduces that figure exactly.
4. Rewrite the golden tests in `tests/test_engine.py` with that verified figure.
5. Cite the gazette number in the commit message.

Until step 4 is done, the tests only prove the engine composes levies correctly.
They do not prove the numbers are right.

---

## Step 0 — Set up your machine (30 min)

```bash
sudo dnf install -y git python3.12 python3-pip
# Docker Engine + compose plugin, from docs.docker.com — not the distro package
sudo usermod -aG docker $USER   # log out and back in

git config --global user.name "Sampath"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
gh auth login                    # GitHub CLI, you will use it constantly
```

## Step 1 — Repo and branch protection (20 min)

```bash
gh repo create vehicle-import --private --source=. --remote=origin
git add . && git commit -m "chore: initial scaffold" && git push -u origin main
```

Then on GitHub: **Settings → Rules → New branch ruleset**, target `main`:

- Require a pull request before merging
- Require status checks to pass → add `quality` and `image` once they have run once
- Block force pushes

This step is the one people skip, and it is the one that makes CI mean anything.
A pipeline you can bypass is decoration.

## Step 2 — Run it locally (15 min)

```bash
python -m venv .venv && source .venv/bin/activate
make install
make test        # 10 tests should pass
make run         # http://localhost:8000
```

Then the container path:

```bash
cp .env.example .env
make up          # app + postgres via compose
```

**Learn here:** why the Dockerfile has two stages, why it creates a user with
UID 10001, and why `docker-compose.yml` bind-mounts `./app` in dev but the
production image does not.

## Step 3 — Make CI real (1 day)

`.github/workflows/ci.yml` is already written and commented. Push a branch and
open a PR to watch it run.

Then **deliberately break things** — this is the actual learning:

- Push a formatting violation. Watch `ruff format --check` fail.
- Change one golden test's expected figure by 1 rupee. Watch it fail, and notice
  the error tells you exactly which vehicle and which date.
- Add a second ruleset with `effective_from: 2026-05-16` so it overlaps the
  existing one. Watch `test_key_dates_are_all_covered` catch it. **This is the
  single best demo in the whole project** — CI catching a business-logic error
  that no linter could find.
- Pin an old base image with a known CVE and watch Trivy block the build.

**Learn here:** triggers, jobs vs steps, the matrix strategy, `needs`,
`if: always()`, artifacts, caching, concurrency groups, and why
`${{ secrets.GITHUB_TOKEN }}` beats a personal access token.

## Step 4 — Provision the server (2 days)

A €4–5/month Hetzner CX22 is plenty. Write `deploy/terraform/`:

- `hcloud_server`, `hcloud_firewall` (22/80/443 only), `hcloud_ssh_key`
- DNS records via the Cloudflare provider
- Remote state in a Cloudflare R2 or Backblaze B2 bucket — never local state

Workflow pattern: `terraform plan` posts to the PR, `terraform apply` runs on
merge to main. That is IaC done the way real teams do it.

Then `deploy/ansible/` to harden the box — **reuse your CIS roles here.** SSH
key-only, fail2ban, unattended-upgrades, Docker installed, a deploy user.

## Step 5 — Continuous deployment (2 days)

Write `.github/workflows/cd.yml`:

- Trigger on push to main, `needs` the CI workflow
- Authenticate to the server with an SSH deploy key from repo secrets
- Pull `ghcr.io/you/vehicle-import:${{ github.sha }}` and restart the service
- Poll `/readyz` until healthy; if it does not come up in 60s, roll back to the
  previous SHA and fail the job
- Production behind a GitHub **Environment** with a required reviewer, so a tag
  deploy waits for you to click approve

Put Caddy in front for automatic TLS — two lines of Caddyfile and you have
Let's Encrypt with auto-renewal.

**Learn here:** build-once-deploy-many, immutable image tags, health-gated
rollout, automated rollback, environment protection rules, OIDC vs static
secrets.

## Step 6 — Observability (2 days)

- Structured JSON logs from the app
- Prometheus + Grafana + Loki on the same box
- One alert that actually fires, routed to Telegram
- An external uptime check (UptimeRobot free tier) so you find out before users do

You already think this way from Centreon. The new part is that the app emits
its own metrics rather than being probed from outside.

## Step 7 — The GitOps rebuild (1 week, optional but high value)

Migrate to k3s on the same server, then Argo CD. Your CD workflow stops
deploying and instead commits a new image tag to a manifests repo; Argo
reconciles. Write down in the README **why** pull-based beats push-based —
that paragraph is interview gold.

## Step 8 — Make it a business

- Daily JPY/LKR rate from a scheduled workflow
- Auction sheet grade reference (you can read these already)
- Euro 6 / airbag / ABS / ESC compliance checker — 2026 registration requires them
- Saved quotes with a shareable link, and a PDF quote for clients
- Comparison view: same budget, three candidate vehicles, side by side

---

## Project layout

```
app/
  main.py              FastAPI routes — deliberately thin
  tax/
    engine.py          how levies compose. No rates live here, ever.
    loader.py          picks the ruleset in force on a date; rejects overlaps
    rules/*.yaml       one file per gazette, with effective dates
  templates/           Jinja + HTMX, no build step
tests/
  test_engine.py       golden cases + rule-integrity tests
.github/workflows/     CI now, CD next
deploy/                terraform + ansible (yours to write, Step 4)
```

## Commands

| Command | What it does |
|---|---|
| `make install` | install app + dev tooling |
| `make check` | exactly what CI runs — run before every push |
| `make test` | golden tests |
| `make run` | dev server on :8000 |
| `make up` / `make down` | full stack in Docker |

## Disclaimer

Estimates only. Duty is assessed by Sri Lanka Customs at the time of clearance
and the rules change by gazette, sometimes with days of notice. Confirm every
figure with Customs or a licensed clearing agent before committing money.

---

## v0.2 — what changed

The app is no longer just a calculator.

**Calculator**
- CIF is entered in **yen** with an exchange rate, the way auction prices actually arrive
- Eight editable cost lines: supplier commission, inland Japan, bank charges, clearing
  agent, port, your commission, registration, recondition
- Each cost line is flagged **dutiable or not**. Dutiable costs fold into CIF and get
  taxed; the rest are added after clearance. On a Rs. 200,000 supplier commission
  that distinction is worth about Rs. 114,000 — see `test_dutiable_cost_increases_the_tax_bill`
- Output ends with **total cost to you**, a suggested selling price at your target
  margin, and the profit at that price

**Inventory** (`/inventory`) — every unit you are sourcing, shipping or selling.
Chassis number, auction grade, mileage, cost, asking price, live margin, and a
status pipeline: sourcing → won at auction → in transit → at port → for sale →
reserved → sold. Dashboard shows capital tied up, realised profit, projected profit.

**Showroom** (`/showroom`) — the buyer-facing page. Only `for_sale` and `reserved`
units appear, and cost, margin and profit are never rendered. There is a test that
fails if they ever leak.

**Margin, not markup.** `price_at_margin(20)` divides by 0.8. Multiplying cost by 1.2
gives 16.7% margin and quietly eats your profit — `test_margin_is_on_selling_price_not_markup_on_cost`
locks that down.

### New files
```
app/pricing.py            FX, dutiable classification, margin
app/inventory.py          SQLAlchemy model, status pipeline, portfolio summary
app/templates/base.html   shared shell + nav
app/templates/inventory.html, showroom.html
tests/test_pricing.py     8 tests
tests/test_inventory.py   4 tests
```

### Setup
```bash
pip install -e ".[dev]"     # sqlalchemy is new
pytest -v                   # 22 tests
uvicorn app.main:app --reload --port 8000
```
SQLite by default (`inventory.db`, gitignored). Set `DATABASE_URL` to use Postgres.

### Next on this side
- Photos per listing, and the auction sheet PDF attached to the unit
- Buyer enquiry form on the showroom, feeding a simple CRM
- Alembic migrations, with `alembic upgrade head` as a step in the deploy pipeline
- Auth on `/inventory` — right now anyone who knows the URL can see your margins
