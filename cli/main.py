#!/usr/bin/env python3
import click, requests, json, sys, os

API = "http://localhost:8000"
CONFIG_FILE = os.path.expanduser("~/.myplatform.json")

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)
    os.chmod(CONFIG_FILE, 0o600)

def auth_headers():
    cfg = load_config()
    token = cfg.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}

def api(method, path, **kwargs):
    kwargs.setdefault("headers", {}).update(auth_headers())
    try:
        r = getattr(requests, method)(f"{API}{path}", **kwargs)
        if r.status_code == 401:
            click.echo("Error: not authenticated — run 'myplatform login'", err=True)
            sys.exit(1)
        return r.json()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@click.group()
def cli():
    """myplatform — Mini Heroku CLI"""
    pass

# ── AUTH ─────────────────────────────────────────────────
@cli.command()
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def register(email, password):
    """Create an account"""
    r = api("post", "/auth/register", json={"email": email, "password": password})
    save_config({"email": r["email"], "token": r["token"]})
    click.echo(f"-----> Registered as {r['email']}")

@cli.command()
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True)
def login(email, password):
    """Log in and store your API token"""
    r = api("post", "/auth/login", json={"email": email, "password": password})
    save_config({"email": r["email"], "token": r["token"]})
    click.echo(f"-----> Logged in as {r['email']}")

@cli.command()
def logout():
    """Remove the stored API token"""
    save_config({})
    click.echo("-----> Logged out")

@cli.command()
def whoami():
    """Show the current logged-in user"""
    cfg = load_config()
    if not cfg.get("token"):
        click.echo("Not logged in — run 'myplatform login'")
        return
    r = api("get", "/auth/me")
    click.echo(f"Email: {r['email']}")
    click.echo(f"Registered: {r['created_at']}")

@cli.command()
@click.argument("name")
@click.argument("repo_url")
def deploy(name, repo_url):
    """Deploy an app from a git repo"""
    click.echo(f"-----> Deploying {name}...")
    r = api("post", "/apps/deploy",
            json={"name": name, "repo_url": repo_url})
    if r.get("status") == "deployed":
        click.echo(f"-----> Deploy successful!")
        click.echo(f"-----> Version: v{r['version']}")
        click.echo(f"-----> URL: https://{name}.68.221.16.224.sslip.io")
    else:
        click.echo(f"-----> Deploy failed: {r}", err=True)
        sys.exit(1)

@cli.command()
@click.argument("name")
@click.option("-f", "--follow", is_flag=True, help="Stream logs")
@click.option("-n", "--tail", default=50, help="Number of lines")
def logs(name, follow, tail):
    """Stream logs from an app"""
    import urllib.request
    url = f"{API}/apps/{name}/logs?follow={str(follow).lower()}&tail={tail}"
    try:
        with urllib.request.urlopen(url) as r:
            for line in r:
                decoded = line.decode().strip()
                if decoded.startswith("data: "):
                    click.echo(decoded[6:])
    except KeyboardInterrupt:
        pass
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@cli.command("config:set")
@click.argument("name")
@click.argument("kvpairs", nargs=-1)
def config_set(name, kvpairs):
    """Set env vars: myplatform config:set myapp KEY=VALUE"""
    for kv in kvpairs:
        if "=" not in kv:
            click.echo(f"Invalid format: {kv} (use KEY=VALUE)", err=True)
            continue
        key, value = kv.split("=", 1)
        r = api("put", f"/apps/{name}/config",
                json={"key": key, "value": value})
        click.echo(f"-----> Set {key}")

@cli.command("config:get")
@click.argument("name")
def config_get(name):
    """Get env vars for an app"""
    r = api("get", f"/apps/{name}/config")
    for k, v in r.items():
        click.echo(f"{k}={v}")

@cli.command("config:unset")
@click.argument("name")
@click.argument("key")
def config_unset(name, key):
    """Remove an env var"""
    r = api("delete", f"/apps/{name}/config/{key}")
    click.echo(f"-----> Unset {key}")

@cli.command()
@click.argument("name")
@click.argument("scale_spec")
def scale(name, scale_spec):
    """Scale an app: myplatform scale myapp web=3"""
    try:
        replicas = int(scale_spec.split("=")[1])
    except:
        click.echo("Format: web=N", err=True)
        sys.exit(1)
    r = api("post", f"/apps/{name}/scale", json={"replicas": replicas})
    click.echo(f"-----> Scaled {name} to {replicas} replicas")
    click.echo(f"-----> Ports: {r.get('ports', [])}")

@cli.command()
@click.argument("name")
def restart(name):
    """Restart an app"""
    r = api("post", f"/apps/{name}/restart")
    click.echo(f"-----> Restarted {name}")

@cli.command()
@click.argument("name")
def ps(name):
    """List running containers for an app"""
    r = api("get", f"/apps/{name}/ps")
    for c in r:
        click.echo(f"{c['name']}\t{c['status']}")

@cli.command()
@click.argument("name")
def info(name):
    """Show app details"""
    r = api("get", f"/apps/{name}")
    click.echo(f"App:      {r['name']}")
    click.echo(f"Status:   {r['status']}")
    click.echo(f"Port:     {r['port']}")
    click.echo(f"Replicas: {r.get('replicas', 1)}")
    click.echo(f"Image:    {r['image']}")
    click.echo(f"URL:      https://{r['name']}.68.221.16.224.sslip.io")

@cli.command()
@click.argument("name")
def releases(name):
    """List releases for an app"""
    r = api("get", f"/apps/{name}/releases")
    for rel in r:
        click.echo(f"v{rel['version']}\t{rel['deployed_at']}\t{rel['image']}")

@cli.command()
@click.argument("name")
@click.argument("version", type=int)
def rollback(name, version):
    """Rollback to a previous release"""
    click.echo(f"-----> Rolling back {name} to v{version}...")
    r = api("post", f"/apps/{name}/rollback?version={version}")
    click.echo(f"-----> Rolled back to v{version}")

@cli.command("metrics")
@click.argument("name")
def metrics(name):
    """Show CPU and memory metrics"""
    r = api("get", f"/apps/{name}/metrics")
    click.echo(f"CPU:    {r['cpu_percent']}%")
    click.echo(f"Memory: {r['memory_mb']}MB / {r['memory_limit_mb']}MB ({r['memory_percent']}%)")

@cli.command("list")
def list_apps():
    """List all apps"""
    r = api("get", "/apps")
    if not r:
        click.echo("No apps deployed.")
        return
    for a in r:
        click.echo(f"{a['name']}\t{a['status']}\tport:{a['port']}")

# ── CUSTOM DOMAINS ───────────────────────────────────────
@cli.command("domains")
@click.argument("name")
def domains(name):
    """List custom domains for an app"""
    r = api("get", f"/apps/{name}/domains")
    for d in r:
        click.echo(d)

@cli.command("domains:add")
@click.argument("name")
@click.argument("domain")
def domains_add(name, domain):
    """Attach a custom domain to an app (point DNS A/AAAA to the VM IP first)"""
    r = api("post", f"/apps/{name}/domains", json={"domain": domain})
    click.echo(f"-----> Domain {domain} added to {name}")
    click.echo(f"-----> Point DNS: {domain} -> 68.221.16.224 (Let's Encrypt auto)")

@cli.command("domains:remove")
@click.argument("name")
@click.argument("domain")
def domains_remove(name, domain):
    """Remove a custom domain"""
    r = api("delete", f"/apps/{name}/domains/{domain}")
    click.echo(f"-----> Domain {domain} removed from {name}")


@cli.command("deploy:zero-downtime")
@click.argument("name")
def deploy_zero_downtime(name):
    """Zero-downtime blue-green deploy"""
    click.echo(f"-----> Starting blue-green deploy for {name}...")
    r = api("post", f"/apps/{name}/deploy-zero-downtime")
    if r.get("status") == "deployed":
        click.echo(f"-----> Blue-green deploy successful!")
        click.echo(f"-----> Old port: {r['old_port']} -> New port: {r['new_port']}")
        click.echo(f"-----> Downtime: {r['downtime']}")
        click.echo(f"-----> URL: https://{name}.68.221.16.224.sslip.io")
    else:
        click.echo(f"-----> Deploy failed: {r}", err=True)

if __name__ == "__main__":
    cli()
