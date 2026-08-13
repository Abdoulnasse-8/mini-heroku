<div align="center">

# ⚡ Mini Heroku

### A self-hosted PaaS platform — git push → HTTPS in under 2 minutes

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green?logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-24+-blue?logo=docker)
![Caddy](https://img.shields.io/badge/Caddy-2.11-orange)
![Tests](https://img.shields.io/badge/tests-27%2F27%20passing-brightgreen)
![HTTPS](https://img.shields.io/badge/HTTPS-Let's%20Encrypt-blue)

**Built as a PFA project at ENSA Khouribga — Option SCIL**

</div>

---

## What is this?

Mini Heroku is a minimal but real Platform-as-a-Service (PaaS) inspired by Heroku, Render, and Fly.io.

Push your code → it builds, runs, and serves it with HTTPS. Automatically.

```bash
git push myplatform main

-----> Received push for app: my-api
-----> Deploying my-api...
-----> Building image...
-----> Pushing to registry...
-----> Starting container...
-----> Deploy successful!
-----> Version: v3
-----> URL: https://my-api.68.221.16.224.sslip.io
```

---

## Architecture

```
Developer Machine                    Mini Heroku VM (Azure)
─────────────────                    ──────────────────────────────────────

git push ──────────────────────────► Git Server (SSH)
                                          │
                                          ▼
                                     post-receive hook
                                          │
                                          ▼
                                     FastAPI Control Plane :8000
                                       ├── Builder
                                       │     ├── git clone repo
                                       │     ├── docker build
                                       │     └── push → Registry :5000
                                       │
                                       ├── Runner
                                       │     ├── docker run
                                       │     ├── resource limits (CPU/RAM)
                                       │     └── health check + auto-restart
                                       │
                                       └── Caddy (reverse proxy)
                                             ├── <app>.domain → container
                                             └── Auto HTTPS (Let's Encrypt)
```

---

## Features

| Feature | Status |
|---|---|
| Git push deploy via SSH | ✅ |
| Auto Docker build from Dockerfile | ✅ |
| Local Docker registry | ✅ |
| Automatic HTTPS (Let's Encrypt) | ✅ |
| Custom subdomain per app | ✅ |
| Custom domains (DNS + auto HTTPS) | ✅ |
| Multi-user accounts + API tokens (hashés en base) | ✅ |
| Rotation + expiration des tokens API | ✅ |
| CSRF protection (Web UI) | ✅ |
| Rate-limiting sur l'auth (brute-force) | ✅ |
| Encrypted environment variables | ✅ |
| Real-time log streaming (SSE) | ✅ |
| CPU / RAM metrics | ✅ |
| Horizontal scaling + load balancing | ✅ |
| Release history + one-click rollback | ✅ |
| Container resource limits | ✅ |
| Health checks + auto-restart | ✅ |
| Add-ons Postgres / Redis attachables | ✅ |
| Backup DB + clé Fernet | ✅ |
| Web UI dashboard | ✅ |
| REST API + Swagger docs | ✅ |
| Full CLI (24 commands) | ✅ |
| systemd service (survives reboot) | ✅ |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Control plane | Python 3.12 + FastAPI |
| Containers | Docker + local Registry v2 |
| Reverse proxy | Caddy 2.11 (auto HTTPS) |
| Database | SQLite (via SQLAlchemy) |
| Encryption | Fernet (AES-128-CBC) |
| CLI | Python + Click |
| Web UI | Jinja2 + HTMX + Chart.js |
| Infrastructure | Azure VM — Ubuntu 24.04 |
| Tests | pytest (27/27 passing) |

---

## CLI Reference

| Command | Description |
|---|---|
| `myplatform register` | Create an account |
| `myplatform login` | Log in and store your API token |
| `myplatform logout` | Remove the stored token |
| `myplatform whoami` | Show the current user |
| `myplatform list` | List all deployed apps |
| `myplatform info <app>` | Show app details and URL |
| `myplatform logs <app>` | View recent logs |
| `myplatform logs <app> -f` | Stream logs in real time |
| `myplatform config:set <app> KEY=VAL` | Set an environment variable |
| `myplatform config:get <app>` | List all env vars (masked) |
| `myplatform config:unset <app> KEY` | Delete an env var |
| `myplatform scale <app> web=N` | Scale to N replicas |
| `myplatform restart <app>` | Restart the app |
| `myplatform releases <app>` | List all releases |
| `myplatform rollback <app> <version>` | Rollback to a previous release |
| `myplatform metrics <app>` | Show CPU and RAM usage |
| `myplatform ps <app>` | List running containers |
| `myplatform domains <app>` | List custom domains |
| `myplatform domains:add <app> DOMAIN` | Attach a custom domain |
| `myplatform domains:remove <app> DOMAIN` | Remove a custom domain |
| `myplatform addons` | List your add-ons |
| `myplatform addons:create <name> postgres\|redis` | Provision a database add-on |
| `myplatform addons:destroy <name>` | Destroy an add-on |
| `myplatform addons:attach <app> <addon>` | Attach an add-on to an app |
| `myplatform addons:detach <app> <addon>` | Detach an add-on from an app |
| `myplatform token:rotate` | Issue a new API token (old one revoked) |
| `myplatform token:revoke` | Revoke the current API token |

---

## Quick Start

### 1. Prerequisites
- Ubuntu 24.04 VM with ports 22, 80, 443, 8000 open
- Docker, Python 3.12, Caddy installed

### 2. Install
```bash
git clone https://github.com/Abdoulnasse-8/mini-heroku.git
cd mini-heroku
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
sudo systemctl start mini-heroku
```

### 3. Create your first app
```bash
# On the VM — initialize a git repo for your app
sudo mini-heroku-init-repo my-app

# On your local machine — log in first (multi-user)
myplatform register
myplatform login

# Add the remote and push
git remote add myplatform git@VM-IP:/opt/git-repos/my-app.git
git push myplatform main
```

### 4. Your app is live
```
https://my-app.YOUR-IP.sslip.io
```

---

## API Reference

Full interactive docs: `http://YOUR-IP:8000/docs`

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/register` | Create an account (returns API token) |
| `POST` | `/auth/login` | Log in (returns a new API token, rotation) |
| `GET` | `/auth/me` | Current user |
| `POST` | `/auth/rotate-token` | Issue a new token (revokes the old one) |
| `POST` | `/auth/revoke-token` | Revoke the current token |
| `POST` | `/apps/deploy` | Deploy an app from git repo |
| `GET` | `/apps` | List your apps |
| `GET` | `/apps/{name}` | Get app details |
| `PUT` | `/apps/{name}/config` | Set env var |
| `GET` | `/apps/{name}/config` | Get env vars |
| `GET` | `/apps/{name}/logs` | Stream logs (SSE) |
| `GET` | `/apps/{name}/metrics` | Get CPU/RAM metrics |
| `POST` | `/apps/{name}/scale` | Scale replicas |
| `POST` | `/apps/{name}/restart` | Restart app |
| `POST` | `/apps/{name}/stop` | Stop app |
| `GET` | `/apps/{name}/releases` | List releases |
| `POST` | `/apps/{name}/rollback` | Rollback to version N |
| `GET` | `/apps/{name}/ps` | List containers |
| `POST` | `/apps/{name}/domains` | Add a custom domain |
| `GET` | `/apps/{name}/domains` | List custom domains |
| `DELETE` | `/apps/{name}/domains/{domain}` | Remove a custom domain |
| `POST` | `/apps/{name}/deploy-zero-downtime` | Blue-green deploy |
| `POST` | `/addons` | Create an add-on (postgres/redis) |
| `GET` | `/addons` | List your add-ons |
| `DELETE` | `/addons/{name}` | Destroy an add-on |
| `POST` | `/apps/{name}/addons/{addon}` | Attach an add-on to an app |
| `DELETE` | `/apps/{name}/addons/{addon}` | Detach an add-on from an app |
| `GET` | `/apps/{name}/addons` | List add-ons attached to an app |
| `GET` | `/audit` | Audit log (global) |
| `GET` | `/audit/{app}` | Audit log per app |

---

## Security

- **Multi-user**: every user owns their apps — access control on all API + UI routes
- **API tokens**: opaque bearer tokens, **stored hashed** (SHA-256) — never in plaintext; PBKDF2-SHA256 password hashing
- **Token rotation**: each login / `token:rotate` issues a new token and revokes the previous one
- **Token expiration**: configurable TTL (default 90 days, `MINIHEROKU_TOKEN_TTL_DAYS`)
- **CSRF protection** on the Web UI (double-submit cookie + `X-CSRF-Token` header)
- **Rate-limiting** on `/auth/login` and `/auth/register` (brute-force, configurable)
- **Env vars encrypted at rest** using Fernet (AES-128-CBC); decrypt errors fail loudly instead of leaking garbage
- **Fernet key stored OUTSIDE the repo** (`~/.mini-heroku/fernet.key`, mode 600)
- **App containers bound to loopback** — only reachable through Caddy (no public random ports)
- **Input validation**: app names (regex), repo URLs (HTTPS or local path), domains
- **No secrets in logs** — all values masked as `***`
- **Resource limits** per container (CPU + memory)
- **Swagger docs disabled in production** (`MINIHEROKU_ENV=production`)

---

## Custom Domains (livrable du sujet)

1. Buy/point a domain (or subdomain) — create an `A` (and `AAAA`) DNS record to the VM IP:
   ```bash
   demo.mycompany.com  A  68.221.16.224
   ```
2. Attach it to your app (API, CLI or Web UI → *Domains* tab):
   ```bash
   myplatform domains:add my-app demo.mycompany.com
   ```
3. Caddy adds it to the site config and **Let's Encrypt issues the HTTPS certificate automatically**.

> `*.sslip.io` subdomains work out-of-the-box with no DNS setup — ideal for demos. A real custom
> domain requires DNS records pointing to the VM. HTTPS certs are provisioned automatically
> (validated via HTTP-01 challenge on the VM).

---

## Add-ons (Postgres / Redis)

Provision a managed database and attach it to an app in seconds. Attaching injects
`DATABASE_URL` (Postgres) or `REDIS_URL` (Redis) into the app and restarts it.

```bash
myplatform addons:create my-db postgres
myplatform addons:create my-cache redis
myplatform addons:attach my-app my-db
myplatform addons:detach my-app my-db
myplatform addons:destroy my-db
```

Add-ons run on an internal Docker network (`mh_addons`) — they are never exposed to the internet.

---

## Ops Runbook

### Service management
```bash
sudo systemctl start|stop|restart mini-heroku
sudo systemctl status mini-heroku
sudo journalctl -u mini-heroku -f
sudo journalctl -u caddy -f
```

### Backup
Backup la DB + la clé Fernet en un seul snapshot cohérent (sqlite3 backup API) :
```bash
cd ~/mini-heroku && source venv/bin/activate
python3 scripts/backup.py            # → ~/mini-heroku-backups/YYYYMMDD-HHMMSS/
python3 scripts/backup.py --list     # liste les snapshots
```
Cron conseillé :
```bash
30 3 * * *  cd ~/mini-heroku && python3 scripts/backup.py >> ~/mini-heroku-backups/backup.log 2>&1
```
> ⚠️ Sans backup, une perte de la VM = perte des données ET clé Fernet illisible
> (les env vars chiffrées deviennent indéchiffrables). Sauvegardez aussi la clé hors VM.

### Run tests
```bash
cd ~/mini-heroku && source venv/bin/activate
python3 -m pytest tests/test_auth.py tests/test_ops.py -v   # unitaires (sans Docker)
# Expected: 27 passed
python3 -m pytest tests/test_e2e.py -v                       # E2E (sur la VM)
```

### Add a new app
```bash
sudo mini-heroku-init-repo <app-name>
# Then from local machine:
git push myplatform main
```

---

## Project Structure

```
mini-heroku/
├── api/
│   ├── main.py        # FastAPI — tous les endpoints
│   ├── security.py    # Auth, hash PBKDF2/tokens, CSRF, validations
│   ├── ratelimit.py   # Rate limiter in-memory (fenêtre glissante)
│   └── ui.py          # Routes Web UI (login, apps, domains, add-ons)
├── builder/
│   └── build.py       # Clone → docker build → push registry
├── runner/
│   └── run.py         # Cycle de vie des containers Docker
├── proxy/
│   └── caddy.py       # Génération dynamique du Caddyfile (reconstruction propre)
├── cli/
│   └── main.py        # CLI Click (24 commandes)
├── db/
│   └── models.py      # Modèles SQLAlchemy (App, Release, EnvVar, AuditLog, User, CustomDomain, Addon)
├── scripts/
│   └── backup.py      # Backup DB + clé Fernet (prêt pour cron)
├── config.py          # Toutes les constantes configurables (env vars)
├── ui/
│   └── templates/
│       ├── base.html
│       ├── index.html   # Dashboard apps
│       ├── app.html     # Détail app (métriques, logs, env, releases, domains, add-ons)
│       ├── deploy.html  # Formulaire déploiement
│       ├── addons.html  # Gestion des add-ons
│       ├── login.html   # Connexion
│       └── register.html# Inscription
├── tests/
│   ├── test_auth.py   # Tests unitaires auth, tokens, rate-limit, CSRF, add-ons, backup
│   ├── test_ops.py    # Tests Caddyfile, scale, env vars, docs
│   └── test_e2e.py    # Tests E2E (sur la VM)
├── requirements.txt
└── README.md
```

---

## Evaluation

| Criterion | Weight | Result |
|---|---|---|
| End-to-end deploy works reliably | 25% | ✅ |
| HTTPS, networking, multi-app isolation | 20% | ✅ |
| Logs, metrics, env vars, scaling | 15% | ✅ |
| CLI & UI usability | 15% | ✅ |
| Code quality & security | 15% | ✅ |
| Demo & documentation | 10% | ✅ |

---

## Demo

- **hello-world**: https://hello-world.68.221.16.224.sslip.io
- **API docs**: http://68.221.16.224:8000/docs
- **Web UI**: http://68.221.16.224:8000/ui/

---

<div align="center">

**Built with ❤️ by Abdoul Nasser — ENSA Khouribga 2026**

*PFA — Génie Informatique — Option SCIL*

</div>
