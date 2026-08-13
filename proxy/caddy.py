import subprocess
import os

import config

CADDYFILE = config.CADDYFILE
BASE_DOMAIN = config.BASE_DOMAIN

def _reload():
    if os.environ.get("MINIHEROKU_CADDY_RELOAD", "1") != "0":
        subprocess.run(["sudo", "/usr/bin/systemctl", "reload", "caddy"],
                       check=True)

def update_caddyfile(apps: list[dict]):
    """Reconstruit intégralement le Caddyfile à partir de l'état connu.

    apps = [{"name": "myapp", "port": 3001, "domains": [...], "ports": [...]}, ...]
    - "ports" (optionnel) : liste de ports pour le load-balancing (scale > 1).
      S'il est présent et non vide, il remplace "port".
    - Caddy exige une virgule entre plusieurs hostnames d'un même site.
    """
    blocks = []
    for app in apps:
        hostnames = [f"{app['name']}.{BASE_DOMAIN}"]
        hostnames += app.get("domains", [])
        site_line = ", ".join(hostnames)
        upstreams = app.get("ports") or [app["port"]]
        target = " ".join(f"localhost:{p}" for p in upstreams)
        block = f"{site_line} {{\n    reverse_proxy {target}\n}}\n"
        blocks.append(block)

    content = "\n".join(blocks) if blocks else "# no apps deployed\n"
    with open(CADDYFILE, "w") as f:
        f.write(content)
    _reload()
    print(f"[caddy] Updated Caddyfile with {len(apps)} apps")
