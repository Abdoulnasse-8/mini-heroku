# État du projet — Mini Heroku (notes de session)

> Fichier de contexte pour reprendre le travail. Dernière mise à jour : 2026-08-13 (session backlog).

## Où on en est (déployé sur la VM)

- VM : `68.221.16.224`, user `azureuser`, service systemd `mini-heroku` (uvicorn sur :8000), proxy Caddy sur 80/443.
- **VM toujours arrêtée** par l'utilisateur (changement de taille). À redémarrer avant de reprendre.
  → **Après la soutenance : redescendre en `B2ts_v2` ou supprimer la VM pour ne plus payer.**
- **Au prochain boot de la VM :** `sudo systemctl start docker` puis `sudo systemctl restart mini-heroku`, et relancer les apps via `POST /apps/{name}/restart`.
- **Session 13/08 — BACKLOG (10/10) + 1 BONUS faits, en local (pas encore commités ni poussés) :**
  1. **CSRF UI** : cookie `mh_csrf` (double-submit) + middleware FastAPI + header `X-CSRF-Token` dans `base.html`. Les GET `/ui/login` & `/ui/register` posent le cookie + champ caché.
  2. **Rate-limiting** : `api/ratelimit.py` (fenêtre glissante in-memory) sur `/auth/login` (10/15min) et `/auth/register` (5/h) — API + UI. 429 + `Retry-After` (le custom exception handler passe maintenant les headers).
  3. **Tokens hashés + rotation/expiration** : les tokens ne sont plus en clair en base (`sha256$hex` dans `users.token`, migration auto des legacy). Login = rotation (nouveau token à chaque connexion). TTL 90j (`MINIHEROKU_TOKEN_TTL_DAYS`). Endpoints `POST /auth/rotate-token`, `POST /auth/revoke-token`. ⚠️ **Re-login nécessaire pour la demo user après déploiement** (l'ancien token en base est hashé par la migration, le cookie encore valide — vérifier).
  4. **Caddyfile propre** : `update_caddyfile_replicas` supprimé → `update_caddyfile(apps)` reconstruit tout le fichier ; `ports` (replicas) stockés dans `apps.replica_ports` (JSON) par le scale. `_caddy_apps()` les relit.
  5. **Backup** : `scripts/backup.py` (backup sqlite3 API + copie clé Fernet, horodaté, prune keep-N). Cron dans le README.
  6. **`get_env_vars`** échoue en 500 (avec log) au lieu d'avaler les erreurs de déchiffrement.
  7. **Ports restreints** : les containers d'apps + replicas + blue-green écoutent sur `127.0.0.1` (`MINIHEROKU_APP_BIND`), exposés uniquement via Caddy. API conseillée en bind 127.0.0.1 aussi.
  8. **Constantes centralisées** : `config.py` (BASE_DOMAIN, ports, bind, TTL, rate-limit, réseau addons, backup). Templates/CLI utilisent `{{ base_domain }}` / `MINIHEROKU_BASE_DOMAIN`.
  9. **Custom domains** : feature déjà en place ; README documenté (DNS A → VM + Let's Encrypt auto). Pour le livrable, il faut pointer 2 vrais domaines vers `68.221.16.224` et les attacher aux apps de démo.
  10. **/docs** désactivé en prod (`MINIHEROKU_ENV=production`) + lien sidebar conditionnel.
  - **Bonus — Add-ons Postgres/Redis** : table `Addon` + `AppAddon` ; réseau Docker `mh_addons` (interne, jamais exposé) ; containers `postgres:16-alpine` / `redis:7-alpine` avec mot de passe généré (chiffré Fernet en base). `POST /addons`, `GET /addons`, `DELETE /addons/{name}`, `POST|DELETE /apps/{name}/addons/{addon}` (injecte `DATABASE_URL`/`REDIS_URL` + restart app), `GET /apps/{name}/addons`. CLI : `addons`, `addons:create`, `addons:destroy`, `addons:attach`, `addons:detach`. UI : page `/ui/addons` + onglet Add-ons dans app.
  - **Tests** : `tests/test_auth.py` (23) + `tests/test_ops.py` (4) = **27 passed** (`/tmp/opencode/venv-mh`). Nouveaux tests : tokens hashés/expiration/rotation, rate-limit, CSRF UI, add-ons (docker mocké), Caddyfile rendering, scale replica_ports, env var corrompue → 500.
- Identifiants de démo UI : `demo@test.local` / `demopass123`.
- Clé Fernet hors repo : `~/.mini-heroku/fernet.key` (0600).
- Push GitHub : via token PAT dans l'URL (`ghp_...@github.com/...`) — **token à révoquer après la soutenance**, credential helper `gh` cassé sur la machine locale.

## Rappels critiques (pièges connus)

- Après un `git pull` sur la VM : **toujours `sudo systemctl restart mini-heroku`**.
- Un `sudo systemctl restart docker` NE redémarre PAS les containers `on-failure` → on est passé en `unless-stopped` ; si un container legacy est absent après reboot, le relancer via `POST /apps/{name}/restart`.
- Le sudoers VM autorise `azureuser` à `sudo systemctl reload caddy` (nécessaire au code).
- Les containers écoutent sur le port **8000** (ports mapping dans `run.py`), health check ≤ 30s. Depuis cette session : bind `127.0.0.1`.
- Le build Docker Next.js de CabinetMedical : lourd mais OK sur B2ls_v2. Le cache des images rend les re-deploys rapides.
- **Nouveau** : les apps et add-ons tournent sur le réseau Docker `mh_addons` — si un vieux container legacy tourne encore sur le réseau par défaut après `git pull`, un simple restart le remet à jour.
- **Nouveau** : chaque `login` émet un nouveau token → la demo UI/CLI doit se reconnecter après déploiement.

## Idées d'amélioration (backlog restant / bonus)

- **Add-ons** : expose le port du addon sur `127.0.0.1` pour debug si besoin ; backup des addons (pg_dump) ; limites par user.
- **Docs/Swagger** : le lien `/docs` est caché en prod (fait), mais les routes `/audit` restent ouvertes aux users authentifiés.
- **Auto-suspend** des apps gratuites après 30 min d'inactivité + réveil sur requête (bonus du sujet, pas encore fait).
- **Review apps** par branche/PR (bonus du sujet).
- **Cluster mode** (k3s/Nomad) (bonus du sujet).

## Commandes utiles (à taper soi-même sur la VM)

```bash
cd ~/mini-heroku && source venv/bin/activate
python3 -m pytest tests/test_auth.py tests/test_ops.py -v   # tests unitaires (sans Docker)
systemctl status mini-heroku caddy           # services
docker ps                                    # containers
docker network ls | grep mh_addons           # réseau add-ons
sudo journalctl -u mini-heroku -n 50         # logs API
curl -s -o /dev/null -w '%{http_code}\n' https://demo-python.68.221.16.224.sslip.io
cd ~/mini-heroku && python3 scripts/backup.py   # backup DB + clé Fernet
```