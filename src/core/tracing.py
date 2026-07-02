import logging

from fastapi import FastAPI

from core.config import Settings


logger = logging.getLogger(__name__)


def setup_tracing(app: FastAPI, settings: Settings) -> None:
    if not settings.tracing_enabled:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception as exc:
        # Graceful degradation: app should boot even if tracing dependencies are missing or incompatible.
        logger.warning("Tracing is disabled because OpenTelemetry import failed: %s", exc)
        return

    provider = TracerProvider(resource=Resource.create({"service.name": settings.tracing_service_name}))
    trace.set_tracer_provider(provider)
    otlp_exporter = OTLPSpanExporter(
        endpoint=f"http://{settings.jaeger_host}:4317",
        insecure=True,
    )
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
