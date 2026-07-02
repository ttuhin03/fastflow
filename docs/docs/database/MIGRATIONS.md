# Database Migrations

This document explains how to run database migrations in Fast-Flow manually.

## Overview

Fast-Flow uses [Alembic](https://alembic.sqlalchemy.org/) for database migrations. Migrations are **not** run automatically on container start; they must be executed manually.

## Running migrations

### In the Docker container

When the application runs in a Docker container:

```bash
# Run migrations
docker compose exec fastflow-orchestrator alembic upgrade head

# Or if the container has a different name:
docker exec <container-name> alembic upgrade head
```

### Locally (without Docker)

When the application runs locally:

```bash
# In the project directory
cd /path/to/fastflow

# Run migrations
alembic upgrade head
```

## Checking migration status

To see which migrations have already been applied:

```bash
# In container
docker compose exec fastflow-orchestrator alembic current

# Or locally
alembic current
```

To see all available migrations:

```bash
# In container
docker compose exec fastflow-orchestrator alembic history

# Or locally
alembic history
```

## Creating a new migration

When the database schema has changed (e.g. new fields in a model), a new migration must be created:

```bash
# In container
docker compose exec fastflow-orchestrator alembic revision --autogenerate -m "Description of change"

# Or locally
alembic revision --autogenerate -m "Description of change"
```

The new migration is created in `alembic/versions/` and should be reviewed before running.

## Rolling back a migration

To undo the last migration:

```bash
# In container
docker compose exec fastflow-orchestrator alembic downgrade -1

# Or locally
alembic downgrade -1
```

To return to a specific revision:

```bash
# In container
docker compose exec fastflow-orchestrator alembic downgrade <revision-id>

# Or locally
alembic downgrade <revision-id>
```

## Available migrations

### 001_add_is_parameter_to_secret
Adds the `is_parameter` field to the `secrets` table.

### 002_add_webhook_fields
Adds `webhook_runs` to the `pipelines` table and `triggered_by` to the `pipeline_runs` table.

### 003_add_user_management_fields
Adds user management fields to the `users` table:
- `email` (optional)
- `role` (READONLY, WRITE, ADMIN)
- `blocked` (boolean)
- `invitation_token`, `invitation_expires_at` (optional; removed again in **006**)
- `microsoft_id` (optional)

### 004_github_invitation
GitHub OAuth + token invitation:
- New table `invitations` (recipient_email, token, is_used, expires_at, role, created_at)
- New column `users.github_id` (optional, unique, for GitHub login)

### 005_make_password_hash_nullable
- `users.password_hash` was briefly nullable (precursor to 007).

### 006_drop_user_invitation_columns
- Removes `users.invitation_token` and `users.invitation_expires_at` (invitations only via `invitations` table).

### 007_drop_password_hash
- Removes `users.password_hash` (login only via GitHub OAuth).

### 008_add_google_avatar
- `users.google_id` (optional, unique) for Google OAuth.
- `users.avatar_url` (optional) for profile image from OAuth providers.

### 009_add_user_status
- `users.status` (String, default `active`) for join requests: `active` (full access), `pending` (awaiting approval), `rejected` (declined, usually with `blocked=true`). Unknown OAuth users receive `pending` and appear under Users → Join requests; after approval `active` is set.

## Important notes

1. **Create a backup**: Before running migrations, create a database backup, especially in production environments.

2. **Review migrations**: New migrations should always be reviewed before execution.

3. **SQLite specifics**: SQLite does not support some ALTER TABLE operations directly. Alembic uses `batch_alter_table` for SQLite, which may copy a table. For large tables this can take time.

4. **Production environments**: In production, migrations should be run during a maintenance window.

## Troubleshooting

### Migration hangs
If a migration hangs, it may help to:
- Check whether the database is locked
- Restart the container
- Review the migration manually

### Migration fails
If a migration fails:
1. Check the error message
2. Check current status: `alembic current`
3. If needed, roll back: `alembic downgrade -1`
4. Fix the migration and run again

### Correcting enum values
If enum values in the database do not match the code (e.g. 'readonly' instead of 'READONLY'), they are corrected automatically on read (`app/auth.py`, `get_current_user`).

## Example workflow

```bash
# 1. Check status
docker compose exec fastflow-orchestrator alembic current

# 2. Run migrations
docker compose exec fastflow-orchestrator alembic upgrade head

# 3. Check status again
docker compose exec fastflow-orchestrator alembic current
```

## Further information

- [Alembic documentation](https://alembic.sqlalchemy.org/)
- [SQLModel documentation](https://sqlmodel.tiangolo.com/)
