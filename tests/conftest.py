from datetime import datetime, timedelta, timezone
import pytest


@pytest.fixture
def request_factory():
    def make(values=None, **config):
        values = [100.0] * 70 if values is None else values
        return {"schema_version": "1.0", "datasets": [{"id": "series", "timestamps": [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat() for i in range(len(values))], "values": values, "frequency": "1d"}], "config": {"max_runtime_seconds": 120, **config}}
    return make
