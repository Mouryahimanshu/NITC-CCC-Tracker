# Development Roadmap

Milestones 1–6 have implementation in the repository. The Neon project and production branch are configured, but this workstation has not yet completed a live PostgreSQL connection. Gmail mailbox authorization and deployment configuration remain external setup items.

| Milestone | Scope | Depends on | Completion evidence |
|---|---|---|---|
| 1. Architecture and planning | Requirements, architecture, target structure, data model, APIs, worker, security, roadmap, decisions, AGENTS.md | None | Completed; slot size and timezone confirmed. |
| 2. Project setup | Initialize React/Vite/Tailwind and FastAPI; environment examples; Git hygiene; PostgreSQL config; docs/run instructions | Milestone 1 approval | Completed. |
| 3. Backend foundation | PostgreSQL/SQLAlchemy schema, room seed, users, auth/RBAC, room and read APIs | Milestone 2 | Implemented; local Neon URL is configured, connection verification pending. |
| 4. Booking engine | Requests, approval/rejection/cancellation, availability, slot allocations, conflicts, audit | Milestone 3; slot size/timezone confirmed | Implemented with transaction-backed unique slot allocation. |
| 5. Gmail integration | OAuth, IMAP read-only UID polling, extraction, parser/validator, dedupe, logs, retries, controlled baseline | Milestones 3–4; mailbox/sender/template configuration | Implemented; first authorization and live mailbox validation remain. |
| 6. Frontend | Student availability, faculty request/history, admin review and email logs; API integration | Milestones 3–5 | Implemented; live API use requires reachable Neon connectivity. |
| 7. Integration and verification | End-to-end workflow, conflict/concurrency, auth boundaries, parser cases, failure handling, security review | Milestones 3–6; PostgreSQL available | Frontend build and backend compilation succeed; live database scenarios remain. |
| 8. Documentation and deployment | Installation, configuration, API, architecture, deployment, worker operations, backup/recovery | Milestones 2–7; deployment target decision | Local runbook present; production deployment target and transaction support remain. |

## Dependency notes

- Milestone 1 decisions about slot granularity, timezone, user provisioning, visibility, and email trust affect schema/API behavior and should be resolved before implementing the dependent logic.
- The API and worker must share booking rules. Implementing the booking service before the importer reduces divergence.
- The worker can be developed and run independently from FastAPI, but it depends on shared configuration, database setup, and booking services.
- The admin email-log UI depends on the log schema and endpoints from the email integration milestone.
- Configure Neon PostgreSQL and initialize schema/seed data before live booking flows can run.
