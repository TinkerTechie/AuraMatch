# AuraMatch Delhi 💄✨
### *AI-Powered Bridal Makeup Artist Matchmaker*

> Drop your bridal moodboard. Groq Llama Vision reads your aesthetic. We find your perfect Delhi artist — in under 3 seconds.

---

## 🏆 Hackathon Submission

**Problem Statement**

Booking a bridal makeup artist in Delhi is overwhelming. With thousands of artists online, brides spend weeks manually scrolling through Instagram profiles hoping their style "feels right." There is no structured, aesthetic-first way to discover the artist who truly matches your vision.

**Our Solution**

AuraMatch Delhi uses **Groq Llama Vision** to analyze a photo from your bridal moodboard and extract a precise _style fingerprint_ — 5 curated tags from a controlled aesthetic vocabulary (`dewy`, `heavy contour`, `airbrush`, `matte finish`, etc.). It then scores every artist in the database against your fingerprint and surfaces the top 3 matches ranked by compatibility percentage. What used to take days now takes seconds.

---

## 🎥 Demo

| Landing | Processing | Results |
|---------|-----------|---------|
| Drop your moodboard photo | Groq Vision analyzes in real time | Top 3 matched artists with compatibility % |

---

## ✨ Key Features

- **🤖 AI Vision Matching** — Groq Llama Vision reads your photo and maps it to a closed set of bridal style tags, preventing hallucinations and ensuring reproducible scores
- **📊 Aesthetic Match Score** — Intersection-based scoring algorithm gives each artist a precise compatibility percentage
- **🛡️ Graceful Fallback** — If Groq times out (20s limit), the system returns a sensible default and flags `"fallback": true` in the response — zero crashes
- **⚡ Single-File SPA** — Zero-framework Vanilla JS frontend with three animated states; deploys as a static file
- **🌐 Production-Ready API** — Gunicorn WSGI server, CORS configured, SQLAlchemy ORM, SQLite persistence

---

## 🏗️ Architecture

```
┌─────────────────────────────────────┐
│           index.html (SPA)          │
│  ┌──────────┐  ┌──────────────────┐ │
│  │ Landing  │→ │   Processing     │ │
│  │ Drop Zone│  │  Gold Spinner    │ │
│  └──────────┘  └────────┬─────────┘ │
│                         │           │
│               ┌─────────▼─────────┐ │
│               │   Results State   │ │
│               │  MUA Cards + Tags │ │
│               └───────────────────┘ │
└──────────────┬──────────────────────┘
               │ POST /api/match
               │ { image: base64 }
┌──────────────▼──────────────────────┐
│        Flask REST API (Python)      │
│                                     │
│  /api/match ──► Groq Llama Vision    │
│                    │                │
│               5 style tags          │
│                    │                │
│  MakeupArtist ◄─── match score calc │
│  (SQLAlchemy)      │                │
│                    ▼                │
│             Top 3 ranked JSON       │
└──────────────────────────────────────┘
               │
┌──────────────▼──────────────────────┐
│        SQLite (auramatch.db)        │
│  MakeupArtist: id, name, location,  │
│  starting_price, instagram,         │
│  portfolio_url, style_tags (JSON)   │
└──────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla JS · Bootstrap 5 CDN · Playfair Display / Inter |
| Backend | Python 3.12 · Flask 3 · Flask-CORS · Flask-SQLAlchemy |
| Database | SQLite + SQLAlchemy ORM (JSON column for style tags) |
| AI | Groq `meta-llama/llama-4-scout-17b-16e-instruct` Vision |
| Production Server | Gunicorn 26 · gthread workers |
| Deploy | Render / Heroku (Procfile included) |

---

## 🚀 Quick Start (Local)

### Prerequisites
- Python 3.12+
- A Groq API key (free at [console.groq.com](https://console.groq.com))

### 1 · Clone & set up backend

```bash
git clone https://github.com/your-username/auramatch-delhi.git
cd auramatch-delhi/backend

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2 · Configure environment

```bash
cp .env.example .env
# Edit .env and set your GROQ_API_KEY
```

### 3 · Run the API server

```bash
# Development
python app.py
# → http://127.0.0.1:5000

# Production (local test)
gunicorn "app:app" --workers 2 --threads 2 --worker-class gthread --bind 0.0.0.0:5000
```

### 4 · Seed the database

```bash
curl -X POST http://127.0.0.1:5000/api/seed
```

### 5 · Open the frontend

```bash
open ../index.html   # macOS
# or simply double-click beauty-salon/index.html
```

---

## 📡 API Reference

### `GET /api/health`
Health check. Returns `{"status": "ok"}`.

---

### `GET /api/artists`
List all makeup artists.

**Query params**
| Param | Description |
|-------|-------------|
| `tag` | Filter by style tag (e.g. `?tag=airbrush`) |

**Response**
```json
[
  {
    "id": 1,
    "name": "Priya Sharma Makeovers",
    "location": "Lajpat Nagar, South Delhi",
    "starting_price": "₹18,000",
    "instagram": "@priyasharma.makeovers",
    "portfolio_url": "https://priyasharma.in/portfolio",
    "style_tags": ["dewy", "glass skin", "soft glam", "airbrush", "natural bridal"]
  }
]
```

---

### `POST /api/seed`
Clears the database and inserts 5 curated Delhi bridal artists with realistic style tags.

---

### `POST /api/match` ⭐ *Core Feature*
Analyzes a bridal moodboard photo using Groq Llama Vision and returns the top 3 matching artists.

**Request body**
```json
{ "image": "<base64-encoded image string>" }
```

**Response**
```json
{
  "ai_tags": ["dewy", "airbrush", "natural", "gold shimmer", "hd makeup"],
  "fallback": false,
  "results": [
    {
      "id": 1,
      "name": "Priya Sharma Makeovers",
      "location": "Lajpat Nagar, South Delhi",
      "starting_price": "₹18,000",
      "instagram": "@priyasharma.makeovers",
      "portfolio_url": "https://priyasharma.in/portfolio",
      "style_tags": ["dewy", "glass skin", "soft glam", "airbrush", "natural bridal"],
      "match_score": 60.0
    }
  ]
}
```

**Match Score formula**

```
match_score = (|artist_tags ∩ ai_tags| / |ai_tags|) × 100
```

**Fallback behaviour**  
If Groq times out (20 s) or returns malformed JSON, the response is returned with `"fallback": true` and a default tag set — the endpoint never crashes.

---

## ☁️ Deploy to Render

1. Push the `backend/` folder to a GitHub repo (Render can point to a subdirectory).
2. Create a new **Web Service** on [render.com](https://render.com).
3. Set **Root Directory** → `backend`
4. Set **Build Command** → `pip install -r requirements.txt`
5. Set **Start Command** → *(auto-detected from `Procfile`)*
6. Add **Environment Variable**: `GROQ_API_KEY` = `gsk_...`
7. *(Optional)* Add a **Disk** at `/mnt/data` and set `DATABASE_URL=sqlite:////mnt/data/auramatch.db` so your SQLite DB survives deploys.

## ☁️ Deploy to Heroku

```bash
cd backend
heroku create auramatch-delhi
heroku config:set GROQ_API_KEY=gsk_...
git push heroku main
heroku run "curl -X POST https://auramatch-delhi.herokuapp.com/api/seed"
```

---

## 📁 Project Structure

```
beauty-salon/
├── index.html                  # Single-file SPA (Vanilla JS + Bootstrap 5)
└── backend/
    ├── app.py                  # Flask app — models, routes, AI logic
    ├── requirements.txt        # All Python deps, fully pinned
    ├── Procfile                # Gunicorn production command
    ├── .env.example            # Environment variable template
    ├── README.md               # This file
    └── instance/
        └── auramatch.db        # SQLite database (auto-created)
```

---

## 🧠 How the AI Matching Works

```
User uploads photo
        │
        ▼
FileReader → base64 string
        │
        ▼ POST /api/match
Flask receives base64 image
        │
        ▼
Groq Llama Vision (meta-llama/llama-4-scout-17b-16e-instruct, max_tokens: 120)
  System prompt enforces:
  - Exactly 5 tags
  - Closed vocabulary of 15 terms
  - Raw JSON output only
        │
        ▼
Response sanitised + validated
  (markdown fences stripped, hallucinations removed)
        │
        ▼
For each MakeupArtist in DB:
  score = |artist_tags ∩ ai_tags| / |ai_tags| × 100
        │
        ▼
Sorted desc → top 3 returned with match_score field
```

---

## 🤝 Team

Built for **[Hackathon Name]** · Delhi, 2026

---

## 📄 License

MIT — free to use, fork, and build upon.
