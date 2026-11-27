# ReconcileAI

**Accounts-receivable reconciliation for Indian businesses** — Python, Streamlit, SQLite and (optionally) an LLM via OpenRouter, OpenAI or Gemini.

Upload bank statements, invoices and payment emails, click **Run Reconciliation**, and get every bank credit matched to its invoice(s) — or routed to a human with the evidence and a proposed allocation. Partial payments, TDS deductions, bulk payments, overpayments and duplicate credits are all handled, and every decision is audited.

**Design principle:** *the LLM reads documents; Python decides about money.* Every amount, match and status is computed deterministically. With no API key the whole app still works: rule-based extractors replace the LLM.

→ Architecture, design trade-offs and weakest points: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## Quick start

```bash
cd ReconcileAI
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional: add an OpenRouter / OpenAI / Gemini key
streamlit run app.py
```

Open http://localhost:8501, use **Load demo dataset**, then **Run reconciliation**.

Or with Docker: `docker build -t reconcileai . && docker run -p 8501:8501 --env-file .env reconcileai`

### New web frontend (React + FastAPI)

A second UI lives in [`frontend/`](frontend/): Next.js, talking to a thin FastAPI layer ([`api/main.py`](api/main.py)) that calls the same Python functions the Streamlit app uses. No money logic moved.

```bash
# terminal 1: API on :8000
cd ReconcileAI && source .venv/bin/activate
uvicorn api.main:app --port 8000

# terminal 2: web on :3000 (proxies /api to :8000; override with RECONCILE_API_URL)
cd ReconcileAI/frontend && npm install && npm run dev
```

Open http://localhost:3000 for the landing page, or http://localhost:3000/app/overview for the workspace. Enter a reviewer name in the bar under the nav, then **Load demo data** and **Run reconciliation**. Shortcuts: ⌘K command bar; on the review queue, J/K move between cases and A approves.

---

## The app

| Page | What it does |
|---|---|
| **Overview** | Receipts, matched value, outstanding receivables, review backlog, TDS awaiting certificates. |
| **Review queue** | Uncertain credits, largest first and filterable by reason, beside a detail panel: the bank line next to the suggested invoice, the computed shortfall or excess, exactly what approving will post, and the remittance excerpt it rests on. Actions: approve, reject, apply to one or several invoices (with TDS), mark as not a receivable, or confirm/release a duplicate. A named reviewer is required and anything other than approving needs a note. |
| **Bank credits** | Every credit, what it was allocated to, and why. Reconcile one line now, or reverse a match. |
| **Import** | Bank statements (CSV/Excel), invoices (PDF, CSV or Excel register), remittance emails (.eml/.txt/.pdf or pasted text). The same file is never imported twice. |
| **Reports** | Summary (with an optional model-drafted management note, labelled as such), receivables ageing (not due / 1–30 / 31–60 / 61–90 / 90+, by bucket and by customer), customer balances, TDS register (verify with Form 16A or reject), invoices, Excel export. |
| **Audit trail** | Every import, decision and human action, with its evidence. |
| **Ask the data** | Plain-language questions ("what's overdue?", "status of INV-005", "how much does Apex owe?"). Python fetches the data; the LLM, if configured, only rephrases it. |

### UI design

**Web frontend.** The design language is modelled on the Awwwards Honorable Mention "Autonomous Finances" (April 2026): a monochrome black canvas, white-alpha hairlines, an ice-blue signal colour, DM Sans display type over Inter, and chrome 3D rings that turn as you scroll. Only the design language is borrowed; the copy, 3D geometry and assets are original. Built with Three.js / React Three Fiber, GSAP (ScrollTrigger, SplitText), Lenis, Motion and TanStack Query. Tokens and rules are in [`frontend/DESIGN.md`](frontend/DESIGN.md).

**Streamlit app.** The interface follows the "Invoice & Billing Tool" profile from the UI/UX Pro Max skill (Swiss minimalism with a data-dense dashboard). Navy is the primary colour; green, amber and red are reserved for status and always appear with a text label. Type is IBM Plex Sans and Mono. The default theme is light, with a matching dark theme that follows the OS. The theme lives in [`.streamlit/config.toml`](.streamlit/config.toml); `app.py` has only a few lines of CSS for the hero figure and the value-split bar. Money uses Indian digit grouping (₹1,06,200.00), and timestamps are shown in IST.

Text that may come from the model is labelled as such: the management summary, assistant answers, and match explanations. Match explanations are deterministic and evidence-only by default; they come from the model only when `LLM_MATCH_EXPLANATIONS=1`.

---

## How a bank credit is decided

1. **Excluded?** Debits and zero lines are kept for completeness but never matched.
2. **Duplicate?** Same UTR as an earlier credit, or (when a UTR is missing) the same amount with a near-identical narration within 30 days. Two different UTRs are never duplicates.
3. **Remittance advice:** found by UTR, or by a unique amount + date match when the email quoted no UTR. An advice already used by another credit is not used again.
4. **Candidates:** invoice numbers (any format on your register) read from the narration or advice; customers matched by GSTIN or name; and invoices whose outstanding balance equals payment + TDS. Invoices a reviewer rejected for this credit are excluded.
5. **Score:** a weighted sum of six signals.
6. **Auto-match only if all of these hold:**
   - the score is at least 0.60 and no rival is within 0.10;
   - the amount equals the balance within 0.5 %, capped at ₹100, with no TDS involved;
   - the invoice number came from the bank line, or from an advice carrying this UTR whose amount agrees;
   - the payer matches the invoice's customer;
   - the invoice is not a model-read one still waiting for confirmation.
7. Otherwise **review** (part-payments, TDS, bulk, over-payments and anything failing a gate), or **unmatched** below 0.25. Both open a case.

A model-guessed invoice number can suggest a match but never post one.

## Money and balances

- Outstanding = total − paid before import − approved payments − adjustments − rounding. Rounding is stored on the invoice.
- Nothing is applied beyond what an invoice owes. The excess is held as **customer credit**, which can be applied to the same customer's invoices.
- **Credit notes, write-offs and bank charges** are separate reversible entries.
- Every action checks the current state and runs in one database transaction.
- `GET /api/ledger/check` verifies that receipts = applied + held + undecided + duplicates + excluded, and that every invoice balance agrees with its entries.

### TDS (Indian tax deducted at source)

Rates are held by section and effective date in [`config/thresholds.py`](config/thresholds.py) (194C 1/2 %, 194J 10/2 %, 194H 5 % then 2 % from 1 Oct 2024, 194I 10/2 %, 194A 10 %, 194Q 0.1 %), on the taxable value or invoice total (CBDT Circular 23/2017). **Have a Chartered Accountant confirm the table, including section numbering under the Income-tax Act, 2025.** A claim stays pending until a reviewer verifies it with a certificate or a note naming the evidence. A rejected claim re-opens the invoice.

## Accounting and intake tools

| Task | How |
|---|---|
| Hold a receipt as an advance / apply credit | `POST /api/review/{case}/hold`, `POST /api/credits/{id}/apply` |
| Credit note, write-off, bank charge | `POST /api/invoices/{id}/adjustments`, reverse with `/api/adjustments/{id}/reverse` |
| Confirm a model-read invoice | `POST /api/invoices/{id}/confirm` |
| Match TDS against a 26AS table | `POST /api/tds/26as` (preview; `apply=true` to verify unambiguous matches) |
| Draft payment reminders (never sent) | `GET /api/reports/reminders` |
| Import advices from a mailbox (read-only IMAP) | `python -m scripts.fetch_remittances --days 7` |
| Tally / Zoho Books registers | Import the CSV/Excel export; common column names are recognised |
| Extra bank column names | `config/bank_columns.json`, e.g. `{"narration": ["txn particulars"]}` |

These are API/CLI features; the two web UIs do not have screens for them yet.

## Login, audit and backups

- Login is **off unless `RECONCILE_LOGIN=1`** (the old `RECONCILE_AUTH` is ignored). Create the first admin with `RECONCILE_ADMIN_USER` / `RECONCILE_ADMIN_PASSWORD` (10+ characters) or `python -m scripts.create_user NAME --role admin`. Roles: viewer, reviewer, admin. The API uses HTTP Basic, so **serve it over HTTPS only**.
- Audit entries are hash-chained and database triggers block edits. `GET /api/audit-chain` verifies the chain. Someone with direct file access could rebuild it, so record the returned `head` elsewhere.
- `python -m scripts.backup_db` makes a consistent copy and checks the chain. Schedule it yourself.
- Before text goes to a model provider, account numbers, PAN, phone numbers and e-mail addresses are masked. Names, amounts and GSTINs are still sent. In production nothing is sent unless `LLM_DATA_CONSENT=1`.

## Optional parameter calibration

The hand-set values are used. `config/learned_params.json` was fitted on synthetic data **before the safety gates above were added**, and is used only with `RECONCILE_USE_LEARNED_PARAMS=1`; retrain before trying it.

```bash
python -m data.synthetic.generate_training_data
python -m training.train_matcher --dry-run
```

---

## Evaluation: examples tested and where it fails

**All data is synthetic, made up for this prototype.** No real client or bank data is used.

**Jurisdiction:** India: INR, GST invoices, NEFT/RTGS/IMPS/UPI narrations and TDS. Another country would need new tax rules, reference formats, tax-ID matching and multi-currency support.

**Model:** `google/gemini-2.5-flash` via OpenRouter for reading PDFs, emails and narrations. All decisions are made in Python. Tests and the figures below run with the model switched off; the model paths have not been re-run live since the safety changes.

### Demo dataset (`python -m scripts.smoke_reconcile`)

30 hand-designed cases (exact reference, name variant, no reference, part-payment, TDS, bulk, split, duplicate UTR, unknown payer, equal amounts, short payment, wrong reference, over-payment, clean payments): **30 / 30**.

### Generated credits (`python -m scripts.evaluate --batches 150 --seed 2026`)

| Result | Count of 4,524 |
|---|---|
| Auto-matched | 1,786 (39.5 %) |
| Wrong auto-matches | 0 |
| Sent to review | 2,463; the suggestion included a correct invoice in 2,340 of 2,448 that had one |
| Unmatched | 275 |

A second seed (7, 4,157 credits) also had no wrong auto-match. The generator was written alongside the engine, so this shows consistency with its assumptions, not real-world accuracy.

**Where it falls short**
- Messy references (`BILL 0012`, a bare `0012`) go to review: 114 of 292.
- A payment quoting an invoice without naming the payer always goes to review (all 218 such cases). This is the price of requiring the payer to match.
- Some unknown payers are sent to review when their amount equals an open invoice.

**Not tested**
- Real bank statements, real Tally/Zoho exports, a real mailbox, a real 26AS file, scanned-PDF OCR.
- A Docker build or a deployment.
- Only INR is supported.

---

## Configuration

See [`.env.example`](.env.example). The key settings:

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `openrouter` | `openrouter`, `openai` or `gemini` |
| `OPENROUTER_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | – | Leave empty to run offline (rule-based extraction) |
| `LLM_MODEL` | `google/gemini-2.5-flash` | Model id for the provider |
| `LLM_ENABLED` | `1` | Master switch for all LLM calls |
| `LLM_NARRATION_HINTS` | `1` | LLM reads narrations that have no invoice reference |
| `LLM_MATCH_EXPLANATIONS` | `0` | LLM-phrased explanations (default: deterministic, evidence-only) |
| `LLM_DATA_CONSENT` | `1`, `0` in production | Required before document text is sent to a model |
| `LLM_MASK_SENSITIVE` | `1` | Mask account numbers, PAN, phone and e-mail |
| `RECONCILE_MAX_ROUNDING` | `100` | Largest rounding difference in rupees |
| `RECONCILE_LOGIN` | off | Require login |
| `RECONCILE_CORS` | localhost:3000 | Origins allowed to change data |
| `APP_MODE` | – | Docker: `api` serves FastAPI instead of Streamlit |
| `DATABASE_PATH` | `database/reconcile.db` | SQLite file. Older databases are migrated in place on start-up (back up first). |

---

## Project structure

```
ReconcileAI/
├── app.py                         # Streamlit UI
├── config/
│   ├── settings.py                # env-driven settings, LLM and login switches
│   ├── thresholds.py              # hand-set defaults + learned-parameter loader
│   └── learned_params.json        # output of training/train_matcher.py
├── database/
│   ├── schema.sql · db.py         # schema, connection, in-place migrations
│   └── repositories.py            # all SQL lives here
├── extraction/
│   ├── bank_parser.py             # CSV / Excel statements (header detection, UTR from narration)
│   ├── invoice_parser.py          # PDF text (+ OCR for scans), CSV / Excel registers
│   ├── email_parser.py            # .eml bodies
│   ├── rule_extractor.py          # regex extraction of invoices & remittances (offline fallback)
│   ├── llm_extractor.py           # LLM calls (invoice, remittance, narration, summaries)
│   ├── document_classifier.py     # bank statement / invoice / remittance detection
│   └── ingestion.py               # validation, dedup, routing, demo loader
├── matching/                      # narration parsing, exact & fuzzy matching, scoring
├── validation/                    # payment & TDS rules, duplicates, settlement ledger
├── decision/
│   ├── decision_engine.py         # evaluate_transaction() / reconcile_transaction() / batch
│   ├── review_manager.py          # approve, reject, correct, reverse, dismiss, duplicates, TDS
│   └── adjustments.py · credits.py  # credit notes, write-offs, advances
├── reporting/                     # aging, customer balances, TDS register, Excel, finance assistant
├── security/ · utils/             # login and roles; date parsing
├── training/train_matcher.py      # parameter calibration
├── data/synthetic/                # demo dataset + labelled training-data generator
├── scripts/                       # smoke, evaluate, users, backup, mailbox, LLM check
└── tests/                         # pytest suite (offline, throw-away databases)
```

## Sign-in and the demo account

The public Render demo has login off (the default) and `RECONCILE_DEMO_DATA=1`, so the website and the Streamlit app open straight into the synthetic dataset, which is re-created after every cold restart. With login on, the website has no sign-in page: it signs in with the demo account below automatically. `sh scripts/run_demo.sh` starts the API and website that way. Set `PYTHON=/path/to/python` if the project has no `.venv`.

| Email | Password |
|---|---|
| `demo@reconcileai.example` | `ReconcileDemo#2026` |

The demo account has the reviewer role and sees synthetic data only. Anyone can also sign up at `/signup`; all accounts share one ledger. Sign-up is off when `APP_ENV=production` unless `RECONCILE_SIGNUP=1`.

## Tests

```bash
python -m pytest tests -q              # offline; each test gets its own temporary database
python -m scripts.smoke_reconcile      # demo dataset vs ground truth (30/30)
python scripts/check_llm.py            # live check of the configured LLM provider (uses your key)
```

CI (`.github/workflows/ci.yml`) runs both on every push.

## Deploying on Render

`render.yaml` deploys three services: the Streamlit app, the API (`reconcileai-api`) and the website (`reconcileai-web`). The API and Streamlit app have separate databases. Set the website's `RECONCILE_API_URL` to the API's URL and the API's `RECONCILE_CORS` to the website's URL, then redeploy the website.

For the Streamlit app, `render.yaml` deploys the Docker image. Set `OPENROUTER_API_KEY` in the dashboard, or leave it empty for offline mode. Set the admin variables, or nobody can sign in. **The free plan has no persistent disk, so all data, including users and the audit log, is lost on restart.** `render.yaml` shows the disk settings for a paid plan.

## License

MIT
