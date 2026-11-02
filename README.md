# FinanceFlow

FinanceFlow is a simulated financial invoice financing and reconciliation platform engineered to explore, validate, and stress-test core fintech transactional workflows, state machines, and reconciliation pipelines.

---

## 1. Domain & Workflow Overview

FinanceFlow simulates the lifecycle of modern receivables factoring / invoice financing:
1. **Invoice Submission**: A registered business submits an issued invoice.
2. **Financing Request & Validation**: The platform evaluates eligibility, calculates advance amounts and fees using high-precision financial arithmetic (`Decimal`), and validates state transitions.
3. **Approval**: An underwriter or automated risk engine approves or rejects the financing request.
4. **Downstream Disbursement**: Idempotent disbursement execution via an external disbursement service client (simulated / mockable).
5. **Ledger & Reconciliation**: Real-time recording of ledger transactions and automated reconciliation against external bank/clearinghouse records to catch discrepancies.

---

## 2. Technology Stack

- **Runtime**: Python 3.11+
- **Web Framework**: FastAPI (Async ASGI)
- **Data Validation & Schemas**: Pydantic v2 & Pydantic Settings
- **ORM & Data Layer**: SQLAlchemy 2.x (Async Engine with `asyncpg`, sync migrations with `psycopg3`)
- **Database**: PostgreSQL 16
- **Database Migrations**: Alembic
- **HTTP Client**: HTTPX (Async external API communication with retry & circuit breaker readiness)
- **Testing**: Pytest, Pytest-Asyncio, Pytest-Mock, Testcontainers
- **Code Quality**: Ruff (Linter & Formatter), Mypy (Strict Type Checking)
- **Containerization & CI**: Docker Compose, GitHub Actions

---

## 3. Project Structure

```text
FinanceFlow/
├── .github/
│   └── workflows/
│       └── ci.yml                     # Automated Lint, Typecheck, and Test Pipeline
├── alembic/
│   ├── versions/                      # Migration revisions
│   └── env.py                         # Migration runtime environment
├── src/
│   └── financeflow/
│       ├── __init__.py
│       ├── main.py                    # FastAPI application factory & lifespan
│       ├── api/                       # Presentation layer
│       │   ├── dependencies.py        # FastAPI dependency injection providers
│       │   └── v1/
│       │       ├── router.py          # V1 route aggregator
│       │       └── endpoints/         # Invoices, financing, disbursements, reconciliation
│       ├── core/                      # Cross-cutting configurations and utilities
│       │   ├── config.py              # Pydantic Settings (12-factor env config)
│       │   ├── exceptions.py          # Domain & infrastructure exception hierarchy
│       │   ├── logging.py             # Structured logging configuration
│       │   └── precision.py           # Financial precision, rounding & currency rules
│       ├── db/                        # Database connectivity & session management
│       │   ├── session.py             # Async SQLAlchemy engine & sessionmaker
│       │   └── base.py                # Declarative Base metadata
│       ├── models/                    # SQLAlchemy 2.x ORM models
│       │   ├── business.py
│       │   ├── invoice.py
│       │   ├── financing_request.py
│       │   ├── disbursement.py
│       │   ├── ledger.py
│       │   └── audit_log.py
│       ├── schemas/                   # Pydantic v2 input/output schemas
│       │   ├── common.py
│       │   ├── invoice.py
│       │   ├── financing.py
│       │   ├── disbursement.py
│       │   └── reconciliation.py
│       ├── repositories/              # Persistence abstraction (CRUD & query logic)
│       │   ├── base.py
│       │   ├── invoice_repo.py
│       │   ├── financing_repo.py
│       │   ├── disbursement_repo.py
│       │   └── ledger_repo.py
│       ├── services/                  # Pure domain business logic & state transitions
│       │   ├── invoice_service.py
│       │   ├── financing_service.py
│       │   ├── disbursement_service.py
│       │   └── reconciliation_service.py
│       └── integrations/              # External clients & adapters
│           └── disbursement/
│               ├── client.py          # HTTPX-based external disbursement adapter
│               └── schemas.py         # Third-party payload contracts
├── tests/
│   ├── conftest.py                    # Shared test fixtures & DB session overrides
│   ├── fixtures/                      # Mock payloads, factory boy / test data
│   ├── unit/                          # Isolated business logic & mathematical precision tests
│   └── integration/                   # Database repository & API integration tests
├── .env.example                       # Reference environment variables
├── .gitignore
├── alembic.ini                        # Alembic configuration
├── docker-compose.yml                 # Local PostgreSQL + WireMock + API containers
├── Dockerfile                         # Production-grade multi-stage container build
└── pyproject.toml                     # Modern PEP 621 packaging, Ruff, Mypy, Pytest config
```

---

## 4. Setup Instructions

### Prerequisites
- Python 3.11 or higher
- Docker & Docker Compose (v2)
- Git

### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository
git clone <repository_url> financeflow
cd financeflow

# Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate  # On Windows PowerShell: .venv\Scripts\Activate.ps1

# Upgrade packaging tools and install project in editable mode with dev dependencies
pip install --upgrade pip
pip install -e ".[dev]"
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Review `.env` to verify credentials, database connection strings, and downstream mock endpoint configs.

### 3. Spin Up Supporting Infrastructure (PostgreSQL & WireMock)

```bash
docker compose up -d postgres mock-disbursement-service
```

Verify that PostgreSQL is healthy:
```bash
docker compose ps
```

### 4. Database Migrations

Apply Alembic migrations to initialize the schema:
```bash
alembic upgrade head
```

### 5. Running the Application

Start the local development server with auto-reload:
```bash
uvicorn financeflow.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive API documentation will be accessible at:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check**: [http://localhost:8000/health/live](http://localhost:8000/health/live)

---

## 5. Engineering Standards & Quality Checks

### Code Formatting & Linting (Ruff)
```bash
# Check lint issues
ruff check .

# Check formatting
ruff format --check .

# Auto-fix lint and formatting
ruff check --fix .
ruff format .
```

### Static Type Checking (Mypy Strict)
```bash
mypy src
```

### Test Suite Execution (Pytest)
```bash
# Run unit tests
pytest -m unit

# Run integration tests (requires PostgreSQL container running)
pytest -m integration

# Run full test suite with coverage report
pytest --cov=financeflow --cov-report=term-missing
```

---

## 6. Financial Invariants & Guidelines

1. **Strict Decimal Usage**: Floating-point values (`float`) are strictly forbidden for monetary amounts, interest calculations, rates, or balance totals.
2. **Explicit Precision & Rounding**: All calculations must use `Decimal` with `ROUND_HALF_UP` banking rules, standard currency precision (`DECIMAL(18, 2)` for currency units and `DECIMAL(5, 4)` for interest/advance percentages).
3. **Idempotency**: All disbursement requests must carry a unique `idempotency_key` ensuring non-repeatable fund transfers.
4. **Audit Trail**: Every state mutation is preserved via immutable event/audit records.
