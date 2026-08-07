<div align="center">

# ⚡ Mini Heroku

### A self-hosted PaaS platform — git push → HTTPS in under 2 minutes

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green?logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-24+-blue?logo=docker)
![Caddy](https://img.shields.io/badge/Caddy-2.11-orange)
![Tests](https://img.shields.io/badge/tests-11%2F11%20passing-brightgreen)
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
| Encrypted environment variables | ✅ |
| Real-time log streaming (SSE) | ✅ |
| CPU / RAM metrics | ✅ |
| Horizontal scaling + load balancing | ✅ |
| Release history + one-click rollback | ✅ |
| Container resource limits | ✅ |
| Health checks + auto-restart | ✅ |
| Web UI dashboard | ✅ |
| REST API + Swagger docs | ✅ |
| Full CLI (12 commands) | ✅ |
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
| Tests | pytest (11/11 passing) |

---

## CLI Reference

| Command | Description |
|---|---|
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

# On your local machine — add the remote and push
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
| `POST` | `/apps/deploy` | Deploy an app from git repo |
| `GET` | `/apps` | List all apps |
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

---

## Security

- **Env vars encrypted at rest** using Fernet (AES-128-CBC)
- **No secrets in logs** — all values masked as `***`
- **Input validation** on all API endpoints
- **Resource limits** per container (CPU + memory)
- **Bandit audit**: 0 High severity issues

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
```bash
mkdir -p ~/mini-heroku/backups
cp ~/mini-heroku/mini-heroku.db \
   ~/mini-heroku/backups/db-$(date +%Y%m%d-%H%M).db
```

### Run tests
```bash
cd ~/mini-heroku && source venv/bin/activate
pytest tests/test_e2e.py -v
# Expected: 11 passed
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
│   ├── main.py          # FastAPI control plane (all endpoints)
│   └── ui.py            # Web UI routes
├── builder/
│   └── build.py         # Clone → docker build → push registry
├── runner/
│   └── run.py           # Docker container lifecycle
├── proxy/
│   └── caddy.py         # Dynamic Caddyfile generation
├── cli/
│   └── main.py          # Click CLI (12 commands)
├── db/
│   └── models.py        # SQLAlchemy models
├── ui/
│   └── templates/
│       ├── base.html
│       ├── index.html
│       ├── app.html
│       └── deploy.html
├── tests/
│   └── test_e2e.py      # End-to-end tests (11/11 passing)
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
