from opentelemetry.sdk.metrics import MeterProvider
mp = MeterProvider()
print("Exemplar filter:", mp._exemplar_filter)
