"""Pure authorization decisions for a future local agent executor."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from enum import StrEnum


class Action(StrEnum):
    SEARCH = "search"
    ANSWER = "answer"
    SHOW_SOURCE = "show_source"
    REBUILD_INDEX = "rebuild_index"
    PAUSE_SOURCE = "pause_source"
    RESUME_SOURCE = "resume_source"
    DELETE_DERIVED = "delete_derived"
    REVOKE_SOURCE = "revoke_source"


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    DESTRUCTIVE = "destructive"


class DecisionStatus(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"


RISK_BY_ACTION = {
    Action.SEARCH: RiskLevel.READ_ONLY,
    Action.ANSWER: RiskLevel.READ_ONLY,
    Action.SHOW_SOURCE: RiskLevel.READ_ONLY,
    Action.REBUILD_INDEX: RiskLevel.REVERSIBLE,
    Action.PAUSE_SOURCE: RiskLevel.REVERSIBLE,
    Action.RESUME_SOURCE: RiskLevel.REVERSIBLE,
    Action.DELETE_DERIVED: RiskLevel.DESTRUCTIVE,
    Action.REVOKE_SOURCE: RiskLevel.DESTRUCTIVE,
}


@dataclass(frozen=True, slots=True)
class ActionRequest:
    action: Action
    source_id: str
    user_permissions: frozenset[Action]
    agent_permissions: frozenset[Action]
    tool_permissions: frozenset[Action]
    policy_permissions: frozenset[Action]
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    event_id: str
    action: Action
    source_id: str
    status: DecisionStatus
    risk: RiskLevel
    reason_code: str
    idempotency_key: str | None
    authorization_tag: str


class PolicyEngine:
    """Fail-closed intersection policy; it does not execute tools or parse retrieved content."""

    def __init__(self, authorization_key: bytes | None = None) -> None:
        self._authorization_key = authorization_key or secrets.token_bytes(32)

    def evaluate(self, request: ActionRequest) -> Decision:
        risk = RISK_BY_ACTION[request.action]
        permissions = (
            request.user_permissions
            & request.agent_permissions
            & request.tool_permissions
            & request.policy_permissions
        )
        if request.action not in permissions:
            return self._decision(request, DecisionStatus.DENY, risk, "permission_intersection")
        if risk is not RiskLevel.READ_ONLY and not _valid_idempotency_key(
            request.idempotency_key
        ):
            return self._decision(request, DecisionStatus.DENY, risk, "idempotency_key_required")
        if risk is RiskLevel.DESTRUCTIVE:
            return self._decision(
                request, DecisionStatus.REQUIRE_CONFIRMATION, risk, "human_confirmation_required"
            )
        return self._decision(request, DecisionStatus.ALLOW, risk, "authorized")

    def _decision(
        self,
        request: ActionRequest,
        status: DecisionStatus,
        risk: RiskLevel,
        reason_code: str,
    ) -> Decision:
        stable_key = request.idempotency_key or "read-only"
        operation = f"{stable_key}\0{request.action}\0{request.source_id}"
        payload = f"{operation}\0{status}\0{risk}\0{reason_code}"
        event_id = hashlib.sha256(payload.encode()).hexdigest()
        tag = hmac.new(self._authorization_key, payload.encode(), hashlib.sha256).hexdigest()
        return Decision(
            event_id=event_id,
            action=request.action,
            source_id=request.source_id,
            status=status,
            risk=risk,
            reason_code=reason_code,
            idempotency_key=request.idempotency_key,
            authorization_tag=tag,
        )

    def verify(self, decision: Decision) -> bool:
        stable_key = decision.idempotency_key or "read-only"
        payload = (
            f"{stable_key}\0{decision.action}\0{decision.source_id}\0{decision.status}"
            f"\0{decision.risk}\0{decision.reason_code}"
        )
        expected_event = hashlib.sha256(payload.encode()).hexdigest()
        expected_tag = hmac.new(
            self._authorization_key, payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(decision.event_id, expected_event) and hmac.compare_digest(
            decision.authorization_tag, expected_tag
        )


def _valid_idempotency_key(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False
