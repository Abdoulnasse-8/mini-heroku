from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:////home/azureuser/mini-heroku/mini-heroku.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class App(Base):
    __tablename__ = "apps"
    name        = Column(String, primary_key=True)
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

class User(Base):
    __tablename__ = "users"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    email       = Column(String, unique=True)
    password    = Column(String)
    token       = Column(String, unique=True)

def init_db():
    Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
