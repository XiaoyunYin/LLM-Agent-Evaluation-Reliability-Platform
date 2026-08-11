import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)


SERVICE_NAME = "llm-eval-regression-platform"
TRACER_NAME = "backend.app"
SERVICE_LAYER_GATEWAY = "gateway"
SERVICE_LAYER_RETRIEVAL = "retrieval"
SERVICE_LAYER_PROVIDER = "provider"
SERVICE_LAYER_JUDGE = "judge"
SERVICE_LAYER_TOOL = "tool"
SERVICE_LAYER_STORAGE = "storage"
OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
OTLP_INSECURE_ENV = "OTEL_EXPORTER_OTLP_INSECURE"

_tracing_configured = False


def configure_tracing(service_name: str = SERVICE_NAME) -> None:
    global _tracing_configured

    if _tracing_configured:
        return

    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name})
    )
    otlp_endpoint = os.getenv(OTLP_ENDPOINT_ENV)

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        except ImportError as error:
            raise RuntimeError(
                "OTLP tracing is configured, but "
                "opentelemetry-exporter-otlp-proto-grpc is not installed."
            ) from error

        insecure = os.getenv(OTLP_INSECURE_ENV, "true").strip().lower() == "true"
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=otlp_endpoint,
                    insecure=insecure,
                )
            )
        )
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracing_configured = True


def get_tracer():
    configure_tracing()
    return trace.get_tracer(TRACER_NAME)


def current_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()

    if not span_context.is_valid:
        return None

    return format_trace_id(span_context.trace_id)


def format_trace_id(trace_id: int) -> str:
    return f"{trace_id:032x}"


def set_common_span_attributes(
    span,
    layer: str,
    run_id: str,
    trace_id: str | None = None,
) -> None:
    span.set_attribute("service.layer", layer)
    span.set_attribute("eval.run_id", run_id)

    if trace_id:
        span.set_attribute("eval.trace_id", trace_id)


def force_flush_traces(timeout_millis: int = 30_000) -> bool:
    provider = trace.get_tracer_provider()

    if not hasattr(provider, "force_flush"):
        return False

    return provider.force_flush(timeout_millis=timeout_millis)
