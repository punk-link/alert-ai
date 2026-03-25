from pydantic import BaseModel, ConfigDict, Field


class AlertAnalysisResult(BaseModel):
    priority: str
    verdict: str  # "SUPPRESS" or "PROBLEM"
    explanation: str
    actions: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    estimated_impact: str | None = None
    related_runbook: str | None = None


class Alert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    labels: dict
    annotations: dict
    startsAt: str
    endsAt: str | None = None
    fingerprint: str | None = None
    generatorURL: str | None = None


class AlertGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str
    groupKey: str
    status: str
    receiver: str
    groupLabels: dict
    commonLabels: dict
    commonAnnotations: dict
    externalURL: str
    alerts: list[Alert]
