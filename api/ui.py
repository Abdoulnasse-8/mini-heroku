from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import sys, docker as docker_sdk
sys.path.insert(0, "/home/azureuser/mini-heroku")

from db.models import get_db, App, Release, EnvVar
from api.main import fernet, docker_client, get_env_vars

router = APIRouter(prefix="/ui")
templates = Jinja2Templates(directory="/home/azureuser/mini-heroku/ui/templates")

@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    apps = db.query(App).all()
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"apps": apps}
    )

@router.get("/deploy", response_class=HTMLResponse)
def deploy_page(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="deploy.html"
    )

@router.post("/deploy")
async def deploy_app(request: Request, db: Session = Depends(get_db)):
    from api.main import deploy
    data = await request.json()
    class DR:
        name = data["name"]
        repo_url = data["repo_url"]
    return deploy(DR(), db)

@router.get("/apps/{name}", response_class=HTMLResponse)
def app_detail(name: str, request: Request, db: Session = Depends(get_db)):
    app = db.query(App).filter(App.name == name).first()
    if not app:
        return HTMLResponse("App not found", status_code=404)
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
            "metrics": metrics
        }
    )

@router.post("/apps/{name}/restart")
def ui_restart(name: str, db: Session = Depends(get_db)):
    from api.main import restart
    return restart(name, db)

@router.post("/apps/{name}/stop")
def ui_stop(name: str, db: Session = Depends(get_db)):
    from api.main import stop
    return stop(name, db)

@router.post("/apps/{name}/scale")
async def ui_scale(name: str, request: Request, db: Session = Depends(get_db)):
    from api.main import scale, ScaleRequest
    data = await request.json()
    return scale(name, ScaleRequest(replicas=data["replicas"]), db)

@router.post("/apps/{name}/config")
async def ui_config_set(name: str, request: Request, db: Session = Depends(get_db)):
    from api.main import set_config, ConfigRequest
    data = await request.json()
    return set_config(name, ConfigRequest(key=data["key"], value=data["value"]), db)

@router.delete("/apps/{name}/config/{key}")
def ui_config_delete(name: str, key: str, db: Session = Depends(get_db)):
    from api.main import delete_config
    return delete_config(name, key, db)

@router.get("/apps/{name}/logs")
def ui_logs(name: str):
    from api.main import stream_logs
    return stream_logs(name, follow=False, tail=100)

@router.post("/apps/{name}/rollback/{version}")
def ui_rollback(name: str, version: int, db: Session = Depends(get_db)):
    from api.main import rollback
    return rollback(name, version, db)
