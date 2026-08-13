import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from db.models import App, User, get_db
import config

APP_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
PBKDF2_ITERATIONS = 200_000

def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 (stdlib) — pas de dépendance externe fragile."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"

def verify_password(plain: str, hashed: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = hashed.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", plain.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False

def create_token() -> str:
    """Token API en clair — seul le hash (hash_token) est stocké en base."""
    return secrets.token_urlsafe(32)

def hash_token(token: str) -> str:
    return f"sha256${hashlib.sha256(token.encode()).hexdigest()}"

def token_ttl() -> timedelta | None:
    days = config.TOKEN_TTL_DAYS
    return timedelta(days=days) if days and days > 0 else None

def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)

def same_origin(request: Request) -> bool:
    """Vérifie que la requête vient du même hôte (anti login-CSRF)."""
    from urllib.parse import urlparse
    host = request.headers.get("host")
    origin = request.headers.get("origin")
    if origin:
        return urlparse(origin).netloc == host
    referer = request.headers.get("referer")
    if referer:
        return urlparse(referer).netloc == host
    return False

def validate_app_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not APP_NAME_RE.match(name):
        raise HTTPException(
            400,
            "Invalid app name: use lowercase letters, digits and hyphens "
            "(must start and end with a letter/digit).",
        )
    return name

def validate_repo_url(repo_url: str) -> str:
    """Accepte https:// (remote) ou un chemin absolu local (/opt/git-repos/*.git)."""
    repo_url = (repo_url or "").strip()
    if " " in repo_url or "\n" in repo_url or "\r" in repo_url:
        raise HTTPException(400, "repo_url contains invalid characters")
    is_https = repo_url.startswith("https://")
    is_local = repo_url.startswith("/") and not repo_url.startswith("//")
    if not (is_https or is_local):
        raise HTTPException(
            400, "repo_url must be an HTTPS URL or an absolute local git path")
    return repo_url

def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: Session = Depends(get_db),
) -> User:
    """Auth par header Authorization: Bearer <token> ou cookie mh_token (UI)."""
    token = credentials.credentials if credentials else None
    if not token:
        token = request.cookies.get("mh_token")
    if not token:
        raise HTTPException(401, "Authentication required")
    user = db.query(User).filter(User.token == hash_token(token)).first()
    if not user:
        raise HTTPException(401, "Invalid or expired token")
    if user.token_expires_at is not None:
        expires = user.token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            raise HTTPException(401, "Token expired — please log in again")
    return user

def get_app_or_404(name: str, db: Session, user: User) -> App:
    app = db.query(App).filter(App.name == name).first()
    if not app:
        raise HTTPException(404, "App not found")
    if app.owner_email != user.email:
        raise HTTPException(403, "You do not own this app")
    return app