from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio

# --- unit-test-only fixtures (no DB, no network) ------------------------


@pytest.fixture(scope="session")
def rsa_keypair():
    """A throwaway RSA keypair for unit-testing JWT validation without a
    real Keycloak instance -- see tests/unit/test_jwt_validation.py."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


@pytest.fixture
def demo_tenant_id() -> uuid.UUID:
    return uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")


# --- integration-test fixtures (testcontainers postgres) ----------------
# Only imported/used by tests under tests/integration and tests/api; unit
# tests never touch these, so `pytest tests/unit` needs no Docker at all.

_ROLE_SETUP_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'installtec_migrator') THEN
        CREATE ROLE installtec_migrator LOGIN PASSWORD 'test' NOSUPERUSER NOBYPASSRLS CREATEDB;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'installtec_app') THEN
        CREATE ROLE installtec_app LOGIN PASSWORD 'test' NOSUPERUSER NOBYPASSRLS NOCREATEDB;
    END IF;
END
$$;
ALTER DATABASE test OWNER TO installtec_migrator;
GRANT ALL ON SCHEMA public TO installtec_migrator;
GRANT USAGE ON SCHEMA public TO installtec_app;
ALTER DEFAULT PRIVILEGES FOR ROLE installtec_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO installtec_app;
ALTER DEFAULT PRIVILEGES FOR ROLE installtec_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO installtec_app;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS citext;
"""


def _skip_if_no_docker() -> None:
    if os.environ.get("SKIP_DOCKER_TESTS") == "1":
        pytest.skip("SKIP_DOCKER_TESTS=1 -- integration tests requiring Docker are disabled")


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[str]:
    """Session-scoped pgvector/pgvector:pg16 container (same image as
    prod). Returns the migrator-role DSN. Provisions the installtec_app /
    installtec_migrator roles the same way deploy/postgres/initdb/10-roles.sh
    does, then runs every Alembic migration once for the whole test session."""
    _skip_if_no_docker()
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", username="postgres", password="postgres", dbname="test") as pg:
        import psycopg2

        admin_url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        conn = psycopg2.connect(admin_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(_ROLE_SETUP_SQL)
        conn.close()

        migrator_dsn = (
            f"postgresql+asyncpg://installtec_migrator:test@{pg.get_container_host_ip()}:"
            f"{pg.get_exposed_port(5432)}/test"
        )
        os.environ["MIGRATOR_DATABASE_URL"] = migrator_dsn
        os.environ["APP_DATABASE_URL"] = (
            f"postgresql+asyncpg://installtec_app:test@{pg.get_container_host_ip()}:"
            f"{pg.get_exposed_port(5432)}/test"
        )
        # The remaining required Settings fields aren't exercised by
        # integration tests (no real S3/vLLM calls happen here) but
        # Settings() itself requires them to construct at all.
        os.environ.setdefault("S3_ENDPOINT", "http://s3.invalid")
        os.environ.setdefault("VLLM_API_BASE", "http://vllm.invalid/v1")

        from alembic import command
        from alembic.config import Config

        cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "app", "migrations"))
        command.upgrade(cfg, "head")

        yield migrator_dsn


@pytest.fixture(scope="session")
def redis_container() -> Iterator[str]:
    """Session-scoped real Redis container -- used by tests/api for the
    OIDC login flow (SessionStore stores OAuth state in Redis), which a
    fake unreachable REDIS_URL can't exercise."""
    _skip_if_no_docker()
    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as rc:
        yield f"redis://{rc.get_container_host_ip()}:{rc.get_exposed_port(6379)}/0"


@pytest_asyncio.fixture
async def app_engine(postgres_container):
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["APP_DATABASE_URL"])
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def rls_session(app_engine) -> AsyncIterator["AsyncSession"]:  # noqa: F821
    """One transaction, rolled back at test end, connected as the
    NOBYPASSRLS installtec_app role -- exactly how the real app connects.
    RLS context (tenant/user/roles) is NOT set by this fixture; call
    set_rls_context() explicitly per test so each test's intent is visible."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(app_engine, expire_on_commit=False) as session, session.begin():
        yield session
        await session.rollback()


@pytest.fixture
def make_context(demo_tenant_id):
    from app.core.context import RequestContext

    def _make(
        *,
        roles: frozenset[str] = frozenset(),
        user_id: uuid.UUID | None = None,
        tenant_id=None,
        is_system=False,
        acr: str | None = None,
    ):
        return RequestContext(
            tenant_id=tenant_id or demo_tenant_id,
            user_id=user_id or uuid.uuid4(),
            sub=str(user_id) if user_id else "test-user",
            roles=roles,
            is_system=is_system,
            acr=acr,
        )

    return _make
