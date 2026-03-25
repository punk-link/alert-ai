from pydantic import BaseModel, ConfigDict


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
