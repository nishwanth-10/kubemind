"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="viewer"),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("token"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "clusters",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "api_keys",
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key_hash"),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "metrics_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("cpu_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("memory_mb", sa.Integer(), nullable=True),
        sa.Column("network_in_kbps", sa.Numeric(10, 2), nullable=True),
        sa.Column("network_out_kbps", sa.Numeric(10, 2), nullable=True),
        sa.Column("disk_usage_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("error_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("latency_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("restart_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", "recorded_at"),
        postgresql_partition_by="RANGE (recorded_at)",
    )
    op.create_index("idx_mh_org_cluster_time", "metrics_history",
                    ["org_id", "cluster_id", sa.text("recorded_at DESC")])
    op.create_index("idx_mh_service_time", "metrics_history",
                    ["service", sa.text("recorded_at DESC")])
    op.create_table(
        "anomaly_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("anomaly_types", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("detection_method", sa.Text(), nullable=False),
        sa.Column("anomaly_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 3), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ar_org_cluster_time", "anomaly_records",
                    ["org_id", "cluster_id", sa.text("detected_at DESC")])
    op.create_index("idx_ar_service_time", "anomaly_records",
                    ["service", sa.text("detected_at DESC")])
    op.create_index("idx_ar_severity", "anomaly_records", ["severity"])
    op.create_table(
        "prediction_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("predicted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("fp_15m", sa.Numeric(5, 3), nullable=True),
        sa.Column("fp_30m", sa.Numeric(5, 3), nullable=True),
        sa.Column("fp_60m", sa.Numeric(5, 3), nullable=True),
        sa.Column("risk_level", sa.Text(), nullable=True),
        sa.Column("top_risk_metric", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ph_org_cluster_time", "prediction_history",
                    ["org_id", "cluster_id", sa.text("predicted_at DESC")])
    op.create_index("idx_ph_service_time", "prediction_history",
                    ["service", sa.text("predicted_at DESC")])
    op.create_table(
        "ai_insights",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "alert_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("alert_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "dependency_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("topology_json", postgresql.JSONB, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("dependency_snapshots")
    op.drop_table("alert_records")
    op.drop_table("ai_insights")
    op.drop_table("prediction_history")
    op.drop_table("anomaly_records")
    op.drop_table("metrics_history")
    op.drop_table("api_keys")
    op.drop_table("clusters")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("organizations")
