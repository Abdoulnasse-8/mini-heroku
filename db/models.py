from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, Boolean, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = os.environ.get(
    "MINIHEROKU_DB",
    f"sqlite:///{os.path.join(BASE_DIR, 'mini-heroku.db')}",
)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class App(Base):
    __tablename__ = "apps"
    name        = Column(String, primary_key=True)
    owner_email = Column(String, nullable=True)  # propriétaire (NULL = legacy)
    repo_url    = Column(String, nullable=True)  # source git du déploiement
    status      = Column(String, default="stopped")
    port        = Column(Integer)
    image       = Column(String)
    replicas    = Column(Integer, default=1)
    created_at  = Column(DateTime, default=datetime.utcnow)

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
    id          = Column(Integer, primary_key=True, autoincrement=True)
    email       = Column(String, unique=True)
    password    = Column(String)
    token       = Column(String, unique=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

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
