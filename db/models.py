import hashlib
import json
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

import config

DATABASE_URL = config.DATABASE_URL
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class App(Base):
    __tablename__ = "apps"
    name          = Column(String, primary_key=True)
    owner_email   = Column(String, nullable=True)  # propriétaire (NULL = legacy)
    repo_url      = Column(String, nullable=True)  # source git du déploiement
    status        = Column(String, default="stopped")
    port          = Column(Integer)
    image         = Column(String)
    replicas      = Column(Integer, default=1)
    replica_ports = Column(Text)  # JSON list des ports des replicas (scale)
    created_at    = Column(DateTime, default=datetime.utcnow)

class Release(Base):
    __tablename__ = "releases"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    app_name    = Column(String)
    version     = Column(Integer)
    image       = Column(String)
    deployed_at = Column(DateTime, default=datetime.utcnow)

class EnvVar(Base):
    __tablename__ = "env_vars"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    app_name    = Column(String)
    key         = Column(String)
    value       = Column(Text)  # chiffré

class CustomDomain(Base):
    __tablename__ = "custom_domains"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    app_name    = Column(String)
    domain      = Column(String, unique=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

class User(Base):
    __tablename__ = "users"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    email            = Column(String, unique=True)
    password         = Column(String)
    token            = Column(String, unique=True)  # hash du token (sha256$hex)
    token_expires_at = Column(DateTime, nullable=True)  # None = jamais expiré
    created_at       = Column(DateTime, default=datetime.utcnow)

class Addon(Base):
    __tablename__ = "addons"
    name        = Column(String, primary_key=True)
    owner_email = Column(String)
    kind        = Column(String)      # postgres | redis
    password    = Column(Text)        # chiffré (Fernet)
    status      = Column(String, default="running")
    created_at  = Column(DateTime, default=datetime.utcnow)

class AppAddon(Base):
    __tablename__ = "app_addons"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    app_name   = Column(String)
    addon_name = Column(String)

def _migrate():
    """Migrations SQLite idempotentes — ajoute les colonnes manquantes."""
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(apps)"))}
        if "owner_email" not in cols:
            conn.execute(text("ALTER TABLE apps ADD COLUMN owner_email VARCHAR"))
            conn.commit()
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(apps)"))}
        if "repo_url" not in cols:
            conn.execute(text("ALTER TABLE apps ADD COLUMN repo_url VARCHAR"))
            conn.commit()
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(apps)"))}
        if "replica_ports" not in cols:
            conn.execute(text("ALTER TABLE apps ADD COLUMN replica_ports TEXT"))
            conn.commit()
        ucols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)"))}
        if "created_at" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN created_at DATETIME"))
            conn.commit()
        ucols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)"))}
        if "token_expires_at" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN token_expires_at DATETIME"))
            conn.commit()
        # Hasher les tokens legacy stockés en clair (non rétro-déchiffrable)
        for uid, tok in conn.execute(text("SELECT id, token FROM users")).fetchall():
            if tok and not tok.startswith("sha256$"):
                hashed = "sha256$" + hashlib.sha256(tok.encode()).hexdigest()
                conn.execute(text("UPDATE users SET token = ? WHERE id = ?"), (hashed, uid))
        conn.commit()

def init_db():
    Base.metadata.create_all(engine)
    _migrate()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    action     = Column(String)      # deploy, scale, restart, config:set...
    app_name   = Column(String)
    details    = Column(Text)        # JSON details
    status     = Column(String)      # success, error
    created_at = Column(DateTime, default=datetime.utcnow)
