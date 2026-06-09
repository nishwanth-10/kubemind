"""
KubeMind AI — Neon PostgreSQL Database Layer
Async connection with SSL, connection pooling, and idempotent schema creation.

Uses asyncpg directly via SQLAlchemy async engine.
Compatible with Neon serverless PostgreSQL.
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Engine creation ──────────────────────────────────────────────────────────
# Neon requires SSL. asyncpg accepts ssl="require" via connect_args.
# We convert postgres:// → postgresql+asyncpg:// if needed.

def _neon_url(raw: str) -> str:
    """Normalise DATABASE_URL to the asyncpg dialect."""
    url = raw.split("?")[0] # strip out the query string to prevent asyncpg kwargs error
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


_engine = create_async_engine(
    _neon_url(settings.DATABASE_URL),
    # Neon Serverless: short-lived connections are fine; keep pool small
    pool_size=3,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=300,          # recycle before Neon's 5-min idle timeout
    pool_pre_ping=True,        # test connection before use
    connect_args={
        "ssl": settings.DB_SSL,      # "require" for Neon, "disable" for local
        "statement_cache_size": 0,  # required for PgBouncer / Neon pooler
    },
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── Schema DDL (idempotent) ───────────────────────────────────────────────────
# TimescaleDB hypertables are created only if the extension is present.
# On Neon, TimescaleDB is available as an extension on paid plans.
# We fall back gracefully if it is not installed.

_SCHEMA_SQL = """
-- Timescale extension (optional — skipped if not available)
-- CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ── Multi-Tenancy Core ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organizations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'viewer',
    org_id        TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clusters (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    provider    TEXT NOT NULL,
    org_id      TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash    TEXT PRIMARY KEY,
    cluster_id  TEXT NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    org_id      TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Metrics history ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS metrics_history (
    id              BIGSERIAL,
    org_id          TEXT        NOT NULL,
    cluster_id      TEXT        NOT NULL,
    service         TEXT        NOT NULL,
    namespace       TEXT        NOT NULL,
    domain          TEXT        NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cpu_percent     NUMERIC(5,2),
    memory_mb       INTEGER,
    network_in_kbps NUMERIC(10,2),
    network_out_kbps NUMERIC(10,2),
    disk_usage_pct  NUMERIC(5,2),
    error_rate_pct  NUMERIC(5,2),
    latency_ms      NUMERIC(10,2),
    restart_count   INTEGER,
    status          TEXT,
    PRIMARY KEY (id, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_mh_org_cluster_time
    ON metrics_history (org_id, cluster_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_mh_service_time
    ON metrics_history (service, recorded_at DESC);

-- ── Anomaly records ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS anomaly_records (
    id              BIGSERIAL PRIMARY KEY,
    org_id          TEXT        NOT NULL,
    cluster_id      TEXT        NOT NULL,
    service         TEXT        NOT NULL,
    namespace       TEXT        NOT NULL,
    domain          TEXT        NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity        TEXT        NOT NULL,
    anomaly_types   TEXT[]      NOT NULL,
    detection_method TEXT       NOT NULL,
    anomaly_score   NUMERIC(6,4),
    confidence      NUMERIC(5,3),
    raw_payload     JSONB
);

CREATE INDEX IF NOT EXISTS idx_ar_org_cluster_time
    ON anomaly_records (org_id, cluster_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_ar_service_time
    ON anomaly_records (service, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_ar_severity
    ON anomaly_records (severity);

-- ── Prediction history ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prediction_history (
    id              BIGSERIAL PRIMARY KEY,
    org_id          TEXT        NOT NULL,
    cluster_id      TEXT        NOT NULL,
    service         TEXT        NOT NULL,
    predicted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fp_15m          NUMERIC(5,3),
    fp_30m          NUMERIC(5,3),
    fp_60m          NUMERIC(5,3),
    risk_level      TEXT,
    top_risk_metric TEXT,
    raw_payload     JSONB
);

CREATE INDEX IF NOT EXISTS idx_ph_org_cluster_time
    ON prediction_history (org_id, cluster_id, predicted_at DESC);
CREATE INDEX IF NOT EXISTS idx_ph_service_time
    ON prediction_history (service, predicted_at DESC);

-- ── AI insights log ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_insights (
    id          BIGSERIAL PRIMARY KEY,
    org_id      TEXT        NOT NULL,
    cluster_id  TEXT        NOT NULL,
    query       TEXT        NOT NULL,
    response    TEXT        NOT NULL,
    source      TEXT        NOT NULL,   -- 'ollama' | 'rule_engine'
    context     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Alert records ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_records (
    id          BIGSERIAL PRIMARY KEY,
    org_id      TEXT        NOT NULL,
    cluster_id  TEXT        NOT NULL,
    service     TEXT        NOT NULL,
    alert_type  TEXT        NOT NULL,
    severity    TEXT        NOT NULL,
    message     TEXT,
    resolved    BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- ── Dependency map snapshot ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dependency_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    org_id          TEXT        NOT NULL,
    cluster_id      TEXT        NOT NULL,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    topology_json   JSONB       NOT NULL
);
"""

_TIMESCALE_SQL = """
SELECT create_hypertable(
    'metrics_history', 'recorded_at',
    if_not_exists => TRUE,
    migrate_data   => TRUE
);
SELECT create_hypertable(
    'anomaly_records', 'detected_at',
    if_not_exists => TRUE,
    migrate_data   => TRUE
);
SELECT create_hypertable(
    'prediction_history', 'predicted_at',
    if_not_exists => TRUE,
    migrate_data   => TRUE
);
"""


def _split_sql(sql: str) -> list[str]:
    """Split SQL by semicolons, ignoring those inside -- comments."""
    stmts, buf = [], ""
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buf += line + "\n"
        if ";" in line and not line.strip().startswith("--"):
            stmts.append(buf.strip())
            buf = ""
    if buf.strip():
        stmts.append(buf.strip())
    return [s for s in stmts if s and not s.startswith("--")]


async def init_db(enable_timescale: bool = False) -> None:
    """Create all tables. Call once at application startup."""
    statements = _split_sql(_SCHEMA_SQL)
    async with _engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))
        logger.info("✅ KubeMind schema verified / created.")

        if enable_timescale:
            try:
                timescale_statements = [s.strip() for s in _TIMESCALE_SQL.split(";") if s.strip()]
                for stmt in timescale_statements:
                    await conn.execute(text(stmt))
                logger.info("✅ TimescaleDB hypertables configured.")
            except Exception as e:
                logger.warning(f"TimescaleDB not available on this Neon plan — skipping: {e}")


async def close_db() -> None:
    await _engine.dispose()
    logger.info("Database connection pool closed.")


# ── User & Org helpers ────────────────────────────────────────────────────────

async def get_user_by_email(email: str) -> Optional[Dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, email, name, password_hash, role, org_id FROM users WHERE email = :email"),
            {"email": email}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

async def create_user(user_id: str, email: str, name: str, password_hash: str, role: str, org_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO users (id, email, name, password_hash, role, org_id)
                VALUES (:id, :email, :name, :password_hash, :role, :org_id)
            """),
            {"id": user_id, "email": email, "name": name, "password_hash": password_hash, "role": role, "org_id": org_id}
        )
        await session.commit()

async def create_organization(org_id: str, name: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": org_id, "name": name}
        )
        await session.commit()

async def get_api_key(key_hash: str) -> Optional[Dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT key_hash, cluster_id, org_id FROM api_keys WHERE key_hash = :key_hash"),
            {"key_hash": key_hash}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

async def get_api_key_by_cluster(cluster_id: str) -> Optional[Dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT key_hash, cluster_id, org_id FROM api_keys WHERE cluster_id = :cluster_id"),
            {"cluster_id": cluster_id}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

async def create_api_key(key_hash: str, cluster_id: str, org_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO api_keys (key_hash, cluster_id, org_id) VALUES (:key_hash, :cluster_id, :org_id)"),
            {"key_hash": key_hash, "cluster_id": cluster_id, "org_id": org_id}
        )
        await session.commit()

async def get_cluster_db(cluster_id: str) -> Optional[Dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, name, provider, org_id FROM clusters WHERE id = :id"),
            {"id": cluster_id}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

async def create_cluster_db(cluster_id: str, name: str, provider: str, org_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO clusters (id, name, provider, org_id) VALUES (:id, :name, :provider, :org_id)"),
            {"id": cluster_id, "name": name, "provider": provider, "org_id": org_id}
        )
        await session.commit()

async def delete_cluster_db(cluster_id: str, org_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM clusters WHERE id = :id AND org_id = :org_id"),
            {"id": cluster_id, "org_id": org_id}
        )
        await session.commit()

async def get_clusters_by_org(org_id: str) -> List[Dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, name, provider, org_id FROM clusters WHERE org_id = :org_id"),
            {"org_id": org_id}
        )
        return [dict(row._mapping) for row in result]

async def create_refresh_token(token: str, user_id: str, expires_at: datetime) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO refresh_tokens (token, user_id, expires_at) VALUES (:token, :user_id, :expires_at)"),
            {"token": token, "user_id": user_id, "expires_at": expires_at}
        )
        await session.commit()

async def get_refresh_token(token: str) -> Optional[Dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT token, user_id, expires_at FROM refresh_tokens WHERE token = :token"),
            {"token": token}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

async def delete_refresh_token(token: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM refresh_tokens WHERE token = :token"),
            {"token": token}
        )
        await session.commit()

# ── Repository helpers ────────────────────────────────────────────────────────

async def save_metrics_batch(rows: List[Dict[str, Any]], org_id: str, cluster_id: str) -> None:
    """Persist a batch of metric snapshots."""
    async with AsyncSessionLocal() as session:
        for row in rows:
            await session.execute(
                text("""
                    INSERT INTO metrics_history
                        (org_id, cluster_id, service, namespace, domain, cpu_percent, memory_mb,
                         network_in_kbps, network_out_kbps, disk_usage_pct,
                         error_rate_pct, latency_ms, restart_count, status)
                    VALUES
                        (:org_id, :cluster_id, :service, :namespace, :domain, :cpu_percent, :memory_mb,
                         :network_in_kbps, :network_out_kbps, :disk_usage_pct,
                         :error_rate_pct, :latency_ms, :restart_count, :status)
                """),
                {
                    "org_id":           org_id,
                    "cluster_id":       cluster_id,
                    "service":          row.get("service"),
                    "namespace":        row.get("namespace"),
                    "domain":           row.get("domain"),
                    "cpu_percent":      row.get("cpu_percent"),
                    "memory_mb":        row.get("memory_mb"),
                    "network_in_kbps":  row.get("network_in_kbps"),
                    "network_out_kbps": row.get("network_out_kbps"),
                    "disk_usage_pct":   row.get("disk_usage_percent"),
                    "error_rate_pct":   row.get("error_rate_percent"),
                    "latency_ms":       row.get("latency_ms"),
                    "restart_count":    row.get("restart_count", 0),
                    "status":           row.get("status", "Running"),
                },
            )
        await session.commit()


async def save_anomaly(anomaly: Dict[str, Any], org_id: str, cluster_id: str) -> None:
    """Persist a detected anomaly record."""
    import json
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO anomaly_records
                    (org_id, cluster_id, service, namespace, domain, severity, anomaly_types,
                     detection_method, anomaly_score, confidence, raw_payload)
                VALUES
                    (:org_id, :cluster_id, :service, :namespace, :domain, :severity, :anomaly_types,
                     :detection_method, :anomaly_score, :confidence, :raw_payload)
            """),
            {
                "org_id":           org_id,
                "cluster_id":       cluster_id,
                "service":          anomaly.get("service"),
                "namespace":        anomaly.get("namespace", ""),
                "domain":           anomaly.get("domain", ""),
                "severity":         anomaly.get("severity", "warning"),
                "anomaly_types":    anomaly.get("anomaly_types", []),
                "detection_method": anomaly.get("detection_method", ""),
                "anomaly_score":    anomaly.get("anomaly_score"),
                "confidence":       anomaly.get("confidence"),
                "raw_payload":      json.dumps(anomaly),
            },
        )
        await session.commit()


async def save_prediction(prediction: Dict[str, Any], org_id: str, cluster_id: str) -> None:
    """Persist a prediction snapshot."""
    import json
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO prediction_history
                    (org_id, cluster_id, service, fp_15m, fp_30m, fp_60m, risk_level, top_risk_metric, raw_payload)
                VALUES
                    (:org_id, :cluster_id, :service, :fp_15m, :fp_30m, :fp_60m, :risk_level, :top_risk_metric, :raw_payload)
            """),
            {
                "org_id":           org_id,
                "cluster_id":       cluster_id,
                "service":          prediction.get("service"),
                "fp_15m":           prediction.get("failure_probability_15m"),
                "fp_30m":           prediction.get("failure_probability_30m"),
                "fp_60m":           prediction.get("failure_probability_60m"),
                "risk_level":       prediction.get("risk_level"),
                "top_risk_metric":  prediction.get("top_risk_metric"),
                "raw_payload":      json.dumps(prediction),
            },
        )
        await session.commit()


async def save_ai_insight(query: str, response: str, source: str, org_id: str, cluster_id: str, context: str = "") -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO ai_insights (org_id, cluster_id, query, response, source, context)
                VALUES (:org_id, :cluster_id, :query, :response, :source, :context)
            """),
            {"org_id": org_id, "cluster_id": cluster_id, "query": query, "response": response, "source": source, "context": context},
        )
        await session.commit()


async def get_recent_anomalies(org_id: str, cluster_id: str, limit: int = 50) -> List[Dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT service, namespace, domain, severity, anomaly_types,
                       detection_method, anomaly_score, confidence, detected_at
                FROM   anomaly_records
                WHERE  org_id = :org_id AND cluster_id = :cluster_id
                ORDER  BY detected_at DESC
                LIMIT  :limit
            """),
            {"org_id": org_id, "cluster_id": cluster_id, "limit": limit},
        )
        return [dict(row._mapping) for row in result]


async def get_metrics_history(service: str, org_id: str, cluster_id: str, hours: int = 1) -> List[Dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT cpu_percent, memory_mb, latency_ms, error_rate_pct,
                       restart_count, recorded_at
                FROM   metrics_history
                WHERE  service = :service
                  AND  org_id = :org_id
                  AND  cluster_id = :cluster_id
                  AND  recorded_at >= NOW() - INTERVAL ':hours hours'
                ORDER  BY recorded_at ASC
            """),
            {"service": service, "org_id": org_id, "cluster_id": cluster_id, "hours": hours},
        )
        return [dict(row._mapping) for row in result]


async def save_alert_record(org_id: str, cluster_id: str, service: str, alert_type: str, severity: str, message: str = "") -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO alert_records (org_id, cluster_id, service, alert_type, severity, message)
                VALUES (:org_id, :cluster_id, :service, :alert_type, :severity, :message)
            """),
            {"org_id": org_id, "cluster_id": cluster_id, "service": service,
             "alert_type": alert_type, "severity": severity, "message": message},
        )
        await session.commit()


async def save_topology_snapshot(topology_json: dict, org_id: str, cluster_id: str) -> None:
    import json
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO dependency_snapshots (org_id, cluster_id, topology_json)
                VALUES (:org_id, :cluster_id, :topology_json)
            """),
            {"org_id": org_id, "cluster_id": cluster_id, "topology_json": json.dumps(topology_json)},
        )
        await session.commit()
