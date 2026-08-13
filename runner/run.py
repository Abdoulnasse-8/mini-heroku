import socket, time
import requests, docker

import config

client = docker.from_env()

def _ensure_addon_network():
    """Crée le réseau bridge reliant apps et add-ons (idempotent)."""
    try:
        client.networks.get(config.ADDON_NETWORK)
    except docker.errors.NotFound:
        client.networks.create(config.ADDON_NETWORK, driver="bridge")
        print(f"[runner] Created network {config.ADDON_NETWORK}")

def wait_healthy(port: int, timeout: int = None) -> bool:
    """Poll http://localhost:port until it answers with status < 500, or timeout."""
    if timeout is None:
        timeout = config.HEALTH_TIMEOUT
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"http://localhost:{port}", timeout=2)
            if r.status_code < 500:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)
    return False

def get_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def run_container(app_name: str, image: str, env_vars: dict, port: int = None) -> int:
    if port is None:
        port = get_free_port()
    container_name = f"app-{app_name}"
    try:
        old = client.containers.get(container_name)
        old.stop()
        old.remove()
    except:
        pass
    _ensure_addon_network()
    client.containers.run(
        image,
        name=container_name,
        detach=True,
        network=config.ADDON_NETWORK,
        ports={f"{config.CONTAINER_PORT}/tcp": (config.APP_BIND_HOST, port)},
        environment=env_vars,
        mem_limit="512m",
        nano_cpus=500_000_000,
        restart_policy={"Name": "unless-stopped"},
    )
    print(f"[runner] Started {container_name} on port {port} (bind {config.APP_BIND_HOST})")
    return port

def stop_container(app_name: str):
    try:
        c = client.containers.get(f"app-{app_name}")
        c.stop()
        c.remove()
    except Exception as e:
        print(f"[runner] {e}")

def get_container_status(app_name: str) -> str:
    try:
        return client.containers.get(f"app-{app_name}").status
    except:
        return "not found"