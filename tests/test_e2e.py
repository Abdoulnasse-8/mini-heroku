import pytest, requests, time

API = "http://localhost:8000"
APP_NAME = "test-e2e"
REPO_URL = "/opt/git-repos/hello-world.git"

def test_api_health():
    r = requests.get(f"{API}/apps")
    assert r.status_code == 200
    print("✅ API health OK")

def test_deploy():
    r = requests.post(f"{API}/apps/deploy",
        json={"name": APP_NAME, "repo_url": REPO_URL})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "deployed"
    print(f"✅ Deploy OK — v{data['version']} port {data['port']}")

def test_app_responds():
    time.sleep(2)
    r = requests.get(f"{API}/apps/{APP_NAME}")
    port = r.json()["port"]
    app_r = requests.get(f"http://localhost:{port}")
    assert app_r.status_code == 200
    print(f"✅ App responds on port {port}")

def test_config_set():
    r = requests.put(f"{API}/apps/{APP_NAME}/config",
        json={"key": "TEST_KEY", "value": "secret123"})
    assert r.status_code == 200
    print("✅ Config set OK")

def test_config_masked():
    r = requests.get(f"{API}/apps/{APP_NAME}/config")
    assert r.json()["TEST_KEY"] == "***"
    print("✅ Config masked OK")

def test_metrics():
    r = requests.get(f"{API}/apps/{APP_NAME}/metrics")
    assert r.status_code == 200
    data = r.json()
    assert "cpu_percent" in data
    print(f"✅ Metrics OK — CPU {data['cpu_percent']}%")

def test_scale():
    r = requests.post(f"{API}/apps/{APP_NAME}/scale",
        json={"replicas": 2})
    assert r.status_code == 200
    assert r.json()["replicas"] == 2
    print("✅ Scale OK — 2 replicas")

def test_releases():
    r = requests.get(f"{API}/apps/{APP_NAME}/releases")
    assert len(r.json()) >= 1
    print(f"✅ Releases OK")

def test_https():
    r = requests.get("https://hello-world.68.221.16.224.sslip.io", timeout=10)
    assert r.status_code == 200
    print("✅ HTTPS OK")

def test_restart():
    r = requests.post(f"{API}/apps/{APP_NAME}/restart")
    assert r.status_code == 200
    print("✅ Restart OK")

def test_stop():
    r = requests.post(f"{API}/apps/{APP_NAME}/stop")
    assert r.json()["status"] == "stopped"
    print("✅ Stop OK")
