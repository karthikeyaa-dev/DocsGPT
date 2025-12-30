from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from application.api.auth.config import CONFIG
from application.api.auth.users.exceptions import DatabaseConnectionError
from sqlalchemy.exc import OperationalError


class DBConnection:
    def __init__(self):
        self._check_config()
        self.engine = self._create_engine()
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

    def _check_config(self):
        required_attrs = [
            "PG_USERNAME",
            "PG_PASSWORD",
            "PG_DATABASENAME",
            "PG_HOST",
            "PG_PORT",
        ]
        missing = [attr for attr in required_attrs if not getattr(CONFIG, attr, None)]
        if missing:
            raise ValueError(
                f"Missing database configuration for: {', '.join(missing)}"
            )

    def _create_engine(self):
        DATABASE_URL = f"postgresql+psycopg2://{CONFIG.PG_USERNAME}:{CONFIG.PG_PASSWORD}@{CONFIG.PG_HOST}:{CONFIG.PG_PORT}/{CONFIG.PG_DATABASENAME}"
        return create_engine(DATABASE_URL, echo=True)

    def get_database_url(self):
        """Return the database URL for Flask config."""
        return f"postgresql+psycopg2://{CONFIG.PG_USERNAME}:{CONFIG.PG_PASSWORD}@{CONFIG.PG_HOST}:{CONFIG.PG_PORT}/{CONFIG.PG_DATABASENAME}"

    @contextmanager
    def session(self):
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except OperationalError as e:
            print(f"Operational error: {e}")
            session.rollback()
            raise DataBaseConnectionError(f"Database operational error: {str(e)}", 502)
        except Exception as e:
            print(f"Unknown database error: {e}")
            session.rollback()
            raise DataBaseConnectionError(
                f"Failed to connect to the database: {str(e)}", 502
            )
        finally:
            session.close()
