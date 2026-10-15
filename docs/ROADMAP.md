# Roadmap (near-term)

This is lightweight scaffolding, not the full detailed implementation plan (that comes later). See `docs/ARCHITECTURE.md` for the target end-state this is working toward.

## Next steps
1. FastAPI endpoints on top of the existing `data/assimilation` module: `GET /applications/recents` is implemented (reuses the CLI's service layer). `POST /applications/approve` and `/applications/reject` exist but are placeholders — they don't persist status changes or publish the future membership-approval event yet.
2. **Open decision, revisit:** routes currently call `services.py` functions directly (no repository abstraction). This works fine so far; revisit only if the service layer stops being a sufficient seam between FastAPI and SQLAlchemy. Weigh against how much this is a learning exercise vs. a small app that doesn't need the extra layer.
3. Basic automated deploy on push (GitHub Actions).
4. Role gating and leader scoping (Phase 9, specified in `docs/specs/small-group-leader-access.md` in the workspace repo). **Small group routes are done** (`api/access.py`: role sets, `SmallGroupScopeDep`, rule 9 checks; `GET /me` `leads` follows the same scope). **Small group report routes are done too** (`small-group-reports` spec: roster, create/edit/delete, list with not-filed meetings, summary; they reuse `SmallGroupScopeDep`). Still open: role checks on the members, people and applications routes.

## Database access

The assimilation data layer intentionally uses synchronous SQLAlchemy and `pyodbc`. Routes that
perform its blocking database work must be regular `def` handlers, so FastAPI runs them in its
worker threadpool rather than blocking the event loop. Do not migrate to SQLAlchemy asyncio until
measured database latency and concurrent request volume exhaust the worker pool, or an endpoint
needs to overlap database I/O with other remote I/O. That migration would require an async SQL
Server driver, async engine and session factories, and awaitable query helpers, services, API
callers, and CLI session handling.

## Not started / later
- Docker/Kubernetes/Terraform deployment.
- Caching, logging, email/WhatsApp notifications.
