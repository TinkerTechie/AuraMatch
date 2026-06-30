"""
AuraMatch Delhi — Flask Backend
================================
Serves makeup artist data from an SQLite database via a REST API.
Includes JWT-based auth with two roles: 'customer' and 'owner'.
"""

import json
import os
import re
import hmac
import hashlib
import base64 as _b64
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from groq import Groq
from groq import APITimeoutError, APIError

# ---------------------------------------------------------------------------
# App & DB setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

CORS(app, resources={r"/api/*": {"origins": "*"}})

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///auramatch.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Secret used to sign tokens — override in production via env var
JWT_SECRET = os.environ.get("JWT_SECRET", "auramatch-dev-secret-change-in-prod")

db = SQLAlchemy(app)


# ---------------------------------------------------------------------------
# Minimal JWT helpers (no extra library needed)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return _b64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return _b64.urlsafe_b64decode(s + "=" * (padding % 4))


def create_token(payload: dict, expires_in_hours: int = 72) -> str:
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = dict(payload)
    payload["exp"] = (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).timestamp()
    body = _b64url_encode(json.dumps(payload).encode())
    sig_input = f"{header}.{body}".encode()
    sig = _b64url_encode(hmac.new(JWT_SECRET.encode(), sig_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def verify_token(token: str) -> dict | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, body, sig = parts
        sig_input = f"{header}.{body}".encode()
        expected_sig = _b64url_encode(hmac.new(JWT_SECRET.encode(), sig_input, hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(_b64url_decode(body))
        if payload.get("exp", 0) < datetime.now(timezone.utc).timestamp():
            return None
        return payload
    except Exception:
        return None


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return _b64.b64encode(salt + dk).decode()


def _check_password(password: str, stored: str) -> bool:
    raw = _b64.b64decode(stored.encode())
    salt, dk = raw[:16], raw[16:]
    return hmac.compare_digest(
        dk,
        hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    )


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def login_required(roles=None):
    """Decorator that verifies JWT and optionally restricts to certain roles."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return jsonify({"error": "Authentication required."}), 401
            token = auth.split(" ", 1)[1]
            payload = verify_token(token)
            if payload is None:
                return jsonify({"error": "Invalid or expired token."}), 401
            if roles and payload.get("role") not in roles:
                return jsonify({"error": "You do not have permission for this action."}), 403
            request.current_user = payload
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(db.Model):
    """Application user — either a customer or a salon owner."""
    __tablename__ = "users"

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), nullable=False)
    email        = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role         = db.Column(db.String(20),  nullable=False, default="customer")  # "customer" | "owner"
    created_at   = db.Column(db.String(30),  nullable=False)

    def to_dict(self):
        return {
            "id":         self.id,
            "name":       self.name,
            "email":      self.email,
            "role":       self.role,
            "created_at": self.created_at,
        }


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
    style_tags     = db.Column(db.JSON, nullable=False, default=list)
    # owner link (optional — NULL for seeded artists)
    owner_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

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
            "owner_id":       self.owner_id,
        }


class Booking(db.Model):
    """A consultation request submitted through the AuraMatch app."""
    __tablename__ = "bookings"

    id             = db.Column(db.Integer, primary_key=True)
    artist_id      = db.Column(db.Integer, db.ForeignKey("makeup_artists.id"), nullable=False)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)   # NULL for anon/legacy
    client_name    = db.Column(db.String(120), nullable=False)
    client_phone   = db.Column(db.String(20),  nullable=False)
    preferred_date = db.Column(db.String(30),  nullable=False)
    message        = db.Column(db.Text, nullable=True, default="")
    created_at     = db.Column(db.String(30),  nullable=False)

    artist = db.relationship("MakeupArtist", backref="bookings")
    user   = db.relationship("User", backref="bookings")

    def to_dict(self):
        return {
            "id":             self.id,
            "artist_id":      self.artist_id,
            "artist_name":    self.artist.name if self.artist else "",
            "artist_phone":   self.artist.phone if self.artist else "",
            "user_id":        self.user_id,
            "client_name":    self.client_name,
            "client_phone":   self.client_phone,
            "preferred_date": self.preferred_date,
            "message":        self.message,
            "created_at":     self.created_at,
        }


# ---------------------------------------------------------------------------
# Seed data
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
# Groq client
# ---------------------------------------------------------------------------

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

FALLBACK_TAGS: list[str] = ["traditional", "heavy contour", "matte finish", "airbrush", "dewy"]


def _extract_tags_from_image(base64_image: str) -> list[str]:
    client = get_groq_client()
    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        timeout=20,
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "low",
                        },
                    }
                ],
            },
        ],
        max_tokens=120,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\n?```$", "", raw)
    parsed = json.loads(raw)
    tags: list[str] = parsed.get("tags", [])
    if not isinstance(tags, list) or len(tags) != 5:
        raise RuntimeError(f"Unexpected tags shape from Groq: {tags}")
    sanitised = [
        t.lower().strip() for t in tags
        if isinstance(t, str) and t.lower().strip() in VALID_TAGS
    ]
    for fb in FALLBACK_TAGS:
        if len(sanitised) >= 5:
            break
        if fb not in sanitised:
            sanitised.append(fb)
    return sanitised[:5]


def _calculate_match_score(artist_tags: list[str], ai_tags: list[str]) -> float:
    if not ai_tags:
        return 0.0
    artist_set = {t.lower().strip() for t in (artist_tags or [])}
    ai_set     = {t.lower().strip() for t in ai_tags}
    common     = artist_set & ai_set
    return round(len(common) / len(ai_set) * 100, 1)


# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------

@app.route("/api/register", methods=["POST"])
def register():
    """Register a new user (customer or owner)."""
    body  = request.get_json(silent=True) or {}
    name  = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()
    role  = (body.get("role") or "customer").strip().lower()

    errors = []
    if not name:       errors.append("Name is required.")
    if not email:      errors.append("Email is required.")
    if not password or len(password) < 6:
        errors.append("Password must be at least 6 characters.")
    if role not in ("customer", "owner"):
        errors.append("Role must be 'customer' or 'owner'.")
    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists."}), 409

    user = User(
        name=name,
        email=email,
        password_hash=_hash_password(password),
        role=role,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.session.add(user)
    db.session.commit()

    token = create_token({"sub": user.id, "email": user.email, "role": user.role, "name": user.name})
    return jsonify({"token": token, "user": user.to_dict()}), 201


@app.route("/api/login", methods=["POST"])
def login():
    """Login and return a JWT."""
    body  = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not _check_password(password, user.password_hash):
        return jsonify({"error": "Invalid email or password."}), 401

    token = create_token({"sub": user.id, "email": user.email, "role": user.role, "name": user.name})
    return jsonify({"token": token, "user": user.to_dict()})


@app.route("/api/me", methods=["GET"])
@login_required()
def me():
    """Return current user info from token."""
    uid  = request.current_user["sub"]
    user = User.query.get(uid)
    if not user:
        return jsonify({"error": "User not found."}), 404
    return jsonify(user.to_dict())


# ---------------------------------------------------------------------------
# Artist Routes
# ---------------------------------------------------------------------------

@app.route("/api/artists", methods=["GET"])
def get_artists():
    """Return all makeup artists, with optional ?tag= filter."""
    tag = request.args.get("tag", "").strip().lower()
    if tag:
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


@app.route("/api/artists", methods=["POST"])
@login_required(roles=["owner"])
def create_artist():
    """
    Owner-only: create a new artist/salon listing.

    Request body (JSON):
        {
            "name":           "My Salon",
            "location":       "Connaught Place, Delhi",
            "starting_price": "₹10,000",
            "instagram":      "@mysalon",
            "portfolio_url":  "https://mysalon.com",
            "phone":          "+91 99999 00000",
            "style_tags":     ["dewy","airbrush"]
        }
    """
    body = request.get_json(silent=True) or {}

    name           = (body.get("name") or "").strip()
    location       = (body.get("location") or "").strip()
    starting_price = (body.get("starting_price") or "").strip()
    instagram      = (body.get("instagram") or "").strip()
    portfolio_url  = (body.get("portfolio_url") or "https://auramatch.in").strip()
    phone          = (body.get("phone") or "").strip()
    style_tags     = body.get("style_tags") or []

    errors = []
    if not name:           errors.append("'name' is required.")
    if not location:       errors.append("'location' is required.")
    if not starting_price: errors.append("'starting_price' is required.")
    if not instagram:      errors.append("'instagram' is required.")
    if not phone:          errors.append("'phone' is required.")
    if not isinstance(style_tags, list) or len(style_tags) == 0:
        errors.append("'style_tags' must be a non-empty array.")
    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    owner_id = request.current_user["sub"]
    artist = MakeupArtist(
        name=name,
        location=location,
        starting_price=starting_price,
        instagram=instagram,
        portfolio_url=portfolio_url,
        phone=phone,
        style_tags=[t.lower().strip() for t in style_tags if isinstance(t, str)],
        owner_id=owner_id,
    )
    db.session.add(artist)
    db.session.commit()
    return jsonify({"message": "Listing created!", "artist": artist.to_dict()}), 201


@app.route("/api/my-listings", methods=["GET"])
@login_required(roles=["owner"])
def my_listings():
    """Owner-only: list all artists created by the logged-in owner."""
    owner_id = request.current_user["sub"]
    artists = MakeupArtist.query.filter_by(owner_id=owner_id).all()
    return jsonify([a.to_dict() for a in artists])


@app.route("/api/artists/<int:artist_id>", methods=["DELETE"])
@login_required(roles=["owner"])
def delete_artist(artist_id):
    """Owner-only: delete your own listing."""
    owner_id = request.current_user["sub"]
    artist = MakeupArtist.query.get_or_404(artist_id)
    if artist.owner_id != owner_id:
        return jsonify({"error": "You can only delete your own listings."}), 403
    db.session.delete(artist)
    db.session.commit()
    return jsonify({"message": f"Listing '{artist.name}' deleted."})


# ---------------------------------------------------------------------------
# Seed Route
# ---------------------------------------------------------------------------

@app.route("/api/seed", methods=["POST"])
def seed():
    """Re-populate with curated Delhi artists."""
    db.session.query(MakeupArtist).filter_by(owner_id=None).delete()
    db.session.commit()
    inserted = []
    for data in SEED_ARTISTS:
        artist = MakeupArtist(**data)
        db.session.add(artist)
        inserted.append(data["name"])
    db.session.commit()
    return jsonify({"message": "Database seeded successfully.", "artists_added": len(inserted), "names": inserted}), 201


# ---------------------------------------------------------------------------
# Match Route
# ---------------------------------------------------------------------------

@app.route("/api/match", methods=["POST"])
def match():
    """AI image → top-3 artist matches."""
    body = request.get_json(silent=True) or {}
    base64_image: str = body.get("image", "").strip()
    if not base64_image:
        return jsonify({"error": "'image' field (base64 string) is required."}), 400

    used_fallback = False
    ai_tags: list[str] = []

    try:
        ai_tags = _extract_tags_from_image(base64_image)
    except APITimeoutError:
        app.logger.warning("Groq request timed out — using fallback tags.")
        ai_tags = FALLBACK_TAGS[:]
        used_fallback = True
    except (APIError, RuntimeError, json.JSONDecodeError, KeyError) as exc:
        app.logger.error("Groq error: %s", exc)
        ai_tags = FALLBACK_TAGS[:]
        used_fallback = True

    all_artists = MakeupArtist.query.all()
    scored = [
        {**artist.to_dict(), "match_score": _calculate_match_score(artist.style_tags, ai_tags)}
        for artist in all_artists
    ]
    top3 = sorted(scored, key=lambda a: a["match_score"], reverse=True)[:3]
    return jsonify({"ai_tags": ai_tags, "fallback": used_fallback, "results": top3})


# ---------------------------------------------------------------------------
# Booking Routes
# ---------------------------------------------------------------------------

@app.route("/api/book", methods=["POST"])
def book():
    """
    Submit a consultation booking.
    If a valid JWT is present, links the booking to the logged-in customer.
    """
    body = request.get_json(silent=True) or {}

    artist_id      = body.get("artist_id")
    client_name    = (body.get("client_name") or "").strip()
    client_phone   = (body.get("client_phone") or "").strip()
    preferred_date = (body.get("preferred_date") or "").strip()
    message        = (body.get("message") or "").strip()

    errors = []
    if not artist_id:      errors.append("'artist_id' is required.")
    if not client_name:    errors.append("'client_name' is required.")
    if not client_phone:   errors.append("'client_phone' is required.")
    if not preferred_date: errors.append("'preferred_date' is required.")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    artist = MakeupArtist.query.get(artist_id)
    if not artist:
        return jsonify({"error": f"Artist with id={artist_id} not found."}), 404

    # Optionally link to user if they're logged in
    user_id = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        payload = verify_token(auth.split(" ", 1)[1])
        if payload:
            user_id = payload.get("sub")

    booking = Booking(
        artist_id=artist_id,
        user_id=user_id,
        client_name=client_name,
        client_phone=client_phone,
        preferred_date=preferred_date,
        message=message,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.session.add(booking)
    db.session.commit()
    return jsonify({"message": f"Consultation booked with {artist.name}!", "booking": booking.to_dict()}), 201


@app.route("/api/bookings", methods=["GET"])
def list_bookings():
    """Return all bookings (admin view)."""
    bookings = Booking.query.order_by(Booking.id.desc()).all()
    return jsonify([b.to_dict() for b in bookings])


@app.route("/api/my-bookings", methods=["GET"])
@login_required(roles=["customer"])
def my_bookings():
    """Customer-only: return all bookings made by the logged-in user."""
    user_id = request.current_user["sub"]
    bookings = Booking.query.filter_by(user_id=user_id).order_by(Booking.id.desc()).all()
    return jsonify([b.to_dict() for b in bookings])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    """Simple health-check endpoint."""
    return jsonify({"status": "ok", "app": "AuraMatch Delhi"})


# ---------------------------------------------------------------------------
# Initialise DB tables and run
# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()
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
