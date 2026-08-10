from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import sys, socket, docker as docker_sdk
sys.path.insert(0, "/home/azureuser/mini-heroku")

from db.models import init_db, get_db, SessionLocal, App, Release, EnvVar
from builder.build import build_and_push
from runner.run import run_container, stop_container, get_container_status
from proxy.caddy import update_caddyfile, update_caddyfile_replicas
from cryptography.fernet import Fernet

app = FastAPI(title="Mini Heroku API")
docker_client = docker_sdk.from_env()

# Clé Fernet persistante
FERNET_KEY_FILE = "/home/azureuser/mini-heroku/.fernet_key"
try:
    with open(FERNET_KEY_FILE, "rb") as f:
        FERNET_KEY = f.read()
except FileNotFoundError:
    FERNET_KEY = Fernet.generate_key()
    with open(FERNET_KEY_FILE, "wb") as f:
        f.write(FERNET_KEY)
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

# ── HELPERS ─────────────────────────────────────────────
def get_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def get_env_vars(app_name: str, db: Session) -> dict:
    rows = db.query(EnvVar).filter(EnvVar.app_name == app_name).all()
    result = {}
    for row in rows:
        try:
            result[row.key] = fernet.decrypt(row.value.encode()).decode()
        except:
            result[row.key] = row.value
    return result

# ── DEPLOY ──────────────────────────────────────────────
@app.post("/apps/deploy")
def deploy(req: DeployRequest, db: Session = Depends(get_db)):
    releases = db.query(Release).filter(Release.app_name == req.name).all()
    version = len(releases) + 1
    image = build_and_push(req.repo_url, req.name, version)
    env_vars = get_env_vars(req.name, db)
    port = run_container(req.name, image, env_vars)
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
    all_apps = db.query(App).filter(App.status == "running").all()
    update_caddyfile([{"name": a.name, "port": a.port} for a in all_apps])
    audit("deploy", req.name, {"version": version, "port": port, "image": image})
    return {"status": "deployed", "app": req.name, "port": port, "version": version}

# ── LIST + GET ───────────────────────────────────────────
@app.get("/apps")
def list_apps(db: Session = Depends(get_db)):
    apps = db.query(App).all()
    return [{"name": a.name, "status": a.status, "port": a.port} for a in apps]

@app.get("/apps/{name}")
def get_app(name: str, db: Session = Depends(get_db)):
    a = db.query(App).filter(App.name == name).first()
    if not a:
        raise HTTPException(404, "App not found")
    return {"name": a.name, "status": get_container_status(name),
            "port": a.port, "image": a.image, "replicas": a.replicas}

# ── CONFIG ───────────────────────────────────────────────
@app.put("/apps/{name}/config")
def set_config(name: str, req: ConfigRequest, db: Session = Depends(get_db)):
    encrypted = fernet.encrypt(req.value.encode()).decode()
    row = db.query(EnvVar).filter(
        EnvVar.app_name == name, EnvVar.key == req.key).first()
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

@app.delete("/apps/{name}/config/{key}")
def delete_config(name: str, key: str, db: Session = Depends(get_db)):
    row = db.query(EnvVar).filter(
        EnvVar.app_name == name, EnvVar.key == key).first()
    if not row:
        raise HTTPException(404, "Key not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "key": key}

# ── LOGS STREAMING ───────────────────────────────────────
@app.get("/apps/{name}/logs")
def stream_logs(name: str, follow: bool = False, tail: int = 50):
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
def get_metrics(name: str):
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
def scale(name: str, req: ScaleRequest, db: Session = Depends(get_db)):
    a = db.query(App).filter(App.name == name).first()
    if not a:
        raise HTTPException(404, "App not found")
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
        docker_client.containers.run(
            a.image,
            name=container_name,
            detach=True,
            ports={"8000/tcp": port},
            environment=env_vars,
            mem_limit="256m",
            nano_cpus=250_000_000,
            restart_policy={"Name": "on-failure", "MaximumRetryCount": 3}
        )
        ports.append(port)
    a.replicas = req.replicas
    db.commit()
    update_caddyfile_replicas(name, ports)
    audit("scale", name, {"replicas": req.replicas, "ports": ports})
    return {"status": "scaled", "app": name, "replicas": req.replicas, "ports": ports}

# ── RESTART ──────────────────────────────────────────────
@app.post("/apps/{name}/restart")
def restart(name: str, db: Session = Depends(get_db)):
    a = db.query(App).filter(App.name == name).first()
    if not a:
        raise HTTPException(404, "App not found")
    env_vars = get_env_vars(name, db)
    port = run_container(name, a.image, env_vars, a.port)
    audit("restart", name, {"port": port})
    return {"status": "restarted", "app": name, "port": port}

# ── STOP ─────────────────────────────────────────────────
@app.post("/apps/{name}/stop")
def stop(name: str, db: Session = Depends(get_db)):
    stop_container(name)
    a = db.query(App).filter(App.name == name).first()
    if a:
        a.status = "stopped"
        db.commit()
    audit("stop", name, {})
    return {"status": "stopped", "app": name}

# ── RELEASES ─────────────────────────────────────────────
@app.get("/apps/{name}/releases")
def get_releases(name: str, db: Session = Depends(get_db)):
    releases = db.query(Release).filter(Release.app_name == name).all()
    return [{"version": r.version, "image": r.image,
             "deployed_at": str(r.deployed_at)} for r in releases]

# ── ROLLBACK ─────────────────────────────────────────────
@app.post("/apps/{name}/rollback")
def rollback(name: str, version: int, db: Session = Depends(get_db)):
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
    all_apps = db.query(App).filter(App.status == "running").all()
    update_caddyfile([{"name": ap.name, "port": ap.port} for ap in all_apps])
    return {"status": "rolled back", "app": name, "version": version, "port": port}

# ── PS ───────────────────────────────────────────────────
@app.get("/apps/{name}/ps")
def ps(name: str):
    containers = docker_client.containers.list(
        filters={"name": f"app-{name}"})
    return [{"name": c.name, "status": c.status,
             "ports": c.ports} for c in containers]

# ── WEB UI ───────────────────────────────────────────────
from api.ui import router as ui_router
app.include_router(ui_router)

@app.get("/")
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui/")

# ── AUDIT LOG ────────────────────────────────────────────
import json as _json
from db.models import AuditLog

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
def get_audit_log(limit: int = 50, db: Session = Depends(get_db)):
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
def get_app_audit(app_name: str, db: Session = Depends(get_db)):
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
def deploy_zero_downtime(name: str, db: Session = Depends(get_db)):
    """Blue-green deploy — nouvelle version sans coupure"""
    a = db.query(App).filter(App.name == name).first()
    if not a:
        raise HTTPException(404, "App not found")

    # Récupérer la dernière release
    latest = db.query(Release).filter(
        Release.app_name == name
    ).order_by(Release.version.desc()).first()
    if not latest:
        raise HTTPException(404, "No releases found")

    env_vars = get_env_vars(name, db)

    # 1. Lancer le nouveau container (green) sur un nouveau port
    green_port = get_free_port()
    green_name = f"app-{name}-green"
    try:
        old = docker_client.containers.get(green_name)
        old.stop(); old.remove()
    except:
        pass

    docker_client.containers.run(
        latest.image,
        name=green_name,
        detach=True,
        ports={"8000/tcp": green_port},
        environment=env_vars,
        mem_limit="512m",
        nano_cpus=500_000_000,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 3}
    )
    print(f"[blue-green] Green container started on port {green_port}")

    # 2. Health check du nouveau container (max 30s)
    import time as _time
    import requests as _requests
    healthy = False
    for i in range(15):
        _time.sleep(2)
        try:
            r = _requests.get(f"http://localhost:{green_port}", timeout=2)
            if r.status_code < 500:
                healthy = True
                print(f"[blue-green] Green healthy after {(i+1)*2}s")
                break
        except:
            print(f"[blue-green] Waiting for green... ({(i+1)*2}s)")

    if not healthy:
        # Rollback — stopper le green et garder le blue
        try:
            docker_client.containers.get(green_name).stop()
            docker_client.containers.get(green_name).remove()
        except:
            pass
        audit("deploy-zero-downtime", name, {"error": "green unhealthy"}, "error")
        raise HTTPException(500, "New version failed health check — keeping old version")

    # 3. Basculer Caddy vers le green
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

    # Mettre à jour Caddy avec le nouveau port
    a.port = green_port
    db.commit()
    all_apps = db.query(App).filter(App.status == "running").all()
    update_caddyfile([{"name": ap.name, "port": ap.port} for ap in all_apps])

    # 4. Stopper l'ancien container (blue) après la bascule
    _time.sleep(2)
    try:
        blue = docker_client.containers.get(old_name)
        blue.stop()
        blue.remove()
        print(f"[blue-green] Blue container stopped")
    except:
        pass

    audit("deploy-zero-downtime", name, {
        "old_port": old_port,
        "new_port": green_port,
        "image": latest.image
    })

    return {
        "status": "deployed",
        "strategy": "blue-green",
        "app": name,
        "old_port": old_port,
        "new_port": green_port,
        "downtime": "0s"
    }
