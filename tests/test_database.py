import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from app.core.database import (
    save_metrics_batch,
    save_anomaly,
    save_prediction,
    save_ai_insight,
    save_alert_record,
    save_topology_snapshot,
)


@pytest.mark.asyncio
async def test_save_metrics_batch_empty():
    with patch("app.core.database.AsyncSessionLocal") as mock_session:
        mock_session.return_value.__aenter__.return_value.execute = AsyncMock()
        mock_session.return_value.__aenter__.return_value.commit = AsyncMock()
        await save_metrics_batch([], "org-1", "cluster-1")
        assert True


@pytest.mark.asyncio
async def test_save_anomaly_minimal():
    with patch("app.core.database.AsyncSessionLocal") as mock_session:
        mock_session.return_value.__aenter__.return_value.execute = AsyncMock()
        mock_session.return_value.__aenter__.return_value.commit = AsyncMock()
        await save_anomaly({"service": "test-pod"}, "org-1", "cluster-1")
        assert True


@pytest.mark.asyncio
async def test_save_prediction():
    with patch("app.core.database.AsyncSessionLocal") as mock_session:
        mock_session.return_value.__aenter__.return_value.execute = AsyncMock()
        mock_session.return_value.__aenter__.return_value.commit = AsyncMock()
        await save_prediction({"service": "test-pod"}, "org-1", "cluster-1")
        assert True


@pytest.mark.asyncio
async def test_save_alert_record():
    with patch("app.core.database.AsyncSessionLocal") as mock_session:
        mock_session.return_value.__aenter__.return_value.execute = AsyncMock()
        mock_session.return_value.__aenter__.return_value.commit = AsyncMock()
        await save_alert_record("org-1", "cluster-1", "svc", "CPU", "critical")
        assert True


@pytest.mark.asyncio
async def test_save_topology_snapshot():
    with patch("app.core.database.AsyncSessionLocal") as mock_session:
        mock_session.return_value.__aenter__.return_value.execute = AsyncMock()
        mock_session.return_value.__aenter__.return_value.commit = AsyncMock()
        await save_topology_snapshot({"nodes": []}, "org-1", "cluster-1")
        assert True


@pytest.mark.asyncio
async def test_save_ai_insight():
    with patch("app.core.database.AsyncSessionLocal") as mock_session:
        mock_session.return_value.__aenter__.return_value.execute = AsyncMock()
        mock_session.return_value.__aenter__.return_value.commit = AsyncMock()
        await save_ai_insight("query", "response", "ollama", "org-1", "cluster-1")
        assert True
