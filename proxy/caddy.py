import subprocess

CADDYFILE = "/etc/caddy/Caddyfile"
BASE_DOMAIN = "68.221.16.224.sslip.io"

def update_caddyfile(apps: list[dict]):
    """apps = [{"name": "myapp", "port": 3001}, ...]"""
    blocks = []
    for app in apps:
        block = f"""
{app['name']}.{BASE_DOMAIN} {{
    reverse_proxy localhost:{app['port']}
}}
"""
        blocks.append(block)

    content = "\n".join(blocks) if blocks else "# no apps deployed\n"
    with open(CADDYFILE, "w") as f:
        f.write(content)
    subprocess.run(["sudo", "/usr/bin/systemctl", "reload", "caddy"], check=True)
    print(f"[caddy] Updated with {len(apps)} apps")

def update_caddyfile_replicas(app_name: str, ports: list[int]):
    """Load balance across multiple replicas"""
    upstreams = " ".join([f"localhost:{p}" for p in ports])
    
    # Lire le Caddyfile existant
    try:
        with open(CADDYFILE, "r") as f:
            content = f.read()
    except:
        content = ""

    # Supprimer le bloc existant pour cette app
    lines = content.split("\n")
    new_lines = []
    skip = False
    depth = 0
    for line in lines:
        if f"{app_name}.{BASE_DOMAIN}" in line:
            skip = True
            depth = 0
        if skip:
            depth += line.count("{") - line.count("}")
            if depth <= 0 and "{" in content.split(f"{app_name}.{BASE_DOMAIN}")[1][:100]:
                skip = False
            continue
        new_lines.append(line)

    # Ajouter le nouveau bloc avec load balancing
    new_block = f"""
{app_name}.{BASE_DOMAIN} {{
    reverse_proxy {upstreams}
}}
"""
    new_content = "\n".join(new_lines) + new_block

    with open(CADDYFILE, "w") as f:
        f.write(new_content)
    subprocess.run(["sudo", "/usr/bin/systemctl", "reload", "caddy"], check=True)
    print(f"[caddy] Updated {app_name} with {len(ports)} replicas: {ports}")
