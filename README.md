# 🧠 Company Brain

**AI-Powered Knowledge Platform — Turn Your Company's Scattered Knowledge Into Executable Intelligence**

[![CI/CD](https://github.com/your-org/company-brain/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/company-brain/actions)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Security: OWASP](https://img.shields.io/badge/Security-OWASP_Compliant-green.svg)](.github/workflows/ci.yml)

---

## What Is Company Brain?

Company Brain is a **modular, customizable AI platform** that aggregates fragmented knowledge across your organization's tools (Slack, Notion, GitHub, Zendesk, Stripe, and more) and converts it into a **living, executable knowledge map**.

Unlike simple RAG chatbots, Company Brain doesn't just answer questions — it **acts**. Its multi-agent architecture autonomously handles workflows like refund processing, incident response, and lead qualification, with built-in **CriticAgent** validation and **human-in-the-loop** approval for high-stakes actions.

### Key Capabilities

| Capability | Description |
|-----------|-------------|
| 🔌 **Universal Connectors** | Plug-and-play ingestion from Slack, Notion, GitHub (extensible to any SaaS tool) |
| 🧠 **Living Memory** | Vector embeddings + knowledge graph that evolve as your company grows |
| 🤖 **Multi-Agent Workflows** | Concurrent sub-agents that retrieve → reason → act → validate |
| 🔍 **CriticAgent** | Independent second-pass validator enforcing PII, RBAC, financial limits, and policy compliance |
| 🔒 **Enterprise Security** | OIDC/JWT auth, RBAC, HMAC audit chains, PII redaction (Presidio), rate limiting, input sanitization |
| 🏢 **White-Label Ready** | JSON-configurable workflows, YAML RBAC policies — retrofit to any organization in minutes |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js)                       │
│           Premium Dashboard · Dark Mode · Glassmorphism        │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTPS
┌──────────────────────▼───────────────────────────────────────┐
│                   Backend (FastAPI)                            │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Security Middleware Stack                                │  │
│  │ SecurityHeaders → AuditLog → RateLimiter → CORS         │  │
│  │ → OIDCAuth → InputSanitization                          │  │
│  └─────────────────────────────────────────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │ WorkflowAgent│→ │ CriticAgent  │→ │ ActionExecutor    │   │
│  │ (Orchestrator)│  │ (Validator)  │  │ (Stripe, Slack…)  │   │
│  └──────────────┘  └──────────────┘  └───────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ LLMAdapter (Gemini · OpenAI · Anthropic)                 │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────┬──────────────┬──────────────┬─────────────────────────┘
       │              │              │
┌──────▼──────┐ ┌─────▼─────┐ ┌─────▼─────┐
│  Weaviate   │ │   Neo4j   │ │   Kafka   │
│ Vector DB   │ │ Knowledge │ │  Message  │
│ (encrypted) │ │   Graph   │ │ Bus (TLS) │
└─────────────┘ └───────────┘ └───────────┘
       ▲              ▲
┌──────┴──────────────┴───────────────────┐
│         Ingestion Pipeline               │
│  Slack · Notion · GitHub connectors      │
│  PII Redaction (Presidio) → Chunking     │
│  → Embedding (sentence-transformers)     │
│  → Weaviate Upsert                       │
└──────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Node.js 20+ (for frontend development)
- Python 3.12+ (for backend development)

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/company-brain.git
cd company-brain
cp .env.example .env
# Edit .env with your API keys (Slack, Notion, GitHub, LLM provider)
```

### 2. Start All Services

```bash
docker compose up -d
```

This starts: **frontend** (port 3000), **backend** (port 8000), **Weaviate** (port 8080), **Neo4j** (port 7474), **Kafka** (port 9092), and **Vault** (port 8200).

### 3. Open the Dashboard

Navigate to [http://localhost:3000](http://localhost:3000) to access the Company Brain dashboard.

### 4. Trigger Your First Ingestion

```bash
curl -X POST http://localhost:8000/ingest/slack \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json"
```

---

## Project Structure

```
company-brain/
├── frontend/                  # Next.js (React + TypeScript)
│   ├── src/app/               # App Router pages & layouts
│   ├── src/components/        # Reusable UI components
│   └── Dockerfile             # Hardened multi-stage build
│
├── backend/                   # FastAPI (Python)
│   ├── app/
│   │   ├── agents/            # LLMAdapter, BaseAgent, CriticAgent, WorkflowAgent
│   │   ├── middleware/        # Auth, RBAC, audit, rate-limit, sanitizer
│   │   ├── schemas/           # Pydantic models (documents, workflows)
│   │   ├── workflows/         # Pre-built workflows (refund automation)
│   │   └── main.py            # FastAPI entry point
│   ├── requirements.txt
│   └── Dockerfile             # Hardened, non-root
│
├── ingestion/                 # Data connectors & embedding pipeline
│   ├── base_connector.py      # Abstract base + registry
│   ├── slack_connector.py
│   ├── notion_connector.py
│   ├── github_connector.py
│   └── embedding_pipeline.py  # Chunking → embedding → Weaviate
│
├── .github/workflows/ci.yml   # CI/CD (Bandit, Trivy, ESLint, npm audit)
├── docker-compose.yml         # Full stack orchestration
├── .env.example               # Configuration template
└── .gitignore
```

---

## Security

Company Brain is built with **security-by-design** principles, targeting compliance with **GDPR**, **SOC 2**, **ISO 27001**, and **HIPAA**.

| Layer | Mechanism |
|-------|-----------|
| **Authentication** | OIDC/JWT via Okta (RS256/ES256, JWKS caching) |
| **Authorization** | YAML-based RBAC (admin, manager, engineer, viewer) |
| **Data at Rest** | AES-256 encryption (Weaviate, Neo4j) |
| **Data in Transit** | TLS/mTLS between all services |
| **PII Protection** | Microsoft Presidio redaction before storage |
| **Audit Trail** | HMAC-SHA256 chained JSONL logs (tamper-evident) |
| **Rate Limiting** | Token-bucket per user/IP (100 req/min API, 10 req/min workflows) |
| **Input Sanitization** | XSS, SQL injection, HTML tag stripping |
| **Security Headers** | CSP, HSTS, X-Frame-Options, X-Content-Type-Options |
| **Secrets** | HashiCorp Vault (no secrets in source code) |
| **CI/CD Scanning** | Bandit (SAST), Trivy (containers), npm audit, OWASP ZAP (DAST) |

---

## Adding a New Connector

1. Create a new file in `ingestion/` (e.g., `zendesk_connector.py`)
2. Extend `BaseConnector` and set `SOURCE_NAME`
3. Implement `authenticate()`, `fetch_raw()`, and `normalize()`
4. Register with `@ConnectorRegistry.register`
5. PII redaction is inherited automatically via `self.redact_pii()`

```python
from ingestion.base_connector import BaseConnector, ConnectorRegistry, NormalizedDocument

@ConnectorRegistry.register
class ZendeskConnector(BaseConnector):
    SOURCE_NAME = "zendesk"

    def authenticate(self) -> None: ...
    def fetch_raw(self) -> list[dict]: ...
    def normalize(self, raw_item: dict) -> NormalizedDocument: ...
```

---

## Adding a New Workflow

1. Create a new file in `backend/app/workflows/`
2. Instantiate an `LLMAdapter`, `CriticAgent`, and `WorkflowAgent`
3. Define your action executors (async functions)
4. Wire it up in `main.py` or trigger via API

See [`refund_automation.py`](backend/app/workflows/refund_automation.py) for a complete reference implementation.

---

## LLM Providers

Company Brain supports multiple LLM providers through the `LLMAdapter`:

| Provider | Models | Context Window |
|----------|--------|----------------|
| **Google Gemini** | gemini-1.5-pro, gemini-2.0-flash | Up to 1M tokens |
| **OpenAI** | gpt-4o, gpt-4o-mini | Up to 128K tokens |
| **Anthropic** | claude-3.5-sonnet, claude-3-haiku | Up to 200K tokens |

Switch providers by changing `LLM_PROVIDER` and `LLM_API_KEY` in your `.env` file.

---

## License

Core engine: **Apache License 2.0** — free for commercial use, modification, and distribution.

---

<p align="center">
  Built with ❤️ for the future of enterprise AI.
</p>
