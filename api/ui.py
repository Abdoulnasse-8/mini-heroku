from datetime import datetime

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import sys, os, docker as docker_sdk

import config
BASE_DIR = config.BASE_DIR
sys.path.insert(0, BASE_DIR)

from db.models import get_db, App, Release, EnvVar, User, Addon, AppAddon
from api.main import (fernet, docker_client, get_env_vars, get_app_domains,
                      _rate_limit, login_limiter, register_limiter, client_ip)
from api.security import (
    get_current_user, verify_password, hash_password, create_token,
    hash_token, token_ttl, create_csrf_token, get_app_or_404,
)

router = APIRouter(prefix="/ui")
templates = Jinja2Templates(directory=os.environ.get(
    "MINIHEROKU_TEMPLATES", os.path.join(BASE_DIR, "ui", "templates")))
templates.env.globals["base_domain"] = config.BASE_DOMAIN
templates.env.globals["docs_enabled"] = not config.IS_PRODUCTION

def _set_csrf(resp, token: str | None = None) -> None:
    resp.set_cookie("mh_csrf", token or create_csrf_token(), samesite="lax",
                    httponly=False)

def _csrf_page(request, name: str, **context):
    """Rend une page avec UN seul token CSRF partagé entre le formulaire et
    le cookie (sinon le double-submit échoue toujours)."""
    token = create_csrf_token()
    resp = templates.TemplateResponse(request=request, name=name,
                                      context={**context, "csrf_token": token})
    _set_csrf(resp, token)
    return resp

def _login_success(resp, user: User, db: Session) -> None:
    raw_token = create_token()
    user.token = hash_token(raw_token)
    ttl = token_ttl()
    user.token_expires_at = datetime.utcnow() + ttl if ttl else None
    db.commit()
    resp.set_cookie("mh_token", raw_token, httponly=True, samesite="lax",
                    secure=config.IS_PRODUCTION)
    _set_csrf(resp)

# ── LOGIN / LOGOUT ───────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _csrf_page(request, "login.html", error=None)

async def _get_form(request: Request):
    """Le middleware CSRF a déjà parsé le body (BaseHTTPMiddleware le
    consomme) — on relit son résultat depuis request.state."""
    form = getattr(request.state, "csrf_form", None)
    if form is not None:
        return form
    return await request.form()


@router.post("/login")
async def ui_login(request: Request, db: Session = Depends(get_db)):
    form = await _get_form(request)
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        ok, retry = login_limiter.allow(client_ip(request))
        if not ok:
            resp = _csrf_page(
                request, "login.html",
                error=f"Too many attempts — please try again in {retry} seconds")
            resp.status_code = 429
            return resp
        return _csrf_page(request, "login.html",
                          error="Invalid email or password")
    resp = RedirectResponse(url="/ui/", status_code=303)
    _login_success(resp, user, db)
    return resp

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return _csrf_page(request, "register.html", error=None)

@router.post("/register")
async def ui_register(request: Request, db: Session = Depends(get_db)):
    from api.main import audit
    _rate_limit(register_limiter, request)
    form = await _get_form(request)
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    def _err(msg):
        return _csrf_page(request, "register.html", error=msg)
    if not email or "@" not in email:
        return _err("Invalid email")
    if len(password) < 8:
        return _err("Password must be at least 8 characters")
    if db.query(User).filter(User.email == email).first():
        return _err("Email already registered")
    user = User(email=email, password=hash_password(password),
                token=hash_token(create_token()))
    db.add(user)
    db.commit()
    orphan = db.query(App).filter(App.owner_email.is_(None)).all()
    for a in orphan:
        a.owner_email = email
    db.commit()
    audit("register", "platform", {"email": email})
    resp = RedirectResponse(url="/ui/", status_code=303)
    _login_success(resp, user, db)
    return resp

@router.get("/logout")
def ui_logout():
    resp = RedirectResponse(url="/ui/login", status_code=303)
    resp.delete_cookie("mh_token")
    resp.delete_cookie("mh_csrf")
    return resp

@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    apps = db.query(App).filter(App.owner_email == user.email).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"apps": apps, "user": user}
    )

@router.get("/deploy", response_class=HTMLResponse)
def deploy_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        request=request, name="deploy.html", context={"user": user}
    )

@router.post("/deploy")
async def deploy_app(request: Request, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    from api.main import deploy
    data = await request.json()
    class DR:
        name = data["name"]
        repo_url = data["repo_url"]
        dockerfile = data.get("dockerfile") or None
    return deploy(DR(), db, user)

# ── ADD-ONS (UI) ─────────────────────────────────────────
@router.get("/addons", response_class=HTMLResponse)
def addons_page(request: Request, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    addons = db.query(Addon).filter(Addon.owner_email == user.email).all()
    return templates.TemplateResponse(
        request=request, name="addons.html",
        context={"addons": addons, "user": user})

@router.post("/addons")
async def ui_addon_create(request: Request, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    from api.main import create_addon, AddonRequest
    data = await request.json()
    return create_addon(AddonRequest(name=data["name"], kind=data["kind"]),
                        db, user)

@router.delete("/addons/{name}")
def ui_addon_destroy(name: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    from api.main import destroy_addon
    return destroy_addon(name, db, user)

@router.post("/apps/{name}/addons/{addon}")
def ui_addon_attach(name: str, addon: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    from api.main import attach_addon
    return attach_addon(name, addon, db, user)

@router.delete("/apps/{name}/addons/{addon}")
def ui_addon_detach(name: str, addon: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    from api.main import detach_addon
    return detach_addon(name, addon, db, user)

# ── APP DETAIL ───────────────────────────────────────────
@router.get("/apps/{name}", response_class=HTMLResponse)
def app_detail(name: str, request: Request, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    app = get_app_or_404(name, db, user)
    releases = db.query(Release).filter(
        Release.app_name == name).order_by(Release.version.desc()).all()
    config_ = {r.key: "***" for r in db.query(EnvVar).filter(EnvVar.app_name == name).all()}
    metrics = None
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
        metrics = {
            "cpu_percent": round(cpu_pct, 2),
            "memory_mb": round(mem_usage / 1024 / 1024, 2),
            "memory_percent": round((mem_usage / mem_limit) * 100, 2),
            "memory_limit_mb": round(mem_limit / 1024 / 1024, 2)
        }
    except Exception:
        pass
    attached = [{"name": x.addon_name, "kind": ""} for x in
                db.query(AppAddon).filter(AppAddon.app_name == name).all()]
    addon_kinds = {a.name: a.kind for a in
                   db.query(Addon).filter(Addon.owner_email == user.email).all()}
    for att in attached:
        att["kind"] = addon_kinds.get(att["name"], "")
    return templates.TemplateResponse(
        request=request,
        name="app.html",
        context={
            "app": app,
            "releases": releases,
            "config": config_,
            "metrics": metrics,
            "domains": get_app_domains(name, db),
            "addons": attached,
            "user": user,
        }
    )

@router.post("/apps/{name}/redeploy")
def ui_redeploy(name: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Rebuild and deploy the latest code from the app's git repo (blue-green)."""
    from api.main import deploy_zero_downtime
    return deploy_zero_downtime(name, db, user)

@router.post("/apps/{name}/restart")
def ui_restart(name: str, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    from api.main import restart
    return restart(name, db, user)

@router.post("/apps/{name}/stop")
def ui_stop(name: str, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    from api.main import stop
    return stop(name, db, user)

@router.post("/apps/{name}/scale")
async def ui_scale(name: str, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    from api.main import scale, ScaleRequest
    data = await request.json()
    return scale(name, ScaleRequest(replicas=data["replicas"]), db, user)

@router.post("/apps/{name}/config")
async def ui_config_set(name: str, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    from api.main import set_config, ConfigRequest
    data = await request.json()
    return set_config(name, ConfigRequest(key=data["key"], value=data["value"]), db, user)

@router.delete("/apps/{name}/config/{key}")
def ui_config_delete(name: str, key: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    from api.main import delete_config
    return delete_config(name, key, db, user)

@router.get("/apps/{name}/logs")
def ui_logs(name: str, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    from api.main import stream_logs
    return stream_logs(name, follow=False, tail=100, db=db, user=user)

@router.post("/apps/{name}/rollback/{version}")
def ui_rollback(name: str, version: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    from api.main import rollback
    return rollback(name, version, db, user)

@router.post("/apps/{name}/domains")
async def ui_domains_add(name: str, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    from api.main import add_domain, DomainRequest
    data = await request.json()
    return add_domain(name, DomainRequest(domain=data["domain"]), db, user)

@router.delete("/apps/{name}/domains/{domain}")
def ui_domains_remove(name: str, domain: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    from api.main import remove_domain
    return remove_domain(name, domain, db, user)