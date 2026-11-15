# Architecture and Planning

## 1. Project understanding

CCC currently communicates room bookings through email. The system provides a date-range availability timeline for six rooms (T1–T6), faculty booking requests, administrator review and management, and a separately running worker that imports valid booking emails. Imported valid bookings and administrator-approved faculty requests become confirmed bookings. Students can view availability but cannot mutate data.

Operating hours are 08:00–20:00 IST (`Asia/Kolkata`). Bookings can start and end on 30-minute boundaries, span one or more half-hour slots, and are represented as half-open intervals `[start, end)`, so adjacent reservations are permitted. Pending requests do not consume availability.

All dates and times are interpreted in the configured campus timezone `Asia/Kolkata` (IST). Persist booking date and slot boundaries as local date plus minute-of-day/slot identifiers for this fixed-hours domain; use UTC timestamps for audit and processing events.

## 2. Proposed architecture

```text
Browser (React/Vite)
    | HTTPS, JSON REST, session/token credential
    v
FastAPI application
  routes -> authentication/authorization -> booking/email-log services
                                      |                    |
                                      +------ SQLAlchemy ----+--> PostgreSQL (Neon)

Independent Python email worker
  OAuth token provider -> IMAP SSL/XOAUTH2 -> extraction -> parser -> validator
                                                   |                         |
                                                   +---- email_logs ----------+
                                                   +---- booking service ----> PostgreSQL
```

The API and worker share domain/service modules and database configuration, but the worker runs as a separate process. Routes perform HTTP translation only. Booking rules live in services and are reused by faculty approvals and email imports. SQLAlchemy sessions keep persistence operations out of parsing and HTTP translation code.

## 3. Recommended repository structure

```text
.
├── AGENTS.md
├── README.md
├── docs/
│   ├── architecture.md
│   └── roadmap.md
├── backend/
│   ├── pyproject.toml                 # choose dependency/tooling format at setup
│   ├── .env.example
│   ├── app/
│   │   ├── main.py
│   │   ├── api/v1/                    # routers and shared HTTP dependencies
│   │   ├── core/                      # settings, logging, security
│   │   ├── db/                        # SQLAlchemy engine, relational models, sessions
│   │   ├── schemas/                   # Pydantic request/response DTOs
│   │   ├── domain/                    # enums and domain types
│   │   ├── services/                  # auth, booking, availability, audit
│   │   └── email/                     # OAuth, IMAP, extraction, parsing, validation
│   ├── worker.py                      # independent polling entry point
│   └── tests/
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── src/
    │   ├── app/                       # router and app shell
    │   ├── api/                       # HTTP client and API functions
    │   ├── components/                # reusable UI
    │   ├── features/                  # availability, requests, admin
    │   └── styles/
    └── public/
```

This is a target structure, not a claim that these directories or components exist yet. Tests and dependency configuration are implemented in their corresponding milestones.

## 4. PostgreSQL relational schema

Use generated integer primary keys and foreign keys. Store enum values in stable uppercase strings. Use database constraints for uniqueness and references, `DATE` for campus-local booking dates, and timezone-aware timestamps for audit and processing events.

### `users` table
- `_id`, `username` (normalized, unique), `passwordHash`, `role` (`STUDENT`, `FACULTY`, `ADMIN`), `displayName`, `active`, timestamps.
- Never store plaintext passwords. Do not use institutional email as an authentication mechanism. A contact email may be optional profile data only.
- Index: unique `{username: 1}`.

### `rooms` table
- `_id`, `code` (`T1`…`T6`), `name`/optional metadata, `active`, timestamps.
- Index: unique `{code: 1}`. Seed the six initial fixed rooms idempotently.

### `room_maintenance` table
- `roomId`, `roomCode`, `maintenanceDate`, `startMinute`, `endMinute`, `note`, `active`, `createdBy`, `createdAt`.
- Maintenance windows occupy half-hour units and are visible on the schedule. Overlap with confirmed bookings is rejected; overlapping faculty requests/booking approvals are blocked while the window is active.
- Admins can clear a window without deleting its audit history.

### `bookings` table
- `_id`, `roomId`, `bookingDate` (`YYYY-MM-DD`, campus-local date), `startMinute`, `endMinute`, `purpose`, `source` (`FACULTY_REQUEST`, `EMAIL`), `sourceRequestId` or `sourceEmailLogId`, `createdBy` (user id or system marker), `status` (`CONFIRMED`, `CANCELLED`), `cancelledBy`, `cancelledAt`, timestamps.
- A booking is a confirmed interval; do not store pending requests here.
- Query index: `{roomId: 1, bookingDate: 1, status: 1, startMinute: 1}`.
- Overlap cannot be prevented by an ordinary unique index over arbitrary intervals. Use the slot allocation strategy in section 10.

### `booking_requests` table
- `_id`, `facultyUserId`, `roomId`, `bookingDate`, `startMinute`, `endMinute`, `purpose`, `status` (`PENDING`, `APPROVED`, `REJECTED`, `CANCELLED`), `reviewedBy`, `reviewedAt`, `decisionNote`, `resultingBookingId`, timestamps.
- Indexes: `{facultyUserId: 1, createdAt: -1}` and `{status: 1, createdAt: 1}`.

### `email_logs` table
- `_id`, `mailboxKey`, `uidValidity`, `imapUid`, `messageId`, `sender`, `subject`, `receivedAt`, `status` (`RECEIVED`, `PROCESSING`, `PROCESSED`, `INVALID`, `CONFLICT`, `FAILED`), extracted/normalized booking fields when available, `bookingId`, `errorCode`, safe `errorDetail`, `attemptCount`, `processedAt`, timestamps.
- Unique deduplication index on `{mailboxKey: 1, messageId: 1}` when Message-ID exists. Also unique `{mailboxKey: 1, uidValidity: 1, imapUid: 1}` as mailbox cursor identity. Treat missing Message-ID with UID identity and record the condition.
- Avoid retaining full email bodies unless a defined operational need and retention policy justify it. Do not store credentials/tokens.
- Index: `{status: 1, receivedAt: -1}`.

### `audit_logs` table
- `_id`, `actorUserId` (nullable for system), `action`, `entityType`, `entityId`, `details` (allowlisted, no secrets), `createdAt`, request/correlation identifier.
- Indexes: `{entityType: 1, entityId: 1, createdAt: -1}`, `{actorUserId: 1, createdAt: -1}`.

### `slot_allocations` table
- One row per occupied 30-minute slot: `_id`, `roomId`, `bookingDate`, `slotId` (the start minute of day), `bookingId`, `createdAt`.
- Unique index `{roomId: 1, bookingDate: 1, slotId: 1}`. This is the database-level contention guard. A booking spanning multiple slots claims every slot.

### Transactions and Neon

Approval/import runs in a PostgreSQL transaction: create the booking, claim every half-hour slot, update the request/email log, and write the audit record atomically. The unique `(room_id, booking_date, slot_id)` constraint prevents concurrent overlaps; any constraint failure rolls back the entire transaction.

## 5. Entity/service responsibilities

- **User**: application identity, password hash, role, active state.
- **Room**: stable room code and active state.
- **BookingRequest**: faculty-submitted proposal and decision lifecycle; does not block availability while pending.
- **Booking**: confirmed or cancelled reservation with normalized interval and provenance.
- **SlotAllocation**: atomic occupancy claim used for concurrency protection.
- **EmailLog**: durable processing state, deduplication identity, parsed result, and errors.
- **AuditLog**: append-only record of administrator and system actions.
- **AuthService**: password verification, login/session/token issuance, role checks.
- **BookingService**: interval validation, approval, cancellation, occupancy claim/release, audit coordination.
- **AvailabilityService**: bounded date-range schedule and free-slot calculation from confirmed bookings/allocations.
- **EmailParser/Validator**: deterministic extraction and domain validation without database side effects.
- **EmailProcessor**: idempotent state transitions and calls to BookingService.
- **ImapClient**: read-only mailbox connection, UID-based retrieval and reconnect behavior.

## 6. REST API proposal

Base path: `/api/v1`. Return JSON; use Pydantic schemas. Authentication uses application credentials, with secure password hashing and an HTTP-only secure cookie session or short-lived bearer token plus refresh strategy selected during setup. Cookies are preferable for a same-site browser deployment; CSRF protection is required if cookie authentication is chosen.

| Method/path | Access | Purpose |
|---|---|---|
| `POST /auth/login` | Public | Authenticate username/password; issue session/token. |
| `POST /auth/logout` | Authenticated | End session or revoke refresh credential. |
| `GET /auth/me` | Authenticated | Return current user's safe profile and role. |
| `GET /rooms` | Public or authenticated | List active rooms. |
| `GET /rooms/availability?from=YYYY-MM-DD&days=14` | Public | Room booking timeline and free half-hour slots; maximum range is 28 days. |
| `GET /bookings/{bookingId}` | Authenticated | Booking detail subject to role/privacy policy. |
| `POST /booking-requests` | Faculty | Create pending request. |
| `GET /booking-requests/mine` | Faculty | List caller's requests and outcomes. |
| `GET /admin/booking-requests?status=PENDING` | Admin | Review queue. |
| `POST /admin/booking-requests/{id}/approve` | Admin | Atomically claim slots and confirm booking; conflict returns `409`. |
| `POST /admin/booking-requests/{id}/reject` | Admin | Reject with optional decision note and audit entry. |
| `POST /admin/bookings/{id}/cancel` | Admin | Cancel booking, release allocations, record audit. |
| `GET /admin/room-maintenance?from=YYYY-MM-DD&days=28` | Admin | List active maintenance windows in a bounded date range. |
| `POST /admin/room-maintenance` | Admin | Mark a room under maintenance for one date/time range; conflicts with confirmed bookings return `409`. |
| `POST /admin/room-maintenance/{id}/clear` | Admin | Clear a maintenance window and audit the change. |
| `GET /admin/email-logs` | Admin | Filter processing status/date; paginate. |
| `GET /admin/email-logs/{id}` | Admin | Inspect safe headers, parsed fields, and errors. |
| `GET /admin/audit-logs` | Admin | Filter/paginate audit events. |
| `GET /health` | Public/internal | Liveness only; do not reveal secrets or dependency details. |

Use `401` for missing/invalid authentication, `403` for insufficient role, `404` for absent or intentionally concealed resources, `422` for schema/domain input errors, `409` for slot conflict or invalid state transition, and `503` for temporary dependency failure. Use a consistent error body with stable code, message, and optional field errors. Add pagination and bounded filters to administrative lists.

## 7. Email worker architecture and sequence

1. Load configuration from environment and OAuth token material from a protected local credential location. Restrict operation to an explicit mailbox identity; never print tokens.
2. Connect to `imap.gmail.com:993` over TLS and authenticate with XOAUTH2. Select the intended mailbox read-only.
3. Read `UIDVALIDITY`; compare it with persisted mailbox state. A changed validity epoch resets UID cursor interpretation, not message deduplication by Message-ID.
4. Search/fetch messages by UID greater than the stored high-water mark, not only `UNSEEN`. Fetch headers/body using `BODY.PEEK` and keep originals unchanged.
5. Create or locate an `email_logs` record by Message-ID and UID identity. Persist `RECEIVED`, then transition to `PROCESSING` with retry-safe state updates.
6. Extract MIME text and required headers; decode safely. Identify booking messages using configured deterministic rules. Non-booking mail is not a booking failure; record the chosen handling policy (ignore with cursor advance, or log as non-booking—decision needed).
7. Parse room, date, start/end, purpose. Keep extraction, parsing, and validation separate. Normalize date/time into campus timezone and minute/slot values.
8. Validate room, date, operating hours, interval order, required purpose, sender policy, and supported slot granularity. Invalid input becomes `INVALID` with a clear safe reason.
9. Ask BookingService to claim slots and create a confirmed booking idempotently. A collision becomes `CONFLICT`; database/network/temporary errors become `FAILED` and are retryable.
10. Mark success `PROCESSED`, link booking, write audit record, and advance durable UID cursor only after the message has been durably classified/recorded. Reconnect with bounded backoff; poll every 30 seconds by default.
11. Admin endpoints expose failures/conflicts for review. Provide an explicit controlled baseline/backfill command; never silently import the entire history at first launch.

Ensure state transitions tolerate worker restart and duplicate delivery. A per-message processing lease/claim prevents two worker instances from processing the same message simultaneously; unique indexes and idempotent booking creation provide additional protection.

## 8. Authentication and authorization

- Users authenticate with application-managed username/password credentials. Faculty auth must not rely on institutional email login.
- Store only a strong password hash using a maintained password-hashing implementation selected during setup. Apply login throttling and generic authentication errors.
- Roles: student, faculty, CCC administrator. Enforce permissions in backend dependencies/services, never only in the UI.
- Students: read rooms and public availability only.
- Faculty: create requests and read their own request history; cannot directly confirm/cancel bookings.
- Administrators: review all requests, approve/reject, cancel bookings, inspect email failures/conflicts and audit history.
- Seed/bootstrap the first admin through a documented one-time secure process; do not ship a default password.
- Protect secrets with environment/configuration outside Git. Use TLS in deployment, least-privilege database credentials, CORS allowlists, secure cookie flags or protected token storage, and CSRF protection when cookie-based auth is used.
- Gmail `https://mail.google.com/` is a broad mailbox scope. Explain this clearly to the mailbox owner, restrict OAuth client/token access, use a dedicated mailbox where possible, protect/revoke refresh tokens, and avoid broad mailbox access for unrelated services.

## 9. Booking conflict-prevention strategy

Represent allowed predefined slots as atomic, non-overlapping units over 08:00–20:00. A requested interval must align to slot boundaries and claim every covered slot. For interval `[start, end)`, allocate slots whose ranges intersect it; with aligned boundaries this is the set from start inclusive to end exclusive. Adjacent bookings share no slot and therefore remain valid.

Within a PostgreSQL transaction: lock the request row and verify it is pending, insert booking and unique slot allocations, update request/email log, and add an audit event. A unique-constraint failure means another booking claimed a slot; roll back and return a conflict. Cancellation changes booking state and releases allocations atomically. Imported bookings follow the same service path. Pending faculty requests do not allocate slots.

Booking boundaries use 30-minute increments. The PostgreSQL slot uniqueness constraint enforces occupancy for each half-hour unit; existing confirmed intervals are also checked directly so data created under earlier hourly allocation IDs remains protected.

## 10. Security, reliability, and concurrency considerations

- Validate all request and email-derived values server-side; normalize room IDs, dates, times, and strings.
- Prevent privilege escalation by deriving actor identity from authenticated context, not request bodies.
- Apply least privilege to PostgreSQL and Google OAuth; protect, rotate, and revoke secrets.
- Do not include raw email bodies, password hashes, tokens, or sensitive error internals in UI/logs.
- Protect administrative routes and audit every decision, cancellation, and email import outcome.
- Use unique indexes for identities/deduplication/slot claims; handle duplicate key errors as expected concurrency outcomes.
- Use transactions for multi-document booking state changes where deployment supports them. Add idempotency keys or source identity to avoid duplicate creation on retries.
- Make worker retries bounded/backed off and distinguish permanent invalid/conflict results from transient failures.
- Avoid historical mailbox backfill by default; show explicit scope and progress for any approved import.
- Define retention and privacy rules for audit and email metadata before production deployment.
- Ensure availability responses include only data appropriate for public display; purpose/sender visibility needs a policy decision.

## 11. Ambiguities and decisions needed

1. **Slot length and duration rules:** Updated: start/end times align to 30-minute boundaries; a reservation may cover consecutive slots. The 08:00–20:00 range yields twenty-four slots per room per day.
2. **Campus timezone:** Resolved: `Asia/Kolkata` (IST).
3. **Booking request lead time:** Are same-day or past-date requests allowed? How far ahead can bookings be made?
4. **Email format and trust policy:** What subject/body examples define an official booking? Which sender addresses/domains are trusted? Must messages originate from CCC only, and how are forwarded messages handled?
5. **Unrecognized email policy:** Should non-booking emails be silently skipped while advancing the cursor, or recorded as ignored?
6. **Faculty account provisioning:** Who creates faculty accounts, and how are initial passwords/reset handled? Is public signup prohibited (recommended)?
7. **Student access:** Is availability public without login, or must students log in?
8. **Visibility/privacy:** May public users see purpose and requester, or only room/time/status?
9. **Email mailbox:** Is the testing mailbox the same account the worker polls? How will the designated production CCC mailbox be selected later?
10. **PostgreSQL deployment:** Resolved: Neon Free is the selected provider; configure its PostgreSQL connection URL in the local environment.
11. **Deployment target:** Where will frontend, API, worker, and database run, and how will worker uptime/secrets be managed?
12. **Cancellation semantics:** Can confirmed bookings be cancelled at any time, and should cancellations notify anyone by email?
13. **Out-of-band booking changes:** How should cancellation/amendment emails map to existing imported bookings? Initial requirements describe booking imports but not email-driven edits.

## 12. Requirement-to-module mapping

| Requirement | Planned module |
|---|---|
| Weekly six-room availability | `AvailabilityService`, rooms/availability API, frontend availability feature |
| Faculty request lifecycle | request schema, `BookingService`, faculty/admin APIs and features |
| Role-based access | auth service, API dependencies, account provisioning |
| Confirmed booking occupancy | booking service, slot allocations, availability queries |
| Email OAuth/IMAP polling | email OAuth provider, IMAP client, independent `worker.py` |
| Deterministic message parsing | MIME extraction, parser, validator modules |
| Deduplication and failures | `email_logs`, unique indexes, worker state machine, admin API |
| Auditable decisions | `audit_logs`, booking/admin services |
| Secure setup and operations | config, `.env.example`, README and deployment docs |
