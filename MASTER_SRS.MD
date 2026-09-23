# Software Requirements Specification (SRS) & Coding Agent Instruction Manual

**Project:** Self-Hosted AI Pre-Construction, Estimation & Procurement Platform (`INSTALLTEC/RFP/2026/PCP-01` — Mid-Market Value-Engineered Edition)

**Target Architecture:** Contabo Cloud Trial Hosting (6 Months) $\rightarrow$ Seamless On-Premise Docker Migration

---

## 1. Executive Directive & Architectural Principles

You are tasked with building a production-grade, secure, air-gap-ready enterprise application tailored for mid-market regional contractors.

### Core Constraints & Directives:

1. **Zero External Cloud Dependencies for Data/AI**: All application processing, database records, vector search, and AI model inference must run entirely within the deployment boundary (initially hosted on a dedicated Contabo GPU instance, easily movable to on-premise physical servers via Docker Compose). No calls to commercial external AI APIs (OpenAI, Anthropic, etc.).
2. **Value-Engineered AI Stack**: Avoid resource-heavy 32B+ models and complex local LoRA training stores. Use right-sized, quantized **7B/8B open-weight models** via `vLLM` and context-aware **RAG via `pgvector**` for continuous learning.
3. **Containerized Portability**: Zero Kubernetes (K3s) complexity. The entire stack must orchestrate via a single `docker-compose.yml` file.
4. **CAD Ingestion Standard**: Native parsing of standard **DXF and Vector PDF exports**, bypassing third-party proprietary CAD runtime licensing (like ODA).
5. **Strict Enterprise Security**: Keycloak authentication with **MFA (TOTP)**, server-side data-layer RBAC (PostgreSQL RLS), and append-only hash-chained audit trails.

---

## 2. Monorepo & GitHub Workflow Structure

Organize the repository using the following monorepo layout:

```text
/installtec-ai-platform
├── backend/                  # FastAPI app, database models, RAG engine, Celery workers
├── frontend/                 # React 18, Vite, Tailwind CSS, AG Grid Community
├── ai-service/               # vLLM runner configuration, prompt templates, extraction pipelines
├── deploy/                   # Docker Compose, environment templates (.env.example)
└── docs/                     # API specs and admin runbooks

```

### Git Standards for the Agent:

* **Branching Model**: GitHub Flow (`main` for production-ready code, feature branches for development via Pull Requests).
* **Commit Conventions**: Use conventional commits (`feat(module-a): add vendor duplicate detection`, `fix(takeoff): resolve scale calculation drift`).
* **Secret Management**: Never commit `.env` or credentials. Always rely on environment variables mapped via `.env.example`.

---

## 3. Technology Stack Specification

| Layer | Selected Technology | Licensing / Rationale |
| --- | --- | --- |
| **Backend Framework** | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic | Async native, auto-generates OpenAPI 3.1 specs.

 |
| **Frontend Framework** | React 18, TypeScript, Vite, Tailwind CSS, AG Grid Community | Fast virtualized rendering for massive 4,200+ line BOQ grids.

 |
| **Relational Database** | PostgreSQL 16 with `pgvector` extension | Single datastore for transactional data, bi-temporal rates, and embeddings.

 |
| **Object Storage** | SeaweedFS (S3-compatible) | Lightweight, high-performance Apache 2.0 object storage for drawings and quotes.

 |
| **AI Inference Engine** | `vLLM` (for vision-language/reasoning models) & `ONNX Runtime` (CPU tasks) | High-throughput continuous batching optimized for a single GPU instance.

 |
| **Identity & Access** | Keycloak + TOTP Authenticator Support | Standards-based OAuth2/OIDC identity provider with built-in MFA.

 |
| **Orchestration** | Docker & Docker Compose | Simplified container isolation for Contabo cloud and local office migration.

 |

---

## 4. Detailed Feature & Module Scope

### Module A: Enterprise Data & Governance Core

* **Vendor Master & Duplicate Detection**: Unified repository with fuzzy matching on trade licenses and contact fingerprints.


* **Configurable Trade Taxonomy**: Hierarchical trade categories (earthworks, asphalt, concrete, MEP, utilities) manageable via admin UI.


* **Prequalification & Statutory Register**: Effective-dated status tracking and municipal/transport compliance certificate alerts (Dubai Municipality, RTA, DEWA, Civil Defence, etc.).


* **Master Cost Library**: Bi-temporal component-level unit rate decomposition (material, labour, equipment, subcontractor, indirect) supporting historical reconstructions (A-10).


* **Approval Workflows & Security**: Multi-tier threshold routing (Estimator $\rightarrow$ MD). Keycloak integration enforcing MFA and server-side PostgreSQL Row-Level Security (RLS).


* **Immutable Audit Trail**: Append-only, hash-chained audit logging capturing all create, read, update, delete, approval, and export actions with timestamps and IP addresses.



### Module B: AI Takeoff & Estimation Engine

* **Drawing Ingestion**: Vector PDF and DXF parsing with automated multi-sheet indexing.


* **Scale & Title Block Extraction**: Multi-signal scale detection (scale bars, dimensions, text annotations) with manual two-point fallback calibration.


* **Infrastructure Geometry**: Automated alignment measurements (road centrelines, kerbs, boundaries), corridor areas, trench prismoidal volumes, and pipe network graph topologies.


* **Clustered Typology Recognition**: Master layout clustering for repeating villa/unit types, single-unit deep quantification, and controlled multiplication with explicit variant deltas.


* **BOQ Reconciliation & Discrepancy Auditing**: Hierarchical tender BOQ parsing, semantic cross-referencing against AI takeoff using `pgvector` RAG, and three-class discrepancy flagging.


* **Visual Traceability & Adjudication**: Split-pane UI linking quantities directly to drawing regions, confidence indicators, and non-destructive estimator overrides.



### Module C: AI Procurement & Bid Leveling

* **Automated RFQ Generation & Dispatch**: Vendor matching by trade/geography, template-driven RFQ generation, and bulk email dispatch via Contabo/client SMTP relays.


* **Email Quotation Ingestion**: IMAP mailbox polling for unstructured quotations (PDF, scans, photos, Excel) using quantized 7B vision-language models.


* **Normalisation & Semantic Mapping**: Arithmetic verification, unit conversion, currency normalisation, and semantic mapping of vendor line items to package BOQs.


* **Bid Leveling & NLP Exclusion Detection**: Side-by-side comparative matrices and local 7B LLM scanning of quotation text to flag buried exclusions (dewatering, testing, etc.) with explicit source text citations.



### Module D: Executive Cockpit & Pricing Engine

* **Bid Settlement & Margin Simulation**: Consolidation of direct costs, subcontractor quotes, plant allowances, site overheads, and margins into a traceable settled bid. Real-time in-memory simulation across markups and volatility allowances.


* **Client BOQ Export**: Exporting final pricing back into the client's exact tender BOQ workbook format (preserving formulas, merged cells, and sheet structure).


* **Win/Loss Data Capture**: Lightweight historical outcome logging from day one.



### Module E: Post-Award Contract Management (Roadmap Schema Architecture)

* **Phase 1 Schema Readiness**: Database design must natively support future award-to-contract carry-forward, live exclusion registers, revision comparisons, and outturn cost write-backs into the rate library without major schema refactoring.



---

## 5. Security, Authentication & Data Protection Specifications

1. **Authentication Flow**:
* Users authenticate via Keycloak UI screens.
* **MFA Enforcement**: Keycloak must be configured to prompt users for a Time-based One-Time Password (TOTP) from an authenticator app (Google Authenticator, etc.) on first login and sensitive actions.
* Sessions maintained via secure, HTTP-only, encrypted JWT cookies.


2. **Data-Layer Authorization (RBAC)**:
* Define roles: `estimator`, `lead_estimator`, `procurement_head`, `bd_director`, `managing_director`.


* Enforce PostgreSQL RLS policies matching user tenant/project scope dynamically.


3. **Air-Gapped Data Privacy**:
* All data encrypted at rest (AES-256) and in transit (TLS 1.3).
* Zero external tracking scripts, zero telemetry, and zero outbound internet access requirements for core workflows.



---

## 6. Docker Compose Deployment Blueprint (`deploy/docker-compose.yml`)

Instruct your coding agent to scaffold the deployment using this production-ready compose template:

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: installtec_postgres
    environment:
      POSTGRES_DB: installtec_core
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: installtec_redis
    restart: unless-stopped

  seaweedfs:
    image: chrislusf/seaweedfs:latest
    container_name: installtec_seaweedfs
    command: "server -dir=/data -s3"
    volumes:
      - swdata:/data
    ports:
      - "8333:8333"
      - "9333:9333"
    restart: unless-stopped

  vllm:
    image: vllm/vllm-openai:latest
    container_name: installtec_vllm
    environment:
      - MODEL=Qwen/Qwen2.5-VL-7B-Instruct
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    ports:
      - "8000:8000"
    restart: unless-stopped

  backend:
    build: ../backend
    container_name: installtec_backend
    environment:
      - DATABASE_URL=postgresql://postgres:${DB_PASSWORD}@postgres:5432/installtec_core
      - REDIS_URL=redis://redis:6379/0
      - VLLM_API_BASE=http://vllm:8000/v1
      - S3_ENDPOINT=http://seaweedfs:8333
    ports:
      - "8001:8000"
    depends_on:
      - postgres
      - redis
      - vllm
    restart: unless-stopped

  frontend:
    build: ../frontend
    container_name: installtec_frontend
    ports:
      - "3000:80"
    depends_on:
      - backend
    restart: unless-stopped

volumes:
  pgdata:
  swdata:

```

---

