import hmac
import json as _json
import logging
import secrets
import socket
import sys
import os
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import docker as docker_sdk

import config
BASE_DIR = config.BASE_DIR
sys.path.insert(0, BASE_DIR)

from db.models import (init_db, get_db, SessionLocal, App, Release, EnvVar,
                       CustomDomain, User, Addon, AppAddon, AuditLog)
from builder.build import build_and_push
from runner.run import (run_container, stop_container, get_container_status,
                        wait_healthy, get_free_port, _ensure_addon_network)
from proxy.caddy import update_caddyfile
from cryptography.fernet import Fernet
from api.security import (
    get_current_user,
    get_app_or_404,
    hash_password,
    verify_password,
    create_token,
    hash_token,
    token_ttl,
    create_csrf_token,
    same_origin,
    validate_app_name,
    validate_repo_url,
)
from api.ratelimit import RateLimiter, client_ip

logger = logging.getLogger("mini-heroku")
logging.basicConfig(level=logging.INFO)

# Docs/Swagger désactivés en production
if config.IS_PRODUCTION:
    app = FastAPI(title="Mini Heroku API", docs_url=None, redoc_url=None,
                  openapi_url=None)
else:
    app = FastAPI(title="Mini Heroku API")

docker_client = docker_sdk.from_env()

# ── RATE LIMITING (auth) ─────────────────────────────────
login_limiter = RateLimiter(config.LOGIN_RATE_MAX, config.LOGIN_RATE_WINDOW)
register_limiter = RateLimiter(config.REGISTER_RATE_MAX, config.REGISTER_RATE_WINDOW)

def _rate_limit(limiter: RateLimiter, request: Request):
    ok, retry = limiter.allow(client_ip(request))
    if not ok:
        exc = HTTPException(429, "Too many attempts — please try again later")
        exc.headers = {"Retry-After": str(retry)}
        raise exc

# ── CSRF (UI) ────────────────────────────────────────────
@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    method = request.method
    path = request.url.path
    if method in ("POST", "PUT", "DELETE", "PATCH") and path.startswith("/ui"):
        if path in ("/ui/login", "/ui/register"):
            form_token = (await request.form()).get("csrf_token")
            cookie_token = request.cookies.get("mh_csrf")
            request.state.csrf_form = await request.form()
            if not form_token or not cookie_token or \
                    not hmac.compare_digest(form_token, cookie_token):
                return JSONResponse(status_code=403,
                                    content={"detail": "CSRF validation failed"})
        else:
            header_token = request.headers.get("x-csrf-token")
            cookie_token = request.cookies.get("mh_csrf")
            if not header_token or not cookie_token or \
                    not hmac.compare_digest(header_token, cookie_token):
                return JSONResponse(status_code=403,
                                    content={"detail": "CSRF validation failed"})
    return await call_next(request)

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    from fastapi.responses import RedirectResponse
    accept = request.headers.get("accept", "")
    if exc.status_code in (401, 403) and "text/html" in accept:
        return RedirectResponse(url="/ui/login")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                        headers=getattr(exc, "headers", None))

# Clé Fernet persistante — stockée HORS du repo (répertoire utilisateur)
FERNET_KEY_FILE = config.FERNET_KEY_FILE
try:
    with open(FERNET_KEY_FILE, "rb") as f:
        FERNET_KEY = f.read()
except FileNotFoundError:
    os.makedirs(os.path.dirname(FERNET_KEY_FILE), exist_ok=True)
    FERNET_KEY = Fernet.generate_key()
    with open(FERNET_KEY_FILE, "wb") as f:
        f.write(FERNET_KEY)
os.chmod(FERNET_KEY_FILE, 0o600)
fernet = Fernet(FERNET_KEY)

@app.on_event("startup")
def startup():
    init_db()
    print("DB initialized ✅")

# ── MODELS ──────────────────────────────────────────────
class DeployRequest(BaseModel):
    name: str
    repo_url: str

class ConfigRequest(BaseModel):
    key: str
    value: str

class ScaleRequest(BaseModel):
    replicas: int

class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class DomainRequest(BaseModel):
    domain: str

class AddonRequest(BaseModel):
    name: str
    kind: str

# ── AUTH ────────────────────────────────────────────────
@app.post("/auth/register")
def register(req: RegisterRequest, request: Request,
             db: Session = Depends(get_db)):
    _rate_limit(register_limiter, request)
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Invalid email")
    if len(req.password or "") < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Email already registered")
    raw_token = create_token()
    ttl = token_ttl()
    user = User(
        email=email,
        password=hash_password(req.password),
        token=hash_token(raw_token),
        token_expires_at=datetime.utcnow() + ttl if ttl else None,
    )
    db.add(user)
    db.commit()
    # Adopter les apps legacy (sans propriétaire) créées avant l'auth
    orphan = db.query(App).filter(App.owner_email.is_(None)).all()
    for a in orphan:
        a.owner_email = email
    db.commit()
    audit("register", "platform", {"email": email})
    return {"status": "ok", "email": email, "token": raw_token}

@app.post("/auth/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = (req.email or "").strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(req.password, user.password):
        # On ne rate-limit que les ÉCHECS : un utilisateur légitime qui se
        # trompe de mot de passe ne se bloque pas.
        _rate_limit(login_limiter, request)
        raise HTTPException(401, "Invalid email or password")
    # Rotation du token à chaque connexion (le précédent est invalidé)
    raw_token = create_token()
    user.token = hash_token(raw_token)
    ttl = token_ttl()
    user.token_expires_at = datetime.utcnow() + ttl if ttl else None
    db.commit()
    audit("login", "platform", {"email": email})
    return {"status": "ok", "email": user.email, "token": raw_token}

@app.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"email": user.email, "created_at": str(user.created_at)}

@app.post("/auth/rotate-token")
def rotate_token(db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Émet un nouveau token (le précédent est invalidé)."""
    raw_token = create_token()
    user.token = hash_token(raw_token)
    ttl = token_ttl()
    user.token_expires_at = datetime.utcnow() + ttl if ttl else None
    db.commit()
    audit("token:rotate", "platform", {"email": user.email})
    return {"status": "ok", "token": raw_token,
            "expires_at": str(user.token_expires_at) if user.token_expires_at else None}

@app.post("/auth/revoke-token")
def revoke_token(db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Révoque le token courant (il devient immédiatement invalide)."""
    user.token = hash_token(create_token())
    user.token_expires_at = None
    db.commit()
    audit("token:revoke", "platform", {"email": user.email})
    return {"status": "revoked"}

# ── HELPERS ─────────────────────────────────────────────
def get_env_vars(app_name: str, db: Session) -> dict:
    rows = db.query(EnvVar).filter(EnvVar.app_name == app_name).all()
    result = {}
    for row in rows:
        try:
            result[row.key] = fernet.decrypt(row.value.encode()).decode()
        except Exception as e:
            logger.error("Failed to decrypt env var '%s' for app '%s': %s",
                         row.key, app_name, e)
            raise HTTPException(
                500, f"Failed to decrypt env var '{row.key}' for app '{app_name}' "
                     f"— the Fernet key may have changed")
    return result

def get_app_domains(app_name: str, db: Session) -> list[str]:
    rows = db.query(CustomDomain).filter(CustomDomain.app_name == app_name).all()
    return [r.domain for r in rows]

def _caddy_apps(db: Session) -> list[dict]:
    apps = db.query(App).filter(App.status == "running").all()
    result = []
    for a in apps:
        replica_ports = None
        if a.replica_ports:
            try:
                replica_ports = _json.loads(a.replica_ports)
            except Exception:
                replica_ports = None
        entry = {"name": a.name, "port": a.port,
                 "domains": get_app_domains(a.name, db)}
        if replica_ports:
            entry["ports"] = replica_ports
        result.append(entry)
    return result

def _refresh_caddy(db: Session):
    update_caddyfile(_caddy_apps(db))

# ── ADD-ONS (Postgres / Redis) ──────────────────────────
ADDON_IMAGES = {"postgres": "postgres:16-alpine", "redis": "redis:7-alpine"}
ADDON_INTERNAL_PORT = {"postgres": 5432, "redis": 6379}
ADDON_ENV_KEY = {"postgres": "DATABASE_URL", "redis": "REDIS_URL"}

def _addon_url(addon: Addon, password: str) -> str:
    if addon.kind == "postgres":
        return f"postgresql://postgres:{password}@addon-{addon.name}:5432/{addon.name}"
    return f"redis://default:{password}@addon-{addon.name}:6379/0"

def _get_addon_or_404(name: str, db: Session, user: User) -> Addon:
    addon = db.query(Addon).filter(Addon.name == name).first()
    if not addon:
        raise HTTPException(404, "Add-on not found")
    if addon.owner_email != user.email:
        raise HTTPException(403, "You do not own this add-on")
    return addon

@app.post("/addons")
def create_addon(req: AddonRequest, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    name = validate_app_name(req.name)
    kind = (req.kind or "").strip().lower()
    if kind not in ADDON_IMAGES:
        raise HTTPException(400, "kind must be 'postgres' or 'redis'")
    if db.query(Addon).filter(Addon.name == name).first():
        raise HTTPException(409, "Add-on already exists")
    password = secrets.token_urlsafe(24)
    env = {"POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": password,
           "POSTGRES_DB": name} if kind == "postgres" else {}
    command = (["redis-server", "--requirepass", password, "--save", "",
                "--appendonly", "no"] if kind == "redis" else None)
    try:
        _ensure_addon_network()
        docker_client.containers.run(
            ADDON_IMAGES[kind],
            name=f"addon-{name}",
            detach=True,
            network=config.ADDON_NETWORK,
            environment=env,
            command=command,
            mem_limit="256m",
            nano_cpus=250_000_000,
            restart_policy={"Name": "unless-stopped"},
        )
    except docker_sdk.errors.APIError as e:
        audit("addon:create", name, {"kind": kind, "error": str(e)}, "error")
        raise HTTPException(502, f"Failed to start {kind} add-on: {e}")
    addon = Addon(name=name, owner_email=user.email, kind=kind,
                  password=fernet.encrypt(password.encode()).decode(),
                  status="running")
    db.add(addon)
    db.commit()
    audit("addon:create", name, {"kind": kind})
    return {"status": "created", "name": name, "kind": kind,
            "url": _addon_url(addon, password)}

@app.get("/addons")
def list_addons(db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    addons = db.query(Addon).filter(Addon.owner_email == user.email).all()
    return [{"name": a.name, "kind": a.kind, "status": a.status,
             "created_at": str(a.created_at)} for a in addons]

@app.delete("/addons/{name}")
def destroy_addon(name: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    addon = _get_addon_or_404(name, db, user)
    try:
        c = docker_client.containers.get(f"addon-{name}")
        c.stop()
        c.remove()
    except docker_sdk.errors.NotFound:
        pass
    # Détacher proprement des apps qui l'utilisent (supprime la var d'env)
    assocs = db.query(AppAddon).filter(AppAddon.addon_name == name).all()
    for a in assocs:
        key = ADDON_ENV_KEY[addon.kind]
        row = db.query(EnvVar).filter(
            EnvVar.app_name == a.app_name, EnvVar.key == key).first()
        if row:
            db.delete(row)
        db.delete(a)
    db.delete(addon)
    db.commit()
    audit("addon:destroy", name, {"kind": addon.kind})
    return {"status": "destroyed", "name": name}

@app.post("/apps/{name}/addons/{addon_name}")
def attach_addon(name: str, addon_name: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    a = get_app_or_404(name, db, user)
    addon = _get_addon_or_404(addon_name, db, user)
    password = fernet.decrypt(addon.password.encode()).decode()
    url = _addon_url(addon, password)
    key = ADDON_ENV_KEY[addon.kind]
    existing = db.query(EnvVar).filter(
        EnvVar.app_name == name, EnvVar.key == key).first()
    if existing:
        existing.value = fernet.encrypt(url.encode()).decode()
    else:
        db.add(EnvVar(app_name=name, key=key,
                      value=fernet.encrypt(url.encode()).decode()))
    if not db.query(AppAddon).filter(
            AppAddon.app_name == name,
            AppAddon.addon_name == addon_name).first():
        db.add(AppAddon(app_name=name, addon_name=addon_name))
    db.commit()
    env_vars = get_env_vars(name, db)
    port = run_container(name, a.image, env_vars, a.port)
    if not wait_healthy(port):
        stop_container(name)
        audit("addon:attach", name, {"addon": addon_name,
                                     "error": "health check failed"}, "error")
        raise HTTPException(502, "App did not become healthy after attaching add-on")
    a.port = port
    a.status = "running"
    db.commit()
    _refresh_caddy(db)
    audit("addon:attach", name, {"addon": addon_name, "key": key})
    return {"status": "attached", "app": name, "addon": addon_name, "key": key}

@app.delete("/apps/{name}/addons/{addon_name}")
def detach_addon(name: str, addon_name: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    a = get_app_or_404(name, db, user)
    addon = _get_addon_or_404(addon_name, db, user)
    key = ADDON_ENV_KEY[addon.kind]
    row = db.query(EnvVar).filter(
        EnvVar.app_name == name, EnvVar.key == key).first()
    if row:
        db.delete(row)
    assoc = db.query(AppAddon).filter(
        AppAddon.app_name == name, AppAddon.addon_name == addon_name).first()
    if assoc:
        db.delete(assoc)
    db.commit()
    env_vars = get_env_vars(name, db)
    port = run_container(name, a.image, env_vars, a.port)
    a.port = port
    a.status = "running"
    db.commit()
    _refresh_caddy(db)
    audit("addon:detach", name, {"addon": addon_name, "key": key})
    return {"status": "detached", "app": name, "addon": addon_name}

@app.get("/apps/{name}/addons")
def list_app_addons(name: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    assoc = db.query(AppAddon).filter(AppAddon.app_name == name).all()
    names = [x.addon_name for x in assoc]
    if not names:
        return []
    addons = db.query(Addon).filter(Addon.name.in_(names)).all()
    return [{"name": a.name, "kind": a.kind} for a in addons]

# ── DEPLOY ──────────────────────────────────────────────
@app.post("/apps/deploy")
def deploy(req: DeployRequest, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    name = validate_app_name(req.name)
    repo_url = validate_repo_url(req.repo_url)
    releases = db.query(Release).filter(Release.app_name == name).all()
    version = len(releases) + 1
    try:
        image = build_and_push(repo_url, name, version)
    except Exception as e:
        audit("deploy", name, {"error": str(e)}, "error")
        raise HTTPException(502, f"Build failed: {e}")
    env_vars = get_env_vars(name, db)
    port = run_container(name, image, env_vars)
    if not wait_healthy(port):
        stop_container(name)
        audit("deploy", name, {"error": "health check failed after deploy"}, "error")
        raise HTTPException(502, "App did not become healthy within 30s — check the Dockerfile / logs")
    app_row = db.query(App).filter(App.name == name).first()
    if not app_row:
        app_row = App(name=name, owner_email=user.email, repo_url=repo_url,
                      status="running", port=port, image=image)
        db.add(app_row)
    else:
        if app_row.owner_email not in (None, user.email):
            raise HTTPException(403, "You do not own this app")
        app_row.owner_email = user.email
        app_row.repo_url = repo_url
        app_row.status = "running"
        app_row.port = port
        app_row.image = image
    release = Release(app_name=name, version=version, image=image)
    db.add(release)
    db.commit()
    _refresh_caddy(db)
    audit("deploy", name, {"version": version, "port": port, "image": image})
    return {"status": "deployed", "app": name, "port": port, "version": version}

# ── LIST + GET ───────────────────────────────────────────
@app.get("/apps")
def list_apps(db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    apps = db.query(App).filter(App.owner_email == user.email).all()
    return [{"name": a.name, "status": a.status, "port": a.port} for a in apps]

@app.get("/apps/{name}")
def get_app(name: str, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    a = get_app_or_404(name, db, user)
    return {"name": a.name, "status": get_container_status(name),
            "port": a.port, "image": a.image, "replicas": a.replicas}

# ── CONFIG ───────────────────────────────────────────────
@app.put("/apps/{name}/config")
def set_config(name: str, req: ConfigRequest, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    a = get_app_or_404(name, db, user)
    encrypted = fernet.encrypt(req.value.encode()).decode()
    row = db.query(EnvVar).filter(
        EnvVar.app_name == name, EnvVar.key == req.key).first()
    if row:
        row.value = encrypted
    else:
        db.add(EnvVar(app_name=name, key=req.key, value=encrypted))
    db.commit()
    audit("config:set", name, {"key": req.key})
    return {"status": "ok", "key": req.key}

@app.get("/apps/{name}/config")
def get_config(name: str, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    rows = db.query(EnvVar).filter(EnvVar.app_name == name).all()
    return {r.key: "***" for r in rows}

@app.delete("/apps/{name}/config/{key}")
def delete_config(name: str, key: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    row = db.query(EnvVar).filter(
        EnvVar.app_name == name, EnvVar.key == key).first()
    if not row:
        raise HTTPException(404, "Key not found")
    db.delete(row)
    db.commit()
    audit("config:unset", name, {"key": key})
    return {"status": "deleted", "key": key}

# ── LOGS STREAMING ───────────────────────────────────────
@app.get("/apps/{name}/logs")
def stream_logs(name: str, follow: bool = False, tail: int = 50,
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    def generate():
        try:
            container = docker_client.containers.get(f"app-{name}")
            for line in container.logs(stream=True, follow=follow, tail=tail):
                decoded = line.decode("utf-8", errors="replace").strip()
                yield f"data: {decoded}\n\n"
        except docker_sdk.errors.NotFound:
            yield f"data: ERROR: container app-{name} not found\n\n"
        except Exception as e:
            yield f"data: ERROR: {e}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

# ── MÉTRIQUES ────────────────────────────────────────────
@app.get("/apps/{name}/metrics")
def get_metrics(name: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    try:
        container = docker_client.containers.get(f"app-{name}")
        stats = container.stats(stream=False)
        cpu_delta = (stats["cpu_stats"]["cpu_usage"]["total_usage"] -
                     stats["precpu_stats"]["cpu_usage"]["total_usage"])
        system_delta = (stats["cpu_stats"].get("system_cpu_usage", 1) -
                        stats["precpu_stats"].get("system_cpu_usage", 0))
        num_cpus = stats["cpu_stats"].get("online_cpus", 1)
        cpu_pct = (cpu_delta / system_delta) * num_cpus * 100 if system_delta > 0 else 0
        mem_usage = stats["memory_stats"].get("usage", 0)
        mem_limit = stats["memory_stats"].get("limit", 1)
        mem_pct = (mem_usage / mem_limit) * 100
        return {
            "app": name,
            "cpu_percent": round(cpu_pct, 2),
            "memory_mb": round(mem_usage / 1024 / 1024, 2),
            "memory_percent": round(mem_pct, 2),
            "memory_limit_mb": round(mem_limit / 1024 / 1024, 2)
        }
    except docker_sdk.errors.NotFound:
        raise HTTPException(404, f"Container app-{name} not found")
    except Exception as e:
        raise HTTPException(500, str(e))

# ── SCALING ──────────────────────────────────────────────
@app.post("/apps/{name}/scale")
def scale(name: str, req: ScaleRequest, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    a = get_app_or_404(name, db, user)
    if req.replicas < 0 or req.replicas > 10:
        raise HTTPException(400, "replicas must be between 0 and 10")
    env_vars = get_env_vars(name, db)
    ports = []
    # Stopper les anciens replicas
    for i in range(10):
        try:
            c = docker_client.containers.get(f"app-{name}-replica-{i}")
            c.stop(); c.remove()
        except:
            pass
    # Lancer N replicas
    for i in range(req.replicas):
        port = get_free_port()
        container_name = f"app-{name}-replica-{i}"
        try:
            old = docker_client.containers.get(container_name)
            old.stop(); old.remove()
        except:
            pass
        _ensure_addon_network()
        docker_client.containers.run(
            a.image,
            name=container_name,
            detach=True,
            network=config.ADDON_NETWORK,
            ports={f"{config.CONTAINER_PORT}/tcp": (config.APP_BIND_HOST, port)},
            environment=env_vars,
            mem_limit="256m",
            nano_cpus=250_000_000,
            restart_policy={"Name": "unless-stopped"}
        )
        ports.append(port)
    a.replicas = req.replicas
    a.replica_ports = _json.dumps(ports) if ports else None
    db.commit()
    _refresh_caddy(db)
    audit("scale", name, {"replicas": req.replicas, "ports": ports})
    return {"status": "scaled", "app": name, "replicas": req.replicas, "ports": ports}

# ── RESTART ──────────────────────────────────────────────
@app.post("/apps/{name}/restart")
def restart(name: str, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    a = get_app_or_404(name, db, user)
    env_vars = get_env_vars(name, db)
    port = run_container(name, a.image, env_vars, a.port)
    if not wait_healthy(port):
        stop_container(name)
        audit("restart", name, {"error": "health check failed"}, "error")
        raise HTTPException(502, "App did not become healthy within 30s after restart")
    audit("restart", name, {"port": port})
    return {"status": "restarted", "app": name, "port": port}

# ── STOP ─────────────────────────────────────────────────
@app.post("/apps/{name}/stop")
def stop(name: str, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    stop_container(name)
    a = db.query(App).filter(App.name == name).first()
    if a:
        a.status = "stopped"
        db.commit()
    audit("stop", name, {})
    return {"status": "stopped", "app": name}

# ── RELEASES ─────────────────────────────────────────────
@app.get("/apps/{name}/releases")
def get_releases(name: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    releases = db.query(Release).filter(Release.app_name == name).all()
    return [{"version": r.version, "image": r.image,
             "deployed_at": str(r.deployed_at)} for r in releases]

# ── ROLLBACK ─────────────────────────────────────────────
@app.post("/apps/{name}/rollback")
def rollback(name: str, version: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    release = db.query(Release).filter(
        Release.app_name == name, Release.version == version).first()
    if not release:
        raise HTTPException(404, f"Release v{version} not found")
    env_vars = get_env_vars(name, db)
    port = run_container(name, release.image, env_vars)
    a = db.query(App).filter(App.name == name).first()
    if a:
        a.port = port
        a.image = release.image
        a.status = "running"
        db.commit()
    _refresh_caddy(db)
    audit("rollback", name, {"version": version, "port": port})
    return {"status": "rolled back", "app": name, "version": version, "port": port}

# ── PS ───────────────────────────────────────────────────
@app.get("/apps/{name}/ps")
def ps(name: str, db: Session = Depends(get_db),
       user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    containers = docker_client.containers.list(
        filters={"name": f"app-{name}"})
    return [{"name": c.name, "status": c.status,
             "ports": c.ports} for c in containers]

# ── CUSTOM DOMAINS ───────────────────────────────────────
@app.post("/apps/{name}/domains")
def add_domain(name: str, req: DomainRequest, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    domain = (req.domain or "").strip().lower()
    if (not domain or "." not in domain or " " in domain
            or domain.startswith(".") or domain.endswith(".")):
        raise HTTPException(400, "Invalid domain")
    existing = db.query(CustomDomain).filter(CustomDomain.domain == domain).first()
    if existing:
        raise HTTPException(409, "Domain already used by another app")
    db.add(CustomDomain(app_name=name, domain=domain))
    db.commit()
    _refresh_caddy(db)
    audit("domain:add", name, {"domain": domain})
    return {"status": "added", "app": name, "domain": domain}

@app.get("/apps/{name}/domains")
def list_domains(name: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    return get_app_domains(name, db)

@app.delete("/apps/{name}/domains/{domain}")
def remove_domain(name: str, domain: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    get_app_or_404(name, db, user)
    row = db.query(CustomDomain).filter(
        CustomDomain.app_name == name, CustomDomain.domain == domain).first()
    if not row:
        raise HTTPException(404, "Domain not found")
    db.delete(row)
    db.commit()
    _refresh_caddy(db)
    audit("domain:remove", name, {"domain": domain})
    return {"status": "removed", "domain": domain}

# ── WEB UI ───────────────────────────────────────────────
from api.ui import router as ui_router
app.include_router(ui_router)

@app.get("/")
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui/")

# ── AUDIT LOG ────────────────────────────────────────────
def audit(action: str, app_name: str, details: dict, status: str = "success"):
    db = SessionLocal()
    try:
        log = AuditLog(
            action=action,
            app_name=app_name,
            details=_json.dumps(details),
            status=status
        )
        db.add(log)
        db.commit()
    finally:
        db.close()

@app.get("/audit")
def get_audit_log(limit: int = 50, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{
        "id": l.id,
        "action": l.action,
        "app": l.app_name,
        "details": _json.loads(l.details) if l.details else {},
        "status": l.status,
        "timestamp": str(l.created_at)
    } for l in logs]

@app.get("/audit/{app_name}")
def get_app_audit(app_name: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    get_app_or_404(app_name, db, user)
    logs = db.query(AuditLog).filter(
        AuditLog.app_name == app_name
    ).order_by(AuditLog.created_at.desc()).limit(20).all()
    return [{
        "action": l.action,
        "details": _json.loads(l.details) if l.details else {},
        "status": l.status,
        "timestamp": str(l.created_at)
    } for l in logs]

# ── ZERO-DOWNTIME DEPLOY (Blue-Green) ────────────────────
@app.post("/apps/{name}/deploy-zero-downtime")
def deploy_zero_downtime(name: str, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """Blue-green deploy — construit la nouvelle version et bascule sans coupure."""
    a = get_app_or_404(name, db, user)
    if not a.repo_url:
        raise HTTPException(400, "This app has no repo_url — deploy it once first")

    env_vars = get_env_vars(name, db)

    # 1. Construire une NOUVELLE version depuis le code source
    latest = db.query(Release).filter(
        Release.app_name == name
    ).order_by(Release.version.desc()).first()
    new_version = (latest.version if latest else 0) + 1
    try:
        new_image = build_and_push(a.repo_url, name, new_version)
    except Exception as e:
        audit("deploy-zero-downtime", name, {"error": str(e)}, "error")
        raise HTTPException(502, f"Build failed: {e}")
    print(f"[blue-green] Built new image {new_image}")

    # 2. Lancer le nouveau container (green) sur un nouveau port
    green_port = get_free_port()
    green_name = f"app-{name}-green"
    try:
        old = docker_client.containers.get(green_name)
        old.stop(); old.remove()
    except:
        pass

    _ensure_addon_network()
    docker_client.containers.run(
        new_image,
        name=green_name,
        detach=True,
        network=config.ADDON_NETWORK,
        ports={f"{config.CONTAINER_PORT}/tcp": (config.APP_BIND_HOST, green_port)},
        environment=env_vars,
        mem_limit="512m",
        nano_cpus=500_000_000,
        restart_policy={"Name": "unless-stopped"}
    )
    print(f"[blue-green] Green container started on port {green_port}")

    # 3. Health check du nouveau container (max 30s)
    import time as _time
    healthy = wait_healthy(green_port)
    print(f"[blue-green] Green healthy: {healthy}")

    if not healthy:
        # Rollback — stopper le green et garder le blue
        try:
            docker_client.containers.get(green_name).stop()
            docker_client.containers.get(green_name).remove()
        except:
            pass
        audit("deploy-zero-downtime", name, {"error": "green unhealthy"}, "error")
        raise HTTPException(500, "New version failed health check — keeping old version")

    # 4. Basculer Caddy vers le green
    old_port = a.port
    old_name = f"app-{name}-blue"

    # Renommer l'ancien en blue
    try:
        blue = docker_client.containers.get(f"app-{name}")
        blue.rename(old_name)
    except:
        pass

    # Renommer le green en production
    try:
        green = docker_client.containers.get(green_name)
        green.rename(f"app-{name}")
    except:
        pass

    # 5. Mettre à jour DB + Caddy
    a.port = green_port
    a.image = new_image
    a.status = "running"
    release = Release(app_name=name, version=new_version, image=new_image)
    db.add(release)
    db.commit()
    _refresh_caddy(db)

    # 6. Stopper l'ancien container (blue) après la bascule
    _time.sleep(2)
    try:
        blue = docker_client.containers.get(old_name)
        blue.stop()
        blue.remove()
        print(f"[blue-green] Blue container stopped")
    except:
        pass

    audit("deploy-zero-downtime", name, {
        "version": new_version,
        "old_port": old_port,
        "new_port": green_port,
        "image": new_image
    })

    return {
        "status": "deployed",
        "strategy": "blue-green",
        "app": name,
        "version": new_version,
        "old_port": old_port,
        "new_port": green_port,
        "downtime": "0s"
    }