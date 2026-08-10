import pytest, requests, time

API = "http://localhost:8000"
APP_NAME = f"e2e-{int(time.time())}"  # app unique par run (isolation multi-user)
REPO_URL = "/opt/git-repos/hello-world.git"
EMAIL = "e2e@test.local"
PASSWORD = "e2epassword"

def setup_module():
    """Crée un utilisateur E2E + token (auth requise par l'API)."""
    r = requests.post(f"{API}/auth/register",
                      json={"email": EMAIL, "password": PASSWORD})
    if r.status_code != 200:
        assert r.status_code == 409, r.text  # déjà enregistré → ok
    r = requests.post(f"{API}/auth/login",
                      json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    global H
    H = {"Authorization": f"Bearer {r.json()['token']}"}

def test_api_health():
    r = requests.get(f"{API}/apps", headers=H)
    assert r.status_code == 200
    print("✅ API health OK")

def test_deploy():
    r = requests.post(f"{API}/apps/deploy",
        json={"name": APP_NAME, "repo_url": REPO_URL}, headers=H)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "deployed"
    print(f"✅ Deploy OK — v{data['version']} port {data['port']}")

def test_app_responds():
    time.sleep(2)
    r = requests.get(f"{API}/apps/{APP_NAME}", headers=H)
    port = r.json()["port"]
    app_r = requests.get(f"http://localhost:{port}")
    assert app_r.status_code == 200
    print(f"✅ App responds on port {port}")

def test_config_set():
    r = requests.put(f"{API}/apps/{APP_NAME}/config",
        json={"key": "TEST_KEY", "value": "secret123"}, headers=H)
    assert r.status_code == 200
    print("✅ Config set OK")

def test_config_masked():
    r = requests.get(f"{API}/apps/{APP_NAME}/config", headers=H)
    assert r.json()["TEST_KEY"] == "***"
    print("✅ Config masked OK")

def test_metrics():
    r = requests.get(f"{API}/apps/{APP_NAME}/metrics", headers=H)
    assert r.status_code == 200
    data = r.json()
    assert "cpu_percent" in data
    print(f"✅ Metrics OK — CPU {data['cpu_percent']}%")

def test_scale():
    r = requests.post(f"{API}/apps/{APP_NAME}/scale",
        json={"replicas": 2}, headers=H)
    assert r.status_code == 200
    assert r.json()["replicas"] == 2
    print("✅ Scale OK — 2 replicas")

def test_releases():
    r = requests.get(f"{API}/apps/{APP_NAME}/releases", headers=H)
    assert len(r.json()) >= 1
    print(f"✅ Releases OK")

def test_https():
    r = requests.get("https://hello-world.68.221.16.224.sslip.io", timeout=10)
    assert r.status_code == 200
    print("✅ HTTPS OK")

def test_restart():
    r = requests.post(f"{API}/apps/{APP_NAME}/restart", headers=H)
    assert r.status_code == 200
    print("✅ Restart OK")

def test_auth_required():
    # sans token → 401
    r = requests.get(f"{API}/apps")
    assert r.status_code == 401
    print("✅ Auth required OK")

def test_custom_domain():
    r = requests.post(f"{API}/apps/{APP_NAME}/domains",
        json={"domain": f"{APP_NAME}.example.com"}, headers=H)
    assert r.status_code == 200, r.text
    domains = requests.get(f"{API}/apps/{APP_NAME}/domains", headers=H).json()
    assert f"{APP_NAME}.example.com" in domains
    requests.delete(f"{API}/apps/{APP_NAME}/domains/{APP_NAME}.example.com",
                    headers=H)
    print("✅ Custom domain OK")

def test_stop():
    r = requests.post(f"{API}/apps/{APP_NAME}/stop", headers=H)
    assert r.json()["status"] == "stopped"
    print("✅ Stop OK")
