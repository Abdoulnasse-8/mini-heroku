import datetime
import os
import sqlite3
import pytest
from fastapi.testclient import TestClient

import docker as docker_sdk

from db.models import (init_db, SessionLocal, App, User, Release, EnvVar,
                       CustomDomain, AuditLog, Addon, AppAddon)

init_db()
from api.main import app, login_limiter, register_limiter


@pytest.fixture()
def client():
    c = TestClient(app)
    yield c
    # reset complet entre les tests
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


# ── AUTH ─────────────────────────────────────────────────
def test_api_requires_auth(client):
    for path in ("/apps", "/apps/x", "/audit", "/apps/x/logs"):
        assert client.get(path).status_code == 401, path
    assert client.post("/apps/deploy", json={}).status_code == 401


def test_register_and_login(client):
    tok = register(client)
    assert len(tok) >= 20
    r = client.post("/auth/login",
                    json={"email": "alice@example.com", "password": "supersecret"})
    assert r.status_code == 200
    # chaque login émet un NOUVEAU token (rotation) — l'ancien est invalidé
    new_tok = r.json()["token"]
    assert new_tok and new_tok != tok
    assert client.get("/auth/me", headers=hdr(tok)).status_code == 401
    assert client.get("/auth/me", headers=hdr(new_tok)).status_code == 200


def test_duplicate_email_rejected(client):
    register(client)
    r = client.post("/auth/register",
                    json={"email": "alice@example.com", "password": "supersecret"})
    assert r.status_code == 409


def test_bad_login_rejected(client):
    register(client)
    r = client.post("/auth/login",
                    json={"email": "alice@example.com", "password": "wrong"})
    assert r.status_code == 401


def test_short_password_rejected(client):
    r = client.post("/auth/register", json={"email": "x@x.com", "password": "short"})
    assert r.status_code == 400


def test_invalid_email_rejected(client):
    r = client.post("/auth/register", json={"email": "notanemail", "password": "longenough"})
    assert r.status_code == 400


def test_me(client):
    tok = register(client)
    r = client.get("/auth/me", headers=hdr(tok))
    assert r.json()["email"] == "alice@example.com"


def test_invalid_token_rejected(client):
    r = client.get("/auth/me", headers=hdr("bogus-token"))
    assert r.status_code == 401


# ── OWNERSHIP ────────────────────────────────────────────
def test_owner_sees_only_own_apps(client):
    tok_a = register(client, "alice@example.com")
    register(client, "bob@example.com", "bobpass123")
    tok_b = client.post("/auth/login",
                        json={"email": "bob@example.com", "password": "bobpass123"}
                        ).json()["token"]

    db = SessionLocal()
    db.add(App(name="alice-app", owner_email="alice@example.com",
               status="running", port=3001, image="x:v1"))
    db.commit()
    db.close()

    names = [a["name"] for a in client.get("/apps", headers=hdr(tok_a)).json()]
    assert names == ["alice-app"]
    assert client.get("/apps", headers=hdr(tok_b)).json() == []

    assert client.get("/apps/alice-app", headers=hdr(tok_b)).status_code == 403
    assert client.post("/apps/alice-app/stop", headers=hdr(tok_b)).status_code == 403
    assert client.get("/apps/alice-app", headers=hdr(tok_a)).status_code == 200
    assert client.get("/apps/nope", headers=hdr(tok_a)).status_code == 404


def test_register_adopts_legacy_apps(client):
    db = SessionLocal()
    db.add(App(name="legacy", owner_email=None, status="stopped"))
    db.commit()
    db.close()
    tok = register(client)
    names = [a["name"] for a in client.get("/apps", headers=hdr(tok)).json()]
    assert names == ["legacy"]


# ── VALIDATION ───────────────────────────────────────────
def test_invalid_app_name_rejected_before_build(client):
    tok = register(client)
    r = client.post("/apps/deploy", json={"name": "BAD NAME!",
                                          "repo_url": "https://github.com/a/b"},
                    headers=hdr(tok))
    assert r.status_code == 400


def test_non_https_repo_rejected_before_build(client):
    tok = register(client)
    for url in ("ssh://x/y.git", "git://x/y.git", "file:///x", "../rel", "http://x/y"):
        r = client.post("/apps/deploy", json={"name": "my-app", "repo_url": url},
                        headers=hdr(tok))
        assert r.status_code == 400, url


def test_local_repo_allowed(client):
    tok = register(client)
    r = client.post("/apps/deploy", json={"name": "my-app",
                                          "repo_url": "/opt/git-repos/x.git"},
                    headers=hdr(tok))
    # le build échoue en local (pas d'infra) mais proprement -> 502
    assert r.status_code == 502


# ── CUSTOM DOMAINS ───────────────────────────────────────
def test_domain_crud(client):
    tok = register(client)
    db = SessionLocal()
    db.add(App(name="my-app", owner_email="alice@example.com",
               repo_url="/opt/git-repos/x.git", status="running",
               port=3001, image="x:v1"))
    db.commit()
    db.close()

    assert client.get("/apps/my-app/domains", headers=hdr(tok)).json() == []
    r = client.post("/apps/my-app/domains", json={"domain": "demo.example.com"},
                    headers=hdr(tok))
    assert r.status_code == 200
    assert client.get("/apps/my-app/domains", headers=hdr(tok)).json() == \
        ["demo.example.com"]

    # doublon -> 409
    r = client.post("/apps/my-app/domains", json={"domain": "demo.example.com"},
                    headers=hdr(tok))
    assert r.status_code == 409

    # domaine invalide -> 400
    for bad in ("..", "a b", ".com", "x."):
        r = client.post("/apps/my-app/domains", json={"domain": bad},
                        headers=hdr(tok))
        assert r.status_code == 400, bad

    assert client.delete("/apps/my-app/domains/demo.example.com",
                         headers=hdr(tok)).status_code == 200
    assert client.get("/apps/my-app/domains", headers=hdr(tok)).json() == []


# ── TOKENS (hashés en base, rotation, expiration) ─────────
def test_token_stored_hashed(client):
    tok = register(client)
    db = SessionLocal()
    u = db.query(User).filter(User.email == "alice@example.com").first()
    stored = u.token
    db.close()
    assert stored.startswith("sha256$")
    assert tok not in stored  # jamais en clair
    assert client.get("/auth/me", headers=hdr(tok)).status_code == 200


def test_expired_token_rejected(client):
    tok = register(client)
    db = SessionLocal()
    u = db.query(User).filter(User.email == "alice@example.com").first()
    u.token_expires_at = datetime.datetime(2020, 1, 1)
    db.commit()
    db.close()
    assert client.get("/auth/me", headers=hdr(tok)).status_code == 401


def test_token_rotate_and_revoke(client):
    tok = register(client)
    r = client.post("/auth/rotate-token", headers=hdr(tok))
    assert r.status_code == 200, r.text
    new_tok = r.json()["token"]
    assert new_tok != tok
    assert r.json()["expires_at"]  # expiration définie (TTL configuré)
    assert client.get("/auth/me", headers=hdr(tok)).status_code == 401
    assert client.get("/auth/me", headers=hdr(new_tok)).status_code == 200
    # révocation immédiate
    assert client.post("/auth/revoke-token", headers=hdr(new_tok)).status_code == 200
    assert client.get("/auth/me", headers=hdr(new_tok)).status_code == 401


# ── RATE LIMITING ────────────────────────────────────────
def test_login_rate_limited(client):
    login_limiter.max_attempts = 3
    login_limiter.clear()
    try:
        register(client)
        for _ in range(3):
            r = client.post("/auth/login",
                            json={"email": "alice@example.com", "password": "wrong"})
            assert r.status_code == 401
        r = client.post("/auth/login",
                        json={"email": "alice@example.com", "password": "wrong"})
        assert r.status_code == 429
        assert "retry-after" in {k.lower() for k in r.headers}
    finally:
        login_limiter.max_attempts = 1000
        login_limiter.clear()


# ── CSRF (UI) ────────────────────────────────────────────
def test_ui_csrf_protected(client):
    # GET login page pose le cookie mh_csrf
    r = client.get("/ui/login")
    assert r.status_code == 200
    csrf = client.cookies.get("mh_csrf")
    assert csrf
    # POST /ui/login sans token CSRF → 403
    r = client.post("/ui/login", data={"email": "a@b.com", "password": "password123"})
    assert r.status_code == 403
    # avec le bon token, le middleware laisse passer (creds invalides → pas un 403)
    r = client.post("/ui/login", data={"email": "a@b.com", "password": "password123",
                                       "csrf_token": csrf})
    assert r.status_code != 403
    # la page d'erreur a tourné le cookie CSRF → on relit la valeur courante
    csrf = client.cookies.get("mh_csrf")
    # mutation UI sans header X-CSRF-Token → 403
    r = client.post("/ui/apps/x/stop")
    assert r.status_code == 403
    # avec header CSRF → le middleware passe, l'auth échoue (401)
    r = client.post("/ui/apps/x/stop", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 401


# ── ADD-ONS ──────────────────────────────────────────────
def _noop(*a, **k):
    return None


class _FakeContainers:
    def run(self, *a, **k):
        return None

    def get(self, name):
        raise docker_sdk.errors.NotFound(f"{name} not found")

    def list(self, *a, **k):
        return []


class _FakeClient:
    containers = _FakeContainers()


def _fake_docker(monkeypatch):
    monkeypatch.setattr("api.main._ensure_addon_network", _noop)
    monkeypatch.setattr("api.main.docker_client", _FakeClient())
    monkeypatch.setattr("api.main.run_container", lambda n, im, ev, p=None: 3001)
    monkeypatch.setattr("api.main.wait_healthy", lambda p, timeout=30: True)


def test_addon_validation(client):
    tok = register(client)
    r = client.post("/addons", json={"name": "mydb", "kind": "mysql"},
                    headers=hdr(tok))
    assert r.status_code == 400
    r = client.post("/addons", json={"name": "BAD NAME", "kind": "postgres"},
                    headers=hdr(tok))
    assert r.status_code == 400


def test_addon_crud_with_mocked_docker(client, monkeypatch):
    _fake_docker(monkeypatch)
    tok = register(client)
    r = client.post("/addons", json={"name": "mydb", "kind": "postgres"},
                    headers=hdr(tok))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "created" and data["kind"] == "postgres"
    assert data["url"].startswith("postgresql://postgres:")
    assert [a["name"] for a in client.get("/addons", headers=hdr(tok)).json()] == ["mydb"]
    # ownership : un autre user ne le voit pas / ne le détruit pas
    register(client, "bob@example.com", "bobpass123")
    tok_b = client.post("/auth/login",
                        json={"email": "bob@example.com", "password": "bobpass123"}
                        ).json()["token"]
    assert client.get("/addons", headers=hdr(tok_b)).json() == []
    assert client.delete("/addons/mydb", headers=hdr(tok_b)).status_code == 403
    # destroy
    assert client.delete("/addons/mydb", headers=hdr(tok)).status_code == 200
    assert client.get("/addons", headers=hdr(tok)).json() == []


def test_addon_attach_detach(client, monkeypatch):
    _fake_docker(monkeypatch)
    tok = register(client)
    assert client.post("/addons", json={"name": "mycache", "kind": "redis"},
                       headers=hdr(tok)).status_code == 200
    db = SessionLocal()
    db.add(App(name="my-app", owner_email="alice@example.com",
               repo_url="/opt/git-repos/x.git", status="running",
               port=3001, image="x:v1"))
    db.commit()
    db.close()
    # attach
    r = client.post("/apps/my-app/addons/mycache", headers=hdr(tok))
    assert r.status_code == 200, r.text
    assert r.json()["key"] == "REDIS_URL"
    cfg = client.get("/apps/my-app/config", headers=hdr(tok)).json()
    assert "REDIS_URL" in cfg
    assert client.get("/apps/my-app/addons", headers=hdr(tok)).json() == \
        [{"name": "mycache", "kind": "redis"}]
    # detach
    r = client.delete("/apps/my-app/addons/mycache", headers=hdr(tok))
    assert r.status_code == 200
    assert "REDIS_URL" not in client.get("/apps/my-app/config", headers=hdr(tok)).json()
    assert client.get("/apps/my-app/addons", headers=hdr(tok)).json() == []


# ── BACKUP ────────────────────────────────────────────────
def test_backup_script(tmp_path, monkeypatch):
    import scripts.backup as backup_mod
    monkeypatch.setattr(backup_mod.config, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(backup_mod.config, "BACKUP_KEEP", "2")
    # DB de test avec des données
    db = SessionLocal()
    db.add(User(email="bak@test.local", password="x",
                token="sha256$abc"))
    db.commit()
    db.close()
    db_path = backup_mod.config.DATABASE_URL.replace("sqlite:///", "")
    monkeypatch.setattr(backup_mod.config, "DATABASE_URL", f"sqlite:///{db_path}")
    dest = backup_mod.backup()
    assert os.path.exists(os.path.join(dest, "mini-heroku.db"))
    # restauration lisible
    conn = sqlite3.connect(os.path.join(dest, "mini-heroku.db"))
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
    conn.close()
