from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import sys, os, docker as docker_sdk
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from db.models import get_db, App, Release, EnvVar, User
from api.main import fernet, docker_client, get_env_vars, get_app_domains
from api.security import (
    get_current_user, verify_password, hash_password, create_token, get_app_or_404,
)

router = APIRouter(prefix="/ui")
templates = Jinja2Templates(directory=os.environ.get(
    "MINIHEROKU_TEMPLATES", os.path.join(BASE_DIR, "ui", "templates")))

# ── LOGIN / LOGOUT ───────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": None})

@router.post("/login")
async def ui_login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "Invalid email or password"})
    resp = RedirectResponse(url="/ui/", status_code=303)
    resp.set_cookie("mh_token", user.token, httponly=True, samesite="lax")
    return resp

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="register.html", context={"error": None})

@router.post("/register")
async def ui_register(request: Request, db: Session = Depends(get_db)):
    from api.main import audit
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    if not email or "@" not in email:
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"error": "Invalid email"})
    if len(password) < 8:
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"error": "Password must be at least 8 characters"})
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"error": "Email already registered"})
    user = User(email=email, password=hash_password(password),
                token=create_token())
    db.add(user)
    db.commit()
    orphan = db.query(App).filter(App.owner_email.is_(None)).all()
    for a in orphan:
        a.owner_email = email
    db.commit()
    audit("register", "platform", {"email": email})
    resp = RedirectResponse(url="/ui/", status_code=303)
    resp.set_cookie("mh_token", user.token, httponly=True, samesite="lax")
    return resp

@router.get("/logout")
def ui_logout():
    resp = RedirectResponse(url="/ui/login", status_code=303)
    resp.delete_cookie("mh_token")
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
    return deploy(DR(), db, user)

@router.get("/apps/{name}", response_class=HTMLResponse)
def app_detail(name: str, request: Request, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    app = get_app_or_404(name, db, user)
    releases = db.query(Release).filter(
        Release.app_name == name).order_by(Release.version.desc()).all()
    config = {r.key: "***" for r in db.query(EnvVar).filter(EnvVar.app_name == name).all()}
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
    return templates.TemplateResponse(
        request=request,
        name="app.html",
        context={
            "app": app,
            "releases": releases,
            "config": config,
            "metrics": metrics,
            "domains": get_app_domains(name, db),
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
