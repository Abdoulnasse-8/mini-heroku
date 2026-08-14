import json
import pytest
from fastapi.testclient import TestClient

from db.models import (init_db, SessionLocal, App, User, Release, EnvVar,
                       CustomDomain, AuditLog, Addon, AppAddon)

init_db()
from api.main import app, login_limiter, register_limiter


@pytest.fixture()
def client():
    c = TestClient(app)
    yield c
    db = SessionLocal()
    for table in (AuditLog, CustomDomain, EnvVar, Release, App, User,
                  Addon, AppAddon):
        db.query(table).delete()
    db.commit()
    db.close()
    login_limiter.clear()
    register_limiter.clear()


def register(client, email="alice@example.com", password="supersecret"):
    r = client.post("/auth/register",
                    json={"email": email, "password": password})
    assert r.status_code == 200, r.json()
    return r.json()["token"]


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


class _FakeContainers:
    def run(self, *a, **k):
        return None

    def get(self, name):
        import docker as docker_sdk
        raise docker_sdk.errors.NotFound(f"{name} not found")

    def list(self, *a, **k):
        return []


class _FakeClient:
    containers = _FakeContainers()


class _FakeRunning:
    def __init__(self, stats):
        self.stats = stats

    def stop(self):
        pass

    def remove(self):
        self.stats["removed"] += 1


class _FakeContainersTracked:
    def __init__(self, stats):
        self.stats = stats
        self.running = {}
        self.started = []

    def run(self, *a, **k):
        name = k.get("name")
        if name:
            self.running[name] = _FakeRunning(self.stats)
            self.started.append(name)
        return None

    def get(self, name):
        import docker as docker_sdk
        if name in self.running:
            return self.running[name]
        raise docker_sdk.errors.NotFound(f"{name} not found")

    def list(self, *a, **k):
        return []


class _FakeClientTracked:
    def __init__(self, containers):
        self.containers = containers


def _fake_docker(monkeypatch):
    import api.main as m
    monkeypatch.setattr("api.main._ensure_addon_network", lambda *a, **k: None)
    monkeypatch.setattr("api.main.docker_client", _FakeClient())
    monkeypatch.setattr("api.main.run_container", lambda n, im, ev, p=None: 3001)
    monkeypatch.setattr("api.main.wait_healthy", lambda p, timeout=30: True)


# ── CADDYFILE (reconstruction propre) ────────────────────
def test_caddyfile_rendering(monkeypatch, tmp_path):
    import proxy.caddy as caddy
    caddy.CADDYFILE = str(tmp_path / "Caddyfile")
    apps = [
        {"name": "web", "port": 3001, "domains": []},
        {"name": "api", "port": 3002, "ports": [3101, 3102],
         "domains": ["api.example.com"]},
    ]
    caddy.update_caddyfile(apps)
    content = open(caddy.CADDYFILE).read()
    assert "web.68.221.16.224.sslip.io" in content
    assert "reverse_proxy localhost:3001" in content
    assert "api.example.com" in content
    assert "reverse_proxy localhost:3101 localhost:3102" in content


# ── SCALING (replica_ports persistés + Caddy propre) ─────
def test_scale_stores_replica_ports(client, monkeypatch):
    _fake_docker(monkeypatch)
    tok = register(client)
    db = SessionLocal()
    db.add(App(name="my-app", owner_email="alice@example.com",
               status="running", port=3001, image="x:v1"))
    db.commit()
    db.close()
    r = client.post("/apps/my-app/scale", json={"replicas": 2}, headers=hdr(tok))
    assert r.status_code == 200, r.text
    assert r.json()["replicas"] == 2
    db = SessionLocal()
    a = db.query(App).filter(App.name == "my-app").first()
    ports = json.loads(a.replica_ports)
    assert len(ports) == 2
    db.close()
    # scale à 0 → replica_ports vide
    r = client.post("/apps/my-app/scale", json={"replicas": 0}, headers=hdr(tok))
    assert r.status_code == 200
    db = SessionLocal()
    a = db.query(App).filter(App.name == "my-app").first()
    assert a.replica_ports is None
    db.close()


# ── ENV VARS : erreur de déchiffrement → échec franc (500) ─
def test_bad_encrypted_env_var_fails_loudly(client, monkeypatch):
    _fake_docker(monkeypatch)
    tok = register(client)
    db = SessionLocal()
    db.add(App(name="my-app", owner_email="alice@example.com",
               status="running", port=3001, image="x:v1"))
    db.add(EnvVar(app_name="my-app", key="SECRET", value="not-encrypted-garbage"))
    db.commit()
    db.close()
    r = client.post("/apps/my-app/restart", headers=hdr(tok))
    assert r.status_code == 500
    assert "decrypt" in r.json()["detail"].lower()


# ── STOP : arrête le main ET tous les réplicas ────────────
def test_stop_removes_main_and_replicas(client, monkeypatch):
    stats = {"removed": 0}
    fc = _FakeContainersTracked(stats)
    for i in range(3):
        fc.running[f"app-my-app-replica-{i}"] = _FakeRunning(stats)
    removed_main = []
    monkeypatch.setattr("api.main.docker_client", _FakeClientTracked(fc))
    monkeypatch.setattr("api.main.stop_container", lambda n: removed_main.append(n))
    tok = register(client)
    db = SessionLocal()
    db.add(App(name="my-app", owner_email="alice@example.com",
               status="running", port=3001, image="x:v1"))
    db.commit()
    db.close()
    r = client.post("/apps/my-app/stop", headers=hdr(tok))
    assert r.status_code == 200, r.text
    assert removed_main == ["my-app"]
    assert stats["removed"] == 3
    db = SessionLocal()
    a = db.query(App).filter(App.name == "my-app").first()
    assert a.status == "stopped"
    db.close()


# ── RESTART : restaure les réplicas d'une app scalée ─────
def test_restart_restores_replicas(client, monkeypatch):
    stats = {"removed": 0}
    fc = _FakeContainersTracked(stats)
    monkeypatch.setattr("api.main._ensure_addon_network", lambda *a, **k: None)
    monkeypatch.setattr("api.main.run_container", lambda n, im, ev, p=None: 3001)
    monkeypatch.setattr("api.main.wait_healthy", lambda p, timeout=30: True)
    monkeypatch.setattr("api.main.docker_client", _FakeClientTracked(fc))
    tok = register(client)
    db = SessionLocal()
    db.add(App(name="my-app", owner_email="alice@example.com",
               status="stopped", port=3001, image="x:v1",
               replica_ports=json.dumps([3101])))
    db.commit()
    db.close()
    r = client.post("/apps/my-app/restart", headers=hdr(tok))
    assert r.status_code == 200, r.text
    assert r.json()["replicas"] == 1
    assert "app-my-app-replica-0" in fc.started
    db = SessionLocal()
    a = db.query(App).filter(App.name == "my-app").first()
    assert a.replica_ports is not None
    db.close()


# ── PRODUCTION : /docs désactivé ─────────────────────────
def test_docs_available_in_dev():
    # en dev (env de test), /docs est accessible
    r = TestClient(app).get("/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()


# ── MIGRATION : hasher les tokens legacy en clair ─────────
def test_migrate_hashes_legacy_tokens(client):
    import hashlib
    from db.models import _migrate
    db = SessionLocal()
    db.add(User(email="legacy@x.com", password="x", token="legacy-plaintext-token"))
    db.commit()
    db.close()
    _migrate()
    db = SessionLocal()
    u = db.query(User).filter(User.email == "legacy@x.com").first()
    assert u.token.startswith("sha256$")
    assert u.token == "sha256$" + hashlib.sha256(b"legacy-plaintext-token").hexdigest()
    db.close()