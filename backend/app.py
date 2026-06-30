"""
AuraMatch Delhi — Flask Backend
================================
Serves makeup artist data from an SQLite database via a REST API.
"""

import json
import os
import re
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy import text
from groq import Groq
from groq import APITimeoutError, APIError

# ---------------------------------------------------------------------------
# App & DB setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Allow all origins so the frontend SPA can freely communicate during dev.
# Tighten this in production by specifying origins=["http://localhost:5173"].
CORS(app, resources={r"/api/*": {"origins": "*"}})

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///auramatch.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class MakeupArtist(db.Model):
    """Represents a bridal makeup artist listed on AuraMatch Delhi."""

    __tablename__ = "makeup_artists"

    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(120), nullable=False)
    location       = db.Column(db.String(120), nullable=False)
    starting_price = db.Column(db.String(60),  nullable=False)
    instagram      = db.Column(db.String(120), nullable=False)
    portfolio_url  = db.Column(db.String(255), nullable=False)
    phone          = db.Column(db.String(20),  nullable=False, default="")
    # SQLite doesn't have a native JSON column, but SQLAlchemy's JSON type
    # transparently serialises/deserialises Python lists for us.
    style_tags     = db.Column(db.JSON, nullable=False, default=list)

    def to_dict(self):
        return {
            "id":             self.id,
            "name":           self.name,
            "location":       self.location,
            "starting_price": self.starting_price,
            "instagram":      self.instagram,
            "portfolio_url":  self.portfolio_url,
            "phone":          self.phone,
            "style_tags":     self.style_tags,
        }


# ---------------------------------------------------------------------------
# Booking model
# ---------------------------------------------------------------------------

class Booking(db.Model):
    """A consultation request submitted through the AuraMatch app."""

    __tablename__ = "bookings"

    id             = db.Column(db.Integer, primary_key=True)
    artist_id      = db.Column(db.Integer, db.ForeignKey("makeup_artists.id"), nullable=False)
    client_name    = db.Column(db.String(120), nullable=False)
    client_phone   = db.Column(db.String(20),  nullable=False)
    preferred_date = db.Column(db.String(30),  nullable=False)
    message        = db.Column(db.Text, nullable=True, default="")
    created_at     = db.Column(db.String(30),  nullable=False)

    artist = db.relationship("MakeupArtist", backref="bookings")

    def to_dict(self):
        return {
            "id":             self.id,
            "artist_id":      self.artist_id,
            "artist_name":    self.artist.name if self.artist else "",
            "client_name":    self.client_name,
            "client_phone":   self.client_phone,
            "preferred_date": self.preferred_date,
            "message":        self.message,
            "created_at":     self.created_at,
        }


# ---------------------------------------------------------------------------
# Seed data — 5 highly specific Delhi bridal makeup artists
# ---------------------------------------------------------------------------

SEED_ARTISTS = [
    {
        "name":           "Priya Sharma Makeovers",
        "location":       "Lajpat Nagar, South Delhi",
        "starting_price": "₹18,000",
        "instagram":      "@priyasharma.makeovers",
        "portfolio_url":  "https://priyasharma.in/portfolio",
        "phone":          "+91 98111 23456",
        "style_tags":     ["dewy", "glass skin", "soft glam", "airbrush", "natural bridal"],
    },
    {
        "name":           "Radiance by Meher Arora",
        "location":       "Punjabi Bagh, West Delhi",
        "starting_price": "₹25,000",
        "instagram":      "@radiance.by.meher",
        "portfolio_url":  "https://mehararora.com/bridal",
        "phone":          "+91 98765 43210",
        "style_tags":     ["heavy contour", "matte finish", "high drama", "bold eyes", "traditional"],
    },
    {
        "name":           "Divya Kapila Beauty Studio",
        "location":       "Vasant Kunj, South-West Delhi",
        "starting_price": "₹15,500",
        "instagram":      "@divyakapila.beauty",
        "portfolio_url":  "https://divyakapilabeauty.com",
        "phone":          "+91 97113 55678",
        "style_tags":     ["airbrush", "dewy", "pink tones", "no-crease", "minimalist bridal"],
    },
    {
        "name":           "Ananya Goel Artistry",
        "location":       "Rohini, North-West Delhi",
        "starting_price": "₹12,000",
        "instagram":      "@ananya.goel.artistry",
        "portfolio_url":  "https://ananyagoelartistry.in",
        "phone":          "+91 99101 87654",
        "style_tags":     ["matte finish", "cut crease", "heavy contour", "bold lip", "editorial"],
    },
    {
        "name":           "Noor Bridal by Sana Khan",
        "location":       "Chandni Chowk, Old Delhi",
        "starting_price": "₹20,000",
        "instagram":      "@noor.bridal.sana",
        "portfolio_url":  "https://noorbridal.com/gallery",
        "phone":          "+91 98211 34567",
        "style_tags":     ["traditional", "smoky eye", "airbrush", "jewel tones", "heavy contour", "matte finish"],
    },
]


# ---------------------------------------------------------------------------
# Groq client (key read from GROQ_API_KEY env var)
# ---------------------------------------------------------------------------

# Initialised lazily so the server still starts without a key during dev.
_groq_client: Groq | None = None

def get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is not set.")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


# ---------------------------------------------------------------------------
# Vision helpers
# ---------------------------------------------------------------------------

# The closed dictionary the AI must pick from.
VALID_TAGS: list[str] = [
    "dewy", "pastel", "minimalist eye", "nude lip", "hd makeup",
    "bold glam", "smokey eye", "matte finish", "red lip", "airbrush",
    "traditional", "heavy contour", "gold shimmer", "natural", "winged liner",
]

VISION_SYSTEM_PROMPT = (
    "Analyze this bridal makeup photo. Return strictly valid JSON containing a "
    "single array named 'tags' with exactly 5 items. The array items must be "
    "lowercase strings selected exclusively from this dictionary: "
    "[dewy, pastel, minimalist eye, nude lip, hd makeup, bold glam, smokey eye, "
    "matte finish, red lip, airbrush, traditional, heavy contour, gold shimmer, "
    "natural, winged liner]. Output raw JSON only."
)

# Fallback tags returned when Groq is unreachable or times out.
FALLBACK_TAGS: list[str] = ["traditional", "heavy contour", "matte finish", "airbrush", "dewy"]


def _extract_tags_from_image(base64_image: str) -> list[str]:
    """
    Send the base64 image to Groq Vision and parse the returned JSON.
    Returns a list of exactly 5 tag strings.
    Raises RuntimeError if the response cannot be parsed.
    """
    client = get_groq_client()

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        timeout=20,          # seconds — triggers APITimeoutError on breach
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "low",   # cheaper & faster for tag extraction
                        },
                    }
                ],
            },
        ],
        max_tokens=120,
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if the model wraps output in ```json ... ```
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\n?```$", "", raw)

    parsed = json.loads(raw)
    tags: list[str] = parsed.get("tags", [])

    if not isinstance(tags, list) or len(tags) != 5:
        raise RuntimeError(f"Unexpected tags shape from Groq: {tags}")

    # Normalise and guard against hallucinated values
    sanitised = [
        t.lower().strip() for t in tags
        if isinstance(t, str) and t.lower().strip() in VALID_TAGS
    ]
    # Pad with fallback tags if some were invalid
    for fb in FALLBACK_TAGS:
        if len(sanitised) >= 5:
            break
        if fb not in sanitised:
            sanitised.append(fb)

    return sanitised[:5]


def _calculate_match_score(artist_tags: list[str], ai_tags: list[str]) -> float:
    """
    Returns a match percentage (0.0–100.0) based on the Jaccard-style
    intersection of the AI-detected tags against the artist's style tags.

    Formula: (# common tags / # AI tags) * 100
    Using AI-tag count as the denominator so the score reflects how well
    the artist covers what the photo analysis found.
    """
    if not ai_tags:
        return 0.0
    artist_set = {t.lower().strip() for t in (artist_tags or [])}
    ai_set     = {t.lower().strip() for t in ai_tags}
    common     = artist_set & ai_set
    return round(len(common) / len(ai_set) * 100, 1)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/artists", methods=["GET"])
def get_artists():
    """Return all makeup artists, with optional ?tag= filter."""
    tag = request.args.get("tag", "").strip().lower()

    if tag:
        # Filter in Python — keeps the query simple and DB-agnostic
        artists = [
            a for a in MakeupArtist.query.all()
            if any(tag in t.lower() for t in (a.style_tags or []))
        ]
    else:
        artists = MakeupArtist.query.all()

    return jsonify([a.to_dict() for a in artists])


@app.route("/api/artists/<int:artist_id>", methods=["GET"])
def get_artist(artist_id):
    """Return a single makeup artist by ID."""
    artist = MakeupArtist.query.get_or_404(artist_id)
    return jsonify(artist.to_dict())


@app.route("/api/seed", methods=["POST"])
def seed():
    """
    Clear the makeup_artists table and re-populate it with curated Delhi
    bridal makeup artists.  Hit this once to get the app into a known state.
    """
    # Drop all rows without dropping the table schema
    db.session.query(MakeupArtist).delete()
    db.session.commit()

    inserted = []
    for data in SEED_ARTISTS:
        artist = MakeupArtist(**data)
        db.session.add(artist)
        inserted.append(data["name"])

    db.session.commit()

    return jsonify({
        "message": "Database seeded successfully.",
        "artists_added": len(inserted),
        "names": inserted,
    }), 201


@app.route("/api/match", methods=["POST"])
def match():
    """
    Accept a base64-encoded image, run it through Groq Vision to extract
    5 style tags, then return the top-3 best-matching artists sorted by
    match score (highest first).

    Request body (JSON):
        { "image": "<base64 string>" }

    Response (JSON):
        {
            "ai_tags": ["dewy", ...],
            "fallback": false,
            "results": [
                {
                    ...artist fields...,
                    "match_score": 60.0
                },
                ...
            ]
        }
    """
    body = request.get_json(silent=True) or {}
    base64_image: str = body.get("image", "").strip()

    if not base64_image:
        return jsonify({"error": "'image' field (base64 string) is required."}), 400

    used_fallback = False
    ai_tags: list[str] = []

    try:
        ai_tags = _extract_tags_from_image(base64_image)

    except APITimeoutError:
        # Groq took longer than 20 s — use deterministic fallback
        app.logger.warning("Groq request timed out — using fallback tags.")
        ai_tags = FALLBACK_TAGS[:]
        used_fallback = True

    except (APIError, RuntimeError, json.JSONDecodeError, KeyError) as exc:
        # Any other Groq / parse error — log it and fall back gracefully
        app.logger.error("Groq error: %s", exc)
        ai_tags = FALLBACK_TAGS[:]
        used_fallback = True

    # ---- Score every artist ------------------------------------------------
    all_artists = MakeupArtist.query.all()

    scored = [
        {
            **artist.to_dict(),
            "match_score": _calculate_match_score(artist.style_tags, ai_tags),
        }
        for artist in all_artists
    ]

    # Sort descending by match score, take top 3
    top3 = sorted(scored, key=lambda a: a["match_score"], reverse=True)[:3]

    return jsonify({
        "ai_tags":  ai_tags,
        "fallback": used_fallback,
        "results":  top3,
    })


@app.route("/api/book", methods=["POST"])
def book():
    """
    Submit a consultation booking request.

    Request body (JSON):
        {
            "artist_id":      1,
            "client_name":    "Riya Kapoor",
            "client_phone":   "+91 99999 00000",
            "preferred_date": "2026-11-15",
            "message":        "Looking for a dewy bridal look"
        }
    """
    from datetime import datetime, timezone

    body = request.get_json(silent=True) or {}

    artist_id      = body.get("artist_id")
    client_name    = (body.get("client_name") or "").strip()
    client_phone   = (body.get("client_phone") or "").strip()
    preferred_date = (body.get("preferred_date") or "").strip()
    message        = (body.get("message") or "").strip()

    errors = []
    if not artist_id:
        errors.append("'artist_id' is required.")
    if not client_name:
        errors.append("'client_name' is required.")
    if not client_phone:
        errors.append("'client_phone' is required.")
    if not preferred_date:
        errors.append("'preferred_date' is required.")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    artist = MakeupArtist.query.get(artist_id)
    if not artist:
        return jsonify({"error": f"Artist with id={artist_id} not found."}), 404

    booking = Booking(
        artist_id      = artist_id,
        client_name    = client_name,
        client_phone   = client_phone,
        preferred_date = preferred_date,
        message        = message,
        created_at     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.session.add(booking)
    db.session.commit()

    return jsonify({
        "message": f"Consultation booked with {artist.name}!",
        "booking": booking.to_dict(),
    }), 201


@app.route("/api/bookings", methods=["GET"])
def list_bookings():
    """Return all bookings (admin view)."""
    bookings = Booking.query.order_by(Booking.id.desc()).all()
    return jsonify([b.to_dict() for b in bookings])


@app.route("/api/health", methods=["GET"])
def health():
    """Simple health-check endpoint."""
    return jsonify({"status": "ok", "app": "AuraMatch Delhi"})



# ---------------------------------------------------------------------------
# Initialise DB tables and run
# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()
    # Auto-seed if the database is empty (e.g. after a Render spin-down or rebuild)
    try:
        if not MakeupArtist.query.first():
            app.logger.info("Database is empty. Auto-seeding 5 bridal artists...")
            for data in SEED_ARTISTS:
                db.session.add(MakeupArtist(**data))
            db.session.commit()
            app.logger.info("Auto-seeding complete.")
    except Exception as e:
        app.logger.error("Failed to auto-seed database: %s", e)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
