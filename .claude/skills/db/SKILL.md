---
name: db
description: Query or change the local members DB (Postgres in the my-postgres container), reseed it, or write SQL for the user to run in production. Use for "check the DB", "update joined_at", "insert these members", "reseed".
argument-hint: "[what to look up or change]"
---

**Local** (test data: reads and writes are fine, no cleanup needed):
- `docker exec my-postgres psql -U postgres -d ekklesiaio-members-management -At -c "<sql>"`
  (`-i` and a heredoc for multi-line SQL). From Python the URL host is `127.0.0.1`, never `localhost`.
- Schema questions: read the SQLAlchemy models under `src/membership_management/data/` first, not `\d`.
- Reseed: `uv run python -m membership_management.data.seed --reset` (truncates every members-DB table).
- Don't create scratch databases (`*-scratch`) or extra servers unless the user agrees.

**Assimilation** (SQL Server, read-only, the real church DB even locally): SELECT only, small result sets.

**Production** (RDS, through the SSM tunnel in `management-infra`): never run it yourself. Write the SQL
for the user, wrapped in `BEGIN; … SELECT <the rows it changes>; -- COMMIT; or ROLLBACK;`, with a
SELECT first that shows what will change. Inserts from names the user pastes (e.g. members): one
`INSERT … VALUES` per batch; say which rows you were unsure about (e.g. the sex inferred from a name).
