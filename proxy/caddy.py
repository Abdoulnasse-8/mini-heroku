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
