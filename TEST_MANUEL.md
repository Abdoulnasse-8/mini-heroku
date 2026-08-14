# 🧪 TEST MANUEL — Mini Heroku (à faire toi-même)

> Guide pas-à-pas pour vérifier la plateforme à la main, en préparation de la soutenance.
> Coche chaque case après vérification. Durée estimée : 30–40 min.

---

## 0. Prérequis

- [ ] La VM `68.221.16.224` est allumée (portail Azure → *Start*).
- [ ] Services actifs :
  ```bash
  systemctl is-active docker mini-heroku caddy   # → active active active
  ```
- [ ] La Web UI s'ouvre : **http://68.221.16.224:8000/ui/login**
- [ ] Identifiants de démo : `demo@test.local` / `demo123`
  (ou ton propre compte via le bouton *Register*)

---

## 1. Connexion & tableau de bord

- [ ] Va sur **http://68.221.16.224:8000/ui/login**
- [ ] Connecte-toi avec `demo@test.local` / `demo123`
- [ ] Tu arrives sur le **dashboard** : liste des apps avec statut
  → Attendu : `hello-world`, `demo-python`, `cabinetmedical`, `cabinet-api` en `running`, `demo-app` en `stopped`
- [ ] Clique sur une app (ex. `cabinet-api`) → page détail
  → Attendu : statut, image `localhost:5000/...`, port, onglets (Configuration / Domains / Add-ons / Releases / Logs)
- [ ] **Vérifie le HTTPS** dans un autre onglet :
  - https://hello-world.68.221.16.224.sslip.io → JSON `{"status":"ok",...}` (200)
  - https://cabinetmedical.68.221.16.224.sslip.io → page de connexion du cabinet (200)

---

## 2. Déploiement d'une nouvelle app (le moment fort)

- [ ] Menu **Deploy App**
- [ ] App name : `test-<tonprenom>` (minuscules + tirets)
- [ ] Repo : `/opt/git-repos/hello-world.git` (repo local, rapide)
- [ ] Clique **Deploy Application**
  → Attendu : "Deploying…" puis **"✅ Deployed test-xxx (v1)"** + lien HTTPS
- [ ] Ouvre le lien HTTPS → **JSON** `{"status":"ok","app":"hello-world",...}` (200)
- [ ] (Optionnel, version longue) Déploie depuis GitHub public :
  Repo `https://github.com/Abdoulnasse-8/CabinetMedical.git` avec **Build file** `JEEproject/Dockerfile`
  → attendre le build Maven (2–5 min)

---

## 3. Configuration (env vars)

- [ ] Page de l'app `test-xxx` → onglet **Configuration**
- [ ] Ajoute `FLAVOR` = `demo` → bouton *Add variable*
- [ ] La variable apparaît **masquée** : `FLAVOR = ***`
- [ ] Clique **↻ Redeploy** ou **Restart** (pour injecter l'env)
  → Attendu : l'app redémarre, toujours accessible en HTTPS
- [ ] Test de suppression : retire `FLAVOR`

---

## 4. Logs

- [ ] Onglet **Logs** de l'app `cabinet-api` (le backend Spring Boot logge beaucoup)
- [ ] Lance le streaming de logs
  → Attendu : des lignes défilent (requêtes SQL Hibernate, etc.) en temps réel

---

## 5. Métriques

- [ ] Page de l'app `test-xxx` → graphique **Live metrics**
  → Attendu : courbe CPU/RAM qui se met à jour (polling 3s)
- [ ] Recharge la page HTTPS plusieurs fois
  → Attendu : le CPU/Memory bouge légèrement

---

## 6. Scaling (replicas + load balancing)

- [ ] Page de l'app `test-xxx`, action **Scale** (ou CLI `myplatform scale test-xxx web=2`)
- [ ] Mets **2 replicas**
- [ ] Vérifie que 3 containers existent :
  ```bash
  docker ps --filter name=app-test-xxx
  # → app-test-xxx + app-test-xxx-replica-0 + app-test-xxx-replica-1
  ```
- [ ] Recharge l'URL HTTPS plusieurs fois → toujours 200 (Caddy balance entre les replicas)
- [ ] **Remets à 1 replica** ⚠️ (important : le `stop` n'arrête pas les replicas !)

---

## 7. Releases & rollback

- [ ] Onglet **Releases** de `test-xxx` → v1 visible
- [ ] Redéploie (bouton **↻ Redeploy**) → v2 apparaît
- [ ] **Rollback** vers v1 (bouton ou CLI `myplatform rollback test-xxx 1`)
  → Attendu : l'app redevient la v1, toujours en HTTPS (pas de coupure)

---

## 8. Add-ons (base de données)

- [ ] Menu **Add-ons** → **New add-on** : nom `test-cache`, type **Redis**
- [ ] Attache : page app `test-xxx` → onglet **Add-ons** → attache `test-cache`
  → Attendu : l'app redémarre, `REDIS_URL` est injectée
- [ ] Preuve :
  ```bash
  docker inspect app-test-xxx --format '{{json .Config.Env}}'
  # → contient "REDIS_URL=redis://default:...@addon-test-cache:6379/0"
  ```
- [ ] Détache puis **détruit** l'add-on `test-cache` (test de nettoyage)

---

## 9. Stop / restart

- [ ] Page app `test-xxx` → **Stop**
  → Attendu : statut passe à `stopped`, l'URL HTTPS ne répond plus
- [ ] **Start** (ou Restart) → l'app revient, HTTPS OK

---

## 10. Cabinet médical (la démo finale, celle qui impressionne)

- [ ] Ouvre **https://cabinetmedical.68.221.16.224.sslip.io/login**
- [ ] Connecte-toi avec `admin` / `password` (espace ADMINISTRATEUR)
- [ ] Vérifie le dashboard : cabinet, statistiques
- [ ] Déconnecte-toi et connecte-toi avec `medecin1` / `password` (espace MEDECIN)
- [ ] Déconnecte-toi et connecte-toi avec `secretaire1` / `password` (espace SECRETAIRE)
- [ ] Crée un patient (bouton *Nouveau patient*) → il doit apparaître dans la liste
- [ ] Crée un rendez-vous pour ce patient
- [ ] **Preuve de persistance** (le vrai test « base de données ») :
  ```bash
  docker exec addon-cabinet-db psql "postgresql://postgres:$(sudo grep -o 'fernet' /dev/null 2>/dev/null; echo)@localhost:5432/cabinet-db" -c "select id,cin,nom from patients;"
  ```
  → (ou plus simple, voir ci-dessous) Recharge la page après quelques secondes : le patient est toujours là
- [ ] Recharge la page du frontend → le patient créé est toujours présent (données persistées dans Postgres)

---

## 11. Nettoyage après ton test

- [ ] Stop l'app `test-xxx` et supprime-la si tu veux (manuellement via docker + DB) ou laisse-la comme app de démo
- [ ] Remets le scale de `hello-world` à 1 si tu l'avais modifié
- [ ] Vérifie que le dashboard est propre :
  ```bash
  curl -s http://localhost:8000/apps -H "Authorization: Bearer <ton-token>"
  ```

---

## ✅ Checklist finale (avant la soutenance)

- [ ] Deploy depuis git → HTTPS fonctionne (testé < 2 min)
- [ ] HTTPS + Let's Encrypt OK sur toutes les apps
- [ ] Config (env vars chiffrées) OK
- [ ] Logs streaming OK
- [ ] Métriques CPU/RAM OK
- [ ] Scale + load balancing OK
- [ ] Releases + rollback OK
- [ ] Add-ons (Postgres/Redis) OK
- [ ] Multi-user (2 comptes qui ne voient pas les apps de l'autre)
- [ ] Cabinet médical complet : login, patients, rendez-vous, persistance

---

## 🔍 Points connus à connaître (si un juge teste)

- `cabinet-api` renvoie **403 sur `/`** : normal, c'est une API protégée (les endpoints `/api/...` répondent 200).
- Le `stop` n'arrête pas les réplicas → toujours rescaler à 1 avant un stop.
- Les apps Python qui n'utilisent que `print()` sans TTY n'affichent pas de logs (bufférisation) — les logs sont prouvés avec `cabinet-api` (Spring Boot).
- Repos GitHub privés : rends le repo **public** avant un déploiement depuis GitHub (le builder clone en HTTPS).
