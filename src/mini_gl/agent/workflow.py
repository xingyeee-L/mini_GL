"""Metadata-only action workflow; no real tool executor is connected."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from mini_gl.agent.policy import RISK_BY_ACTION, Decision, DecisionStatus, PolicyEngine, RiskLevel
from mini_gl.storage.sqlite import SQLiteStore


class WorkflowState(StrEnum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    READY = "ready"
    SIMULATING = "simulating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPENSATED = "compensated"


@dataclass(frozen=True, slots=True)
class PreparedWorkflow:
    workflow_id: str
    state: WorkflowState
    confirmation_token: str | None = None


class ActionWorkflow:
    """Enforces transitions for dry-run action metadata only."""

    def __init__(
        self,
        store: SQLiteStore,
        policy: PolicyEngine,
        *,
        now: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.policy = policy
        self.now = now or (lambda: datetime.now(UTC))
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE agent_action_workflows SET state=?,failure_code=?,updated_at=? "
                "WHERE state=?",
                (
                    WorkflowState.FAILED.value,
                    "INTERRUPTED_SIMULATION",
                    self.now().isoformat(),
                    WorkflowState.SIMULATING.value,
                ),
            )

    def prepare(self, decision: Decision, *, ttl_seconds: int = 300) -> PreparedWorkflow:
        if decision.status is DecisionStatus.DENY:
            raise ValueError("Denied decisions cannot create workflows")
        if not self.policy.verify(decision):
            raise ValueError("Decision authorization proof is invalid")
        if RISK_BY_ACTION[decision.action] is not decision.risk:
            raise ValueError("Decision risk does not match the fixed action policy")
        self.store.get_source(decision.source_id)
        if decision.risk is RiskLevel.READ_ONLY or decision.idempotency_key is None:
            raise ValueError("Only keyed write-like decisions use the action workflow")
        if not 1 <= ttl_seconds <= 900:
            raise ValueError("Confirmation TTL must be between 1 and 900 seconds")
        existing = self.store.connection.execute(
            "SELECT workflow_id,state FROM agent_action_workflows "
            "WHERE idempotency_key=? AND action=? AND source_id=?",
            (decision.idempotency_key, decision.action.value, decision.source_id),
        ).fetchone()
        if existing is not None:
            return PreparedWorkflow(existing["workflow_id"], WorkflowState(existing["state"]))

        workflow_id = str(uuid.uuid4())
        token: str | None = None
        token_hash: str | None = None
        expires_at: str | None = None
        if decision.status is DecisionStatus.REQUIRE_CONFIRMATION:
            state = WorkflowState.AWAITING_CONFIRMATION
            token = self.token_factory()
            token_hash = _hash_token(token)
            expires_at = (self.now() + timedelta(seconds=ttl_seconds)).isoformat()
        else:
            state = WorkflowState.READY
        created_at = self.now().isoformat()
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO agent_action_workflows VALUES(?,?,?,?,?,?,?,?,NULL,NULL,?,?)",
                (
                    workflow_id,
                    decision.idempotency_key,
                    decision.action.value,
                    decision.source_id,
                    decision.risk.value,
                    state.value,
                    token_hash,
                    expires_at,
                    created_at,
                    created_at,
                ),
            )
        return PreparedWorkflow(workflow_id, state, token)

    def confirm(self, workflow_id: str, token: str) -> WorkflowState:
        row = self._get(workflow_id)
        if row["state"] != WorkflowState.AWAITING_CONFIRMATION.value:
            raise RuntimeError("Workflow is not awaiting confirmation")
        expiry = datetime.fromisoformat(row["confirmation_expires_at"])
        if self.now() >= expiry:
            raise RuntimeError("Confirmation ticket expired")
        if not hmac.compare_digest(row["confirmation_hash"], _hash_token(token)):
            raise RuntimeError("Confirmation ticket is invalid")
        with self.store.connection:
            cursor = self.store.connection.execute(
                "UPDATE agent_action_workflows SET state=?,confirmation_hash=NULL,"
                "confirmation_expires_at=NULL,updated_at=? WHERE workflow_id=? AND state=?",
                (
                    WorkflowState.READY.value,
                    self.now().isoformat(),
                    workflow_id,
                    WorkflowState.AWAITING_CONFIRMATION.value,
                ),
            )
        if cursor.rowcount != 1:
            raise RuntimeError("Invalid workflow transition")
        return WorkflowState.READY

    def start_simulation(self, workflow_id: str) -> WorkflowState:
        return self._transition(workflow_id, WorkflowState.READY, WorkflowState.SIMULATING)

    def complete_simulation(self, workflow_id: str) -> WorkflowState:
        return self._transition(workflow_id, WorkflowState.SIMULATING, WorkflowState.SUCCEEDED)

    def fail_simulation(self, workflow_id: str, failure_code: str) -> WorkflowState:
        code = _safe_code(failure_code)
        with self.store.connection:
            cursor = self.store.connection.execute(
                "UPDATE agent_action_workflows SET state=?,failure_code=?,updated_at=? "
                "WHERE workflow_id=? AND state=?",
                (
                    WorkflowState.FAILED.value,
                    code,
                    self.now().isoformat(),
                    workflow_id,
                    WorkflowState.SIMULATING.value,
                ),
            )
        if cursor.rowcount != 1:
            raise RuntimeError("Invalid workflow transition")
        return WorkflowState.FAILED

    def compensate(self, workflow_id: str, compensation_code: str) -> WorkflowState:
        code = _safe_code(compensation_code)
        with self.store.connection:
            cursor = self.store.connection.execute(
                "UPDATE agent_action_workflows SET state=?,compensation_code=?,updated_at=? "
                "WHERE workflow_id=? AND state=?",
                (
                    WorkflowState.COMPENSATED.value,
                    code,
                    self.now().isoformat(),
                    workflow_id,
                    WorkflowState.FAILED.value,
                ),
            )
        if cursor.rowcount != 1:
            raise RuntimeError("Invalid workflow transition")
        return WorkflowState.COMPENSATED

    def _transition(
        self, workflow_id: str, current: WorkflowState, target: WorkflowState
    ) -> WorkflowState:
        with self.store.connection:
            cursor = self.store.connection.execute(
                "UPDATE agent_action_workflows SET state=?,updated_at=? "
                "WHERE workflow_id=? AND state=?",
                (target.value, self.now().isoformat(), workflow_id, current.value),
            )
        if cursor.rowcount != 1:
            raise RuntimeError("Invalid workflow transition")
        return target

    def _get(self, workflow_id: str) -> sqlite3.Row:
        row = self.store.connection.execute(
            "SELECT * FROM agent_action_workflows WHERE workflow_id=?", (workflow_id,)
        ).fetchone()
        if row is None:
            raise KeyError("Unknown action workflow")
        if not isinstance(row, sqlite3.Row):
            raise RuntimeError("Action workflow storage returned an invalid row")
        return row


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _safe_code(value: str) -> str:
    if not value or len(value) > 64 or not value.replace("_", "").isalnum():
        raise ValueError("Status code must be 1-64 alphanumeric/underscore characters")
    return value
