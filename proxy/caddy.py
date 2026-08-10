import subprocess
import os

CADDYFILE = os.environ.get("MINIHEROKU_CADDYFILE", "/etc/caddy/Caddyfile")
BASE_DOMAIN = os.environ.get("MINIHEROKU_BASE_DOMAIN", "68.221.16.224.sslip.io")

def _reload():
    if os.environ.get("MINIHEROKU_CADDY_RELOAD", "1") != "0":
        subprocess.run(["sudo", "/usr/bin/systemctl", "reload", "caddy"],
                       check=True)

def update_caddyfile(apps: list[dict]):
    """apps = [{"name": "myapp", "port": 3001, "domains": ["app.example.com"]}, ...]"""
    blocks = []
    for app in apps:
        hostnames = [f"{app['name']}.{BASE_DOMAIN}"]
        hostnames += app.get("domains", [])
        # Caddy exige une virgule entre plusieurs hostnames d'un même site
        site_line = ", ".join(hostnames)
        block = f"""
{site_line} {{
    reverse_proxy localhost:{app['port']}
}}
"""
        blocks.append(block)

    content = "\n".join(blocks) if blocks else "# no apps deployed\n"
    with open(CADDYFILE, "w") as f:
        f.write(content)
    _reload()
    print(f"[caddy] Updated with {len(apps)} apps")

def update_caddyfile_replicas(app_name: str, ports: list[int], domains: list[str] = None):
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
    hostnames = [f"{app_name}.{BASE_DOMAIN}"]
    hostnames += domains or []
    site_line = ", ".join(hostnames)
    new_block = f"""
{site_line} {{
    reverse_proxy {upstreams}
}}
"""
    new_content = "\n".join(new_lines) + new_block

    with open(CADDYFILE, "w") as f:
        f.write(new_content)
    _reload()
    print(f"[caddy] Updated {app_name} with {len(ports)} replicas: {ports}")
