import socket, docker

client = docker.from_env()

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
    client.containers.run(
        image,
        name=container_name,
        detach=True,
        ports={"8000/tcp": port},
        environment=env_vars,
        mem_limit="512m",
        nano_cpus=500_000_000,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
    )
    print(f"[runner] Started {container_name} on port {port}")
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
