from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
import sys, os
sys.path.insert(0, "/home/azureuser/mini-heroku")

from db.models import init_db, get_db, App, Release, EnvVar
from builder.build import build_and_push
from runner.run import run_container, stop_container, get_container_status
from proxy.caddy import update_caddyfile
from cryptography.fernet import Fernet

app = FastAPI(title="Mini Heroku API")
FERNET_KEY = Fernet.generate_key()
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

# ── DEPLOY ──────────────────────────────────────────────
@app.post("/apps/deploy")
def deploy(req: DeployRequest, db: Session = Depends(get_db)):
    # Get next version
    releases = db.query(Release).filter(Release.app_name == req.name).all()
    version = len(releases) + 1

    # Build image
    image = build_and_push(req.repo_url, req.name, version)

    # Get env vars
    env_rows = db.query(EnvVar).filter(EnvVar.app_name == req.name).all()
    env_vars = {}
    for row in env_rows:
        try:
            env_vars[row.key] = fernet.decrypt(row.value.encode()).decode()
        except:
            env_vars[row.key] = row.value

    # Run container
    port = run_container(req.name, image, env_vars)

    # Save to DB
    app_row = db.query(App).filter(App.name == req.name).first()
    if not app_row:
        app_row = App(name=req.name, status="running", port=port, image=image)
        db.add(app_row)
    else:
        app_row.status = "running"
        app_row.port = port
        app_row.image = image

    release = Release(app_name=req.name, version=version, image=image)
    db.add(release)
    db.commit()

    # Update Caddy
    all_apps = db.query(App).filter(App.status == "running").all()
    update_caddyfile([{"name": a.name, "port": a.port} for a in all_apps])

    return {"status": "deployed", "app": req.name, "port": port, "version": version}

# ── LIST APPS ────────────────────────────────────────────
@app.get("/apps")
def list_apps(db: Session = Depends(get_db)):
    apps = db.query(App).all()
    return [{"name": a.name, "status": a.status, "port": a.port} for a in apps]

# ── APP STATUS ───────────────────────────────────────────
@app.get("/apps/{name}")
def get_app(name: str, db: Session = Depends(get_db)):
    a = db.query(App).filter(App.name == name).first()
    if not a:
        raise HTTPException(404, "App not found")
    return {"name": a.name, "status": get_container_status(name),
            "port": a.port, "image": a.image}

# ── CONFIG ───────────────────────────────────────────────
@app.put("/apps/{name}/config")
def set_config(name: str, req: ConfigRequest, db: Session = Depends(get_db)):
    encrypted = fernet.encrypt(req.value.encode()).decode()
    row = db.query(EnvVar).filter(EnvVar.app_name == name, EnvVar.key == req.key).first()
    if row:
        row.value = encrypted
    else:
        db.add(EnvVar(app_name=name, key=req.key, value=encrypted))
    db.commit()
    return {"status": "ok", "key": req.key}

@app.get("/apps/{name}/config")
def get_config(name: str, db: Session = Depends(get_db)):
    rows = db.query(EnvVar).filter(EnvVar.app_name == name).all()
    return {r.key: "***" for r in rows}

# ── RESTART ──────────────────────────────────────────────
@app.post("/apps/{name}/restart")
def restart(name: str, db: Session = Depends(get_db)):
    a = db.query(App).filter(App.name == name).first()
    if not a:
        raise HTTPException(404, "App not found")
    env_rows = db.query(EnvVar).filter(EnvVar.app_name == name).all()
    env_vars = {r.key: fernet.decrypt(r.value.encode()).decode() for r in env_rows}
    port = run_container(name, a.image, env_vars, a.port)
    return {"status": "restarted", "app": name, "port": port}

# ── RELEASES ─────────────────────────────────────────────
@app.get("/apps/{name}/releases")
def get_releases(name: str, db: Session = Depends(get_db)):
    releases = db.query(Release).filter(Release.app_name == name).all()
    return [{"version": r.version, "image": r.image,
             "deployed_at": str(r.deployed_at)} for r in releases]

# ── SCALE ────────────────────────────────────────────────
@app.post("/apps/{name}/scale")
def scale(name: str, req: ScaleRequest, db: Session = Depends(get_db)):
    a = db.query(App).filter(App.name == name).first()
    if not a:
        raise HTTPException(404, "App not found")
    a.replicas = req.replicas
    db.commit()
    return {"status": "scaled", "app": name, "replicas": req.replicas}

# ── STOP ─────────────────────────────────────────────────
@app.post("/apps/{name}/stop")
def stop(name: str, db: Session = Depends(get_db)):
    stop_container(name)
    a = db.query(App).filter(App.name == name).first()
    if a:
        a.status = "stopped"
        db.commit()
    return {"status": "stopped", "app": name}
