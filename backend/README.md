# AuraMatch Delhi — Backend

A Python Flask REST API powering the AuraMatch Delhi SPA.

## Stack
| Layer | Choice |
|---|---|
| Web framework | Flask 3 |
| ORM | Flask-SQLAlchemy 3 |
| Database | SQLite (file: `instance/auramatch.db`) |
| CORS | Flask-CORS |

## Quick start

```bash
# 1. Create & activate a virtual environment
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the dev server
python app.py
# → http://127.0.0.1:5000
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/health` | Health check |
| `GET`  | `/api/artists` | List all artists (optional `?tag=dewy` filter) |
| `GET`  | `/api/artists/<id>` | Get a single artist by ID |
| `POST` | `/api/seed` | Clear table & insert 5 Delhi artists |

### Seed the database

```bash
curl -X POST http://127.0.0.1:5000/api/seed
```

### Filter by style tag

```bash
curl "http://127.0.0.1:5000/api/artists?tag=airbrush"
```
