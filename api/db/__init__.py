from sqlalchemy import create_engine
from sqlalchemy.orm.session import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from contextlib import contextmanager


_Session = sessionmaker()

Base = declarative_base()

def get_db_url():
    config = {
        "username": "espeon",
        "password": "11451400",
        "host": "localhost",
        "port": "5432",
        "database": "espeon"
    }
    db_url = "postgresql://{}:{}@{}:{}/{}".format(
        config.get("username", ""),
        config.get("password", ""),
        config.get("host", ""),
        config.get("port", ""),
        config.get("database", "")
    )
    return db_url

def init_database(create_table, func, engine):
    if create_table:
        print(".....")
        func(bind=engine)
    return True

def startup(create_table: bool = False):
    sqlalchemy_url = get_db_url()
    engine = create_engine(
        sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=20,
        pool_recycle=3600
    )
    
    _Session.configure(bind=engine)
    print(Base)
    return init_database(create_table, Base.metadata.create_all, engine)

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