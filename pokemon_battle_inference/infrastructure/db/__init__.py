import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm.session import sessionmaker


_Session = sessionmaker()

Base = declarative_base()
_session_ctx: ContextVar = ContextVar("pokemon_battle_inference_session", default=None)
_SESSION_TOKEN_KEY = "_session_token"

def get_db_url():
    config = {
        "username": os.getenv('PGUSER'),
        "password": os.getenv('PGPASSWORD'),
        "host": os.getenv('PGHOST'),
        "port": os.getenv('PGPORT'),
        "database": os.getenv('PGDATABASE')
    }

    db_url = "postgresql://{}:{}@{}:{}/{}".format(
        config.get("username", ""),
        config.get("password", ""),
        config.get("host", ""),
        config.get("port", 5432),
        config.get("database", "")
    )
    print(db_url)
    return db_url

def init_database(create_table, func, engine):
    if create_table:
        func(bind=engine)
    return True

def startup(create_tables: bool = True):
    sqlalchemy_url = get_db_url()
    engine = create_engine(
        sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=20,
        pool_recycle=3600
    )
    _Session.configure(bind=engine)
    if create_tables:
        Base.metadata.create_all(bind=engine)


def setup(create_tables: bool = False):
    startup(create_tables)


@contextmanager
def open_session(commit_on_exit: bool = True):
    """
    Context manager that provides a shared session for the current call stack.
    DAO code can call `get_session()` to reuse this session without threading it
    through every function signature.
    """
    session = _Session()
    token = _session_ctx.set(session)
    try:
        yield session
        if commit_on_exit:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        _session_ctx.reset(token)


def get_session():
    """
    Return the current session bound to the context manager if available.
    If no context manager is active, lazily create a session and remember it so
    callers (e.g., application layer) can commit or close it manually.
    """
    session = _session_ctx.get()
    if session is None:
        session = _Session()
        token = _session_ctx.set(session)
        session.info[_SESSION_TOKEN_KEY] = token
    return session


def close_session():
    """
    Close a session that was created via `get_session()` outside of
    `open_session`. Sessions spawned by `open_session` are closed when the
    context exits, so this function only affects ad-hoc sessions.
    """
    session = _session_ctx.get()
    if session is None:
        return
    token = session.info.pop(_SESSION_TOKEN_KEY, None)
    if token is None:
        return  # managed by open_session; leave it alone
    try:
        session.close()
    finally:
        _session_ctx.reset(token)


def with_session(func):
    """
    Decorator that ensures a SQLAlchemy session is injected into the wrapped
    function via the ``session`` keyword argument if one wasn't provided.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        if kwargs.get("session") is None:
            kwargs["session"] = get_session()
        return func(*args, **kwargs)

    return wrapper
