import pytest
from fastapi.testclient import TestClient

from db.models import (init_db, SessionLocal, App, User, Release, EnvVar,
                       CustomDomain, AuditLog)

init_db()
from api.main import app


@pytest.fixture()
def client():
    c = TestClient(app)
    yield c
    # reset complet entre les tests
    db = SessionLocal()
    for table in (AuditLog, CustomDomain, EnvVar, Release, App, User):
        db.query(table).delete()
    db.commit()
    db.close()


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
    assert r.status_code == 200 and r.json()["token"] == tok


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
