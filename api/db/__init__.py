import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm.session import sessionmaker
from sqlalchemy.orm import declarative_base
from contextlib import contextmanager


_Session = sessionmaker()

Base = declarative_base()

def get_db_url():
    config = {
        "username": os.getenv('POSTGRES_USER'),
        "password": os.getenv('POSTGRES_PASSWORD'),
        "host": "192.168.31.239",
        "port": "5432",
        "database": os.getenv('POSTGRES_DB')
    }

    db_url = "postgresql://{}:{}@{}:{}/{}".format(
        config.get("username", ""),
        config.get("password", ""),
        config.get("host", ""),
        config.get("port", ""),
        config.get("database", "")
    )
    logging.info(db_url)
    return db_url

def init_database(create_table, func, engine):
    if create_table:
        func(bind=engine)
    return True

def startup():
    sqlalchemy_url = get_db_url()
    engine = create_engine(
        sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=20,
        pool_recycle=3600
    )
    _Session.configure(bind=engine)
    Base.metadata.create_all(bind=engine)

def setup():
    startup(False)


@contextmanager
def open_session():
    session = _Session()
    
    try:
        yield session
        session.commit()
    except:
        session.rollback()
    finally:
        session.close()