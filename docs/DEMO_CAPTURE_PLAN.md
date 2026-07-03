# Demo Capture Plan — Company Brain

This plan turns the existing 7-minute demo flow (`docs/DEMO_RUNBOOK.md`) and founder talk
track (`docs/FOUNDER_DEMO_SCRIPT.md`) into an actual recording + screenshot capture session.
It does not redefine the demo — it schedules the capture of it. Read those two docs first;
this file only adds timing beats, a shot list, output file naming, and recording logistics.

Positioning stays exactly as in the runbook: **controlled-demo ready**, CI-validated, on
fictional "Acme Corp — Demo Workspace" data only.

---

## 1. Seven-minute recording plan

Follow `DEMO_RUNBOOK.md` setup and `FOUNDER_DEMO_SCRIPT.md` talk track for exact wording.
Timings below are the capture beats — hit record once and run straight through in one take
where possible; re-record a beat rather than trying to cut mid-flow.

| Time | Beat | What's on screen |
|---|---|---|
| 0:00–0:30 | Problem and positioning | Talking head or blank terminal; the opening line from `FOUNDER_DEMO_SCRIPT.md` ("Every company's real operating knowledge is scattered...") |
| 0:30–1:30 | Landing page and product promise | `/welcome` — hero, problem section, how-it-works, trust section with the mock approval panel, use cases, security section, CTA |
| 1:30–2:30 | Source-backed answer | Dashboard (`/`) into a run's Time-Travel snapshot dialog — show the exact retrieved sources and graph facts pinned by content-addressed digest at decision time |
| 2:30–3:30 | Approval queue | `/approvals` — walk one swipeable card: proposed action, critic risk score, reasons, blast radius; approve or reject it live |
| 3:30–4:30 | Contradiction / quarantine case | `/reconciliation` — the seeded "Enterprise Onboarding" SOP quarantined by conflicting PR #842; make the point that the system stops itself |
| 4:30–5:30 | Audit trail | `/audit` — HMAC-chained entries list; note that altering any line breaks the chain |
| 5:30–6:30 | Architecture credibility | Cite CI, not just claim it: FastAPI + Celery, Postgres/Redis/Weaviate/Neo4j, multi-tenant from the data model up, Alembic-managed schema, CI-proven live stack — reference the green run (28582152408 or 28581789446, all 3 jobs: backend, frontend, compose-live) |
| 6:30–7:00 | Honest roadmap and CTA | State the real gaps (no native Weaviate multi-tenancy — property-filter isolation today; no compliance certification held; observability is logs + health probes, Prometheus/OTel pending) and the close from `FOUNDER_DEMO_SCRIPT.md` |

Never say: "enterprise-ready," "native Weaviate multi-tenancy," "fully compliant" or any
held certification, "zero hallucination," or imply real customer traction. Say
"controlled demo-ready" instead.

---

## 2. Screenshots to capture

- [ ] `/welcome` — landing page
- [ ] Dashboard overview (`/`) — stat tiles, ingestion health, critic calibration chart, recent actions, critic verdicts
- [ ] Knowledge/source answer — the Time-Travel dialog showing retrieved sources and graph facts
- [ ] Approval queue (`/approvals`) — a card with critic risk score, reasons, blast radius
- [ ] Contradiction/quarantine case (`/reconciliation`) — the quarantined "Enterprise Onboarding" SOP vs. PR #842
- [ ] Audit trail (`/audit`) — the HMAC-chained entry list
- [ ] Health/readiness — terminal or browser screenshot of `curl /health/live` and `/health/ready`, both returning 200
- [ ] CI green run — GitHub Actions run showing all 3 jobs (backend, frontend, compose-live) green; screenshot run [28582152408](https://github.com/smellywesley/Company-Brain/actions/runs/28582152408) or [28581789446](https://github.com/smellywesley/Company-Brain/actions/runs/28581789446)

---

## 3. Output files

```
company-brain-demo-7min.mp4          # the screen recording
company-brain-screenshots/
  01-welcome.png
  02-dashboard.png
  03-time-travel.png
  04-approvals.png
  05-reconciliation.png
  06-audit.png
  07-health-ready.png
  08-ci-green.png
company-brain-demo-notes.md          # short notes file, timestamped to match the recording
```

`company-brain-demo-notes.md` should log what was said/shown at each timestamp (matching the
table in section 1) so anyone editing the raw footage later can cut without re-watching the
whole take.

---

## 4. Recording practicalities

- **Run the capture on a host where Docker actually works.** This repo's local dev
  environment could not get Docker's daemon to initialize, confirmed across multiple work
  sessions — do not burn more time on it here. Capture either on a separate host where
  `docker compose up -d --build` genuinely comes up, or lean on the CI-validated flow (the
  green GitHub Actions run) as the proof point for architecture claims instead of a live
  local stack.
- Keep browser zoom and window size fixed for the whole session (e.g. 100% zoom,
  1280x800) so all screenshots are visually consistent.
- Close notification banners/OS notifications before recording.
- Use the seeded demo data (`make demo-seed`) so the flow is deterministic and repeatable
  between takes.
