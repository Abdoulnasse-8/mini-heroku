#!/usr/bin/env python3
"""Backup de la base SQLite + clé Fernet.

Usage :
    python3 scripts/backup.py            # backup horodaté dans MINIHEROKU_BACKUP_DIR
    python3 scripts/backup.py --list     # liste les backups existants

Cron conseillé (sur la VM) :
    30 3 * * *  cd ~/mini-heroku && python3 scripts/backup.py >> ~/mini-heroku-backups/backup.log 2>&1
"""
import argparse
import datetime
import os
import shutil
import sqlite3
import sys

import config


def backup() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_dir = os.path.join(config.BACKUP_DIR, ts)
    os.makedirs(dest_dir, exist_ok=True)

    db_path = config.DATABASE_URL.replace("sqlite:///", "")
    if not os.path.isabs(db_path):
        db_path = os.path.join(config.BASE_DIR, db_path)
    if not os.path.exists(db_path):
        print(f"!! DB introuvable : {db_path} (rien à sauvegarder)")
        return dest_dir

    # Backup cohérent même si l'API écrit en parallèle (sqlite3 backup API)
    dest_db = os.path.join(dest_dir, "mini-heroku.db")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest_db)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    if os.path.exists(config.FERNET_KEY_FILE):
        shutil.copy2(config.FERNET_KEY_FILE, os.path.join(dest_dir, "fernet.key"))
        os.chmod(os.path.join(dest_dir, "fernet.key"), 0o600)

    # Récapitulatif (taille + utilisateurs) pour vérifier le backup
    try:
        conn = sqlite3.connect(dest_db)
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        apps = conn.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
        conn.close()
        size = os.path.getsize(dest_db)
        print(f"✔ Backup {ts}: {size} bytes, {users} users, {apps} apps → {dest_dir}")
    except Exception as e:
        print(f"⚠ Backup écrit mais lecture impossible : {e}")

    _prune()
    return dest_dir


def _prune():
    keep = max(int(config.BACKUP_KEEP), 1)
    dirs = sorted(
        d for d in os.listdir(config.BACKUP_DIR)
        if os.path.isdir(os.path.join(config.BACKUP_DIR, d))
    )
    for old in dirs[:-keep] if keep < len(dirs) else []:
        shutil.rmtree(os.path.join(config.BACKUP_DIR, old))
        print(f"   pruning {old}")


def list_backups():
    if not os.path.isdir(config.BACKUP_DIR):
        print("Aucun backup.")
        return
    for d in sorted(os.listdir(config.BACKUP_DIR)):
        p = os.path.join(config.BACKUP_DIR, d)
        if os.path.isdir(p):
            size = sum(os.path.getsize(os.path.join(p, f))
                       for f in os.listdir(p)
                       if os.path.isfile(os.path.join(p, f)))
            print(f"{d}\t{size} bytes")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="liste les backups")
    args = ap.parse_args()
    if args.list:
        list_backups()
    else:
        backup()
