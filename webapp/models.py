import os
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, create_engine, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")

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

