import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.tracing import (
    SERVICE_LAYER_GATEWAY,
    SERVICE_LAYER_STORAGE,
    current_trace_id,
    force_flush_traces,
    get_tracer,
    set_common_span_attributes,
)


SMOKE_RUN_ID = "trace_smoke_001"


def main() -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("trace_smoke.eval_run") as root_span:
        root_span.set_attribute("eval.run_id", SMOKE_RUN_ID)
        trace_id = current_trace_id()

        with tracer.start_as_current_span("gateway.trace_smoke") as span:
            set_common_span_attributes(
                span=span,
                layer=SERVICE_LAYER_GATEWAY,
                run_id=SMOKE_RUN_ID,
                trace_id=trace_id,
            )
            span.set_attribute("smoke.test", True)

        with tracer.start_as_current_span("storage.trace_smoke") as span:
            set_common_span_attributes(
                span=span,
                layer=SERVICE_LAYER_STORAGE,
                run_id=SMOKE_RUN_ID,
                trace_id=trace_id,
            )
            span.set_attribute("smoke.test", True)

    force_flush_traces()
    print(f"emitted_trace_smoke_run_id={SMOKE_RUN_ID}")
    print(f"trace_id={trace_id}")


if __name__ == "__main__":
    main()
