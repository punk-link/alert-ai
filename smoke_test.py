from alert_ai.models import AlertGroup
from alert_ai.services.ai import build_prompt

payload = {
    "version": "4",
    "groupKey": "test-group-key",
    "status": "firing",
    "receiver": "telegram",
    "truncatedAlerts": 0,
    "groupLabels": {"alertname": "TestAlert"},
    "commonLabels": {},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "TestAlert", "severity": "critical"},
            "annotations": {"summary": "Test alert"},
            "startsAt": "2026-03-25T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "abc123",
            "generatorURL": "http://prometheus:9090",
        }
    ],
}

ag = AlertGroup(**payload)
print("AlertGroup OK, status:", ag.status, "alerts:", len(ag.alerts))

prompt = build_prompt(ag)
print("build_prompt OK, length:", len(prompt))

from alert_ai.app import create_app

app = create_app.__module__
print("create_app module OK:", app)
print("All checks passed.")
