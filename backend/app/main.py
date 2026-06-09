import asyncio
import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.k8s_collector import set_prometheus_url
from app.core.cluster_manager import cluster_manager
from app.services.state import manager, _broadcast_task
from app.services.broadcast import broadcast_loop
from app.core.middleware import RateLimitMiddleware, SecurityMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("kubemind")

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION,
              description="AI-powered real-time Kubernetes observability platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if settings.CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

resource = Resource.create({"service.name": settings.APP_NAME})
tracer_provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(
    endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
    insecure=True,
)
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(tracer_provider)
FastAPIInstrumentor.instrument_app(app)

from app.routers.auth import router as auth_router
from app.routers.clusters import router as clusters_router
from app.routers.websocket import router as ws_router
from app.routers.dashboard import router as dashboard_router
app.include_router(auth_router)
app.include_router(clusters_router)
app.include_router(ws_router)
app.include_router(dashboard_router)

@app.on_event("startup")
async def startup():
    global _broadcast_task
    logger.info("KubeMind AI backend starting...")
    set_prometheus_url(settings.PROMETHEUS_URL)

    if settings.DB_ENABLED:
        from app.core.database import init_db
        await init_db(enable_timescale=settings.TIMESCALE_ENABLED)

    from app.core.event_bus import init_event_bus
    await init_event_bus()

    from app.core.redis_store import bootstrap_from_redis
    await bootstrap_from_redis()

    _broadcast_task = asyncio.create_task(broadcast_loop())

@app.on_event("shutdown")
async def shutdown():
    if _broadcast_task:
        _broadcast_task.cancel()
    from app.core.event_bus import close_event_bus
    await close_event_bus()
    if settings.DB_ENABLED:
        from app.core.database import close_db
        await close_db()
    from app.core.redis_store import close_redis
    await close_redis()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT,
                reload=settings.DEBUG, log_level="info")
