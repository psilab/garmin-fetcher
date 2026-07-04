# Garmin Fetcher — backend

Python / FastAPI service that pulls your Garmin Connect activity data using the
[`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect)
library. Everything runs in Docker — nothing is installed on the host.

## Auth model

- **One-time login** (`login.py`) authenticates with your Garmin email/password,
  handles MFA if enabled, and saves tokens to the `garmin_tokens` Docker volume
  (`/tokens`).
- **The API service** only *resumes* from those saved tokens — it never touches
  your password. Tokens auto-refresh until the refresh token expires (~1 year).

## Usage

Bootstrap the token store once (interactive — prompts for password + MFA code,
or reads `GARMIN_EMAIL` / `GARMIN_PASSWORD` from `backend/.env`):

```bash
docker compose -f docker-compose.dev.yml run --rm backend python login.py
```

Then start everything:

```bash
make up
```

## Endpoints

| Method | Path                       | Description                              |
|--------|----------------------------|------------------------------------------|
| GET    | `/health`                  | Liveness check                           |
| GET    | `/api/me`                  | Profile name + unit system (auth check)  |
| GET    | `/api/activities?limit=10` | Most recent activities (newest first)    |
| GET    | `/api/activities/range`    | `?start=YYYY-MM-DD&end=YYYY-MM-DD`        |

Interactive API docs: http://localhost:8000/docs

Requests before login return `401` with a message telling you to run the
bootstrap.
