import json

from alert_ai.models import AlertAnalysisResult, AlertGroup
from alert_ai.services.ai import SYSTEM_PROMPT, build_user_message, format_result_for_telegram

payload = {
    "version": "4",
    "groupKey": "test-group-key",
    "status": "firing",
    "receiver": "telegram",
    "truncatedAlerts": 0,
    "groupLabels": {"alertname": "TestAlert"},
    "commonLabels": {"env": "prod"},
    "commonAnnotations": {"runbook": "https://wiki/runbooks/TestAlert"},
    "externalURL": "http://alertmanager:9093",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "TestAlert", "severity": "critical", "env": "prod"},
            "annotations": {"summary": "Test alert", "runbook": "https://wiki/runbooks/TestAlert"},
            "startsAt": "2026-03-25T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "abc123",
            "generatorURL": "http://prometheus:9090",
        }
    ],
}

ag = AlertGroup(**payload)
print("AlertGroup OK, status:", ag.status, "alerts:", len(ag.alerts))

user_msg = build_user_message(ag)
parsed = json.loads(user_msg)
assert "groupKey" in parsed, "groupKey missing from user message"
assert "commonLabels" in parsed, "commonLabels missing from user message"
# env label is in commonLabels so should be stripped from per-alert unique_labels
assert "env" not in (parsed["alerts"][0].get("labels") or {}), \
    "common label 'env' should be stripped from per-alert labels"
# runbook annotation is in commonAnnotations so should be stripped
assert "runbook" not in (parsed["alerts"][0].get("annotations") or {}), \
    "common annotation 'runbook' should be stripped from per-alert annotations"
print("build_user_message OK, length:", len(user_msg), "— common fields deduplicated")

assert len(SYSTEM_PROMPT) > 100, "SYSTEM_PROMPT appears empty"
print("SYSTEM_PROMPT OK, length:", len(SYSTEM_PROMPT))

# Test structured result parsing & formatting
sample_json = json.dumps({
    "priority": "P1",
    "verdict": "PROBLEM",
    "explanation": "High CPU on node-1",
    "actions": ["Check top", "Scale up"],
    "confidence": 0.85,
    "estimated_impact": "1 node degraded",
    "related_runbook": "https://wiki/runbooks/HighCPU",
})
result = AlertAnalysisResult.model_validate_json(sample_json)
assert result.priority == "P1"
assert result.confidence == 0.85
print("AlertAnalysisResult parse OK")

text = format_result_for_telegram(result)
assert "ПРОБЛЕМА" in text
assert "85%" in text
assert "1 node degraded" in text
assert "https://wiki/runbooks/HighCPU" in text
print("format_result_for_telegram OK")

# Test suppress result — no estimated_impact / related_runbook
suppress_json = json.dumps({
    "priority": "P4",
    "verdict": "SUPPRESS",
    "explanation": "Flapping — resolved in 2m",
    "actions": [],
    "confidence": 0.9,
    "estimated_impact": None,
    "related_runbook": None,
})
suppress_result = AlertAnalysisResult.model_validate_json(suppress_json)
assert suppress_result.verdict == "SUPPRESS"
suppress_text = format_result_for_telegram(suppress_result)
assert "ПОДАВИТЬ" in suppress_text
assert "Воздействие" not in suppress_text
assert "Runbook" not in suppress_text
print("Suppress formatting OK")

from alert_ai.app import create_app

app = create_app.__module__
print("create_app module OK:", app)
print("All checks passed.")
