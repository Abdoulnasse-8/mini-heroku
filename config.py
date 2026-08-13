"""Configuration centralisée — toutes les constantes réglables par env vars."""
import os


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Domaine racine des apps (<name>.BASE_DOMAIN) + domaine des custom domains
BASE_DOMAIN = _env("MINIHEROKU_BASE_DOMAIN", "68.221.16.224.sslip.io")

# Environnement : "development" (docs actives) ou "production" (docs désactivées)
ENVIRONMENT = _env("MINIHEROKU_ENV", "development")
IS_PRODUCTION = ENVIRONMENT.lower() == "production"

# Caddyfile
CADDYFILE = _env("MINIHEROKU_CADDYFILE", "/etc/caddy/Caddyfile")

# Clé Fernet — stockée HORS du repo
FERNET_KEY_FILE = _env(
    "MINIHEROKU_FERNET_KEY_FILE",
    os.path.join(os.path.expanduser("~"), ".mini-heroku", "fernet.key"),
)

# Base de données
DATABASE_URL = _env(
    "MINIHEROKU_DB", f"sqlite:///{os.path.join(BASE_DIR, 'mini-heroku.db')}"
)

# Port interne écouté par les apps dans leurs containers
CONTAINER_PORT = int(_env("MINIHEROKU_CONTAINER_PORT", "8000"))

# Hôte d'exposition des containers d'apps (127.0.0.1 = uniquement via le reverse proxy)
APP_BIND_HOST = _env("MINIHEROKU_APP_BIND", "127.0.0.1")

# API (uvicorn) — adresse de bind documentée pour le systemd unit
API_HOST = _env("MINIHEROKU_API_HOST", "127.0.0.1")
API_PORT = int(_env("MINIHEROKU_API_PORT", "8000"))

# Tokens API : durée de vie en jours (None = jamais expiré)
TOKEN_TTL_DAYS = int(_env("MINIHEROKU_TOKEN_TTL_DAYS", "90"))

# Rate limiting sur les endpoints d'auth
LOGIN_RATE_MAX = int(_env("MINIHEROKU_LOGIN_RATE_MAX", "10"))
LOGIN_RATE_WINDOW = int(_env("MINIHEROKU_LOGIN_RATE_WINDOW", "900"))
REGISTER_RATE_MAX = int(_env("MINIHEROKU_REGISTER_RATE_MAX", "5"))
REGISTER_RATE_WINDOW = int(_env("MINIHEROKU_REGISTER_RATE_WINDOW", "3600"))

# Réseau Docker interne reliant apps et add-ons
ADDON_NETWORK = _env("MINIHEROKU_ADDON_NETWORK", "mh_addons")

# Répertoire de backup (scripts/backup.py)
BACKUP_DIR = _env("MINIHEROKU_BACKUP_DIR", os.path.join(BASE_DIR, "..", "mini-heroku-backups"))
BACKUP_KEEP = int(_env("MINIHEROKU_BACKUP_KEEP", "10"))
