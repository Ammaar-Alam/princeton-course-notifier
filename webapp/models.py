import os
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, create_engine, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session


# Normalize DATABASE_URL for SQLAlchemy. Heroku and some providers export
# URLs beginning with "postgres://", but SQLAlchemy expects "postgresql://".
raw_db_url = os.getenv("DATABASE_URL", "sqlite:///app.db")
# Normalize scheme for SQLAlchemy (case-insensitive) and prefer explicit driver
prefix = raw_db_url[:10].lower()
if raw_db_url and prefix.startswith("postgres://"):
    raw_db_url = "postgresql+psycopg2://" + raw_db_url.split("://", 1)[1]
elif raw_db_url and prefix.startswith("postgresql://"):
    raw_db_url = "postgresql+psycopg2://" + raw_db_url.split("://", 1)[1]
DATABASE_URL = raw_db_url

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))
db_session = SessionLocal()

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    token = Column(String, unique=True, index=True)
    ntfy_topic = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    subs = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    course_code = Column(String)  # e.g. COS333
    course_id = Column(String)
    classid = Column(String)
    section = Column(String)
    last_notified_open = Column(Integer, default=-1)
    last_notified_at = Column(DateTime)
    user = relationship("User", back_populates="subs")


def init_db():
    Base.metadata.create_all(bind=engine)


def upsert_user(token: str) -> User:
    u = db_session.query(User).filter_by(token=token).first()
    if not u:
        u = User(token=token)
        db_session.add(u)
        db_session.commit()
    return u
