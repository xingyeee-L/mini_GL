from __future__ import annotations

import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mini_gl.agent import (
    Action,
    ActionRequest,
    ActionWorkflow,
    DecisionStatus,
    PolicyEngine,
    WorkflowState,
)
from mini_gl.storage.sqlite import SQLiteStore

ALL = frozenset(Action)


class AgentWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.temp.name) / "state.sqlite3")
        self.now = datetime(2026, 1, 1, tzinfo=UTC)
        self.workflow = ActionWorkflow(
            self.store, now=lambda: self.now, token_factory=lambda: "one-time-ticket"
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_confirmation_ticket_is_bound_hashed_and_single_transition(self) -> None:
        decision = self._decision(Action.REVOKE_SOURCE, confirmed=False)
        self.assertEqual(decision.status, DecisionStatus.REQUIRE_CONFIRMATION)
        prepared = self.workflow.prepare(decision, ttl_seconds=60)
        self.assertEqual(prepared.state, WorkflowState.AWAITING_CONFIRMATION)
        self.assertEqual(prepared.confirmation_token, "one-time-ticket")
        row = self.store.connection.execute("SELECT * FROM agent_action_workflows").fetchone()
        self.assertNotEqual(row["confirmation_hash"], "one-time-ticket")
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            self.workflow.confirm(prepared.workflow_id, "wrong")
        self.assertEqual(
            self.workflow.confirm(prepared.workflow_id, "one-time-ticket"), WorkflowState.READY
        )
        with self.assertRaisesRegex(RuntimeError, "not awaiting"):
            self.workflow.confirm(prepared.workflow_id, "one-time-ticket")

    def test_expired_ticket_fails_closed(self) -> None:
        prepared = self.workflow.prepare(
            self._decision(Action.DELETE_DERIVED, confirmed=False), ttl_seconds=1
        )
        self.now += timedelta(seconds=2)
        with self.assertRaisesRegex(RuntimeError, "expired"):
            self.workflow.confirm(prepared.workflow_id, "one-time-ticket")

    def test_failure_can_be_compensated_but_state_cannot_be_skipped(self) -> None:
        prepared = self.workflow.prepare(self._decision(Action.PAUSE_SOURCE, confirmed=True))
        with self.assertRaisesRegex(RuntimeError, "Invalid"):
            self.workflow.complete_simulation(prepared.workflow_id)
        self.assertEqual(
            self.workflow.start_simulation(prepared.workflow_id), WorkflowState.SIMULATING
        )
        self.assertEqual(
            self.workflow.fail_simulation(prepared.workflow_id, "INJECTED_FAILURE"),
            WorkflowState.FAILED,
        )
        self.assertEqual(
            self.workflow.compensate(prepared.workflow_id, "RESTORED_PRIOR_STATE"),
            WorkflowState.COMPENSATED,
        )
        with self.assertRaisesRegex(RuntimeError, "Invalid"):
            self.workflow.compensate(prepared.workflow_id, "DUPLICATE")

    def test_same_idempotency_key_returns_same_workflow_without_new_ticket(self) -> None:
        decision = self._decision(Action.REVOKE_SOURCE, confirmed=False)
        first = self.workflow.prepare(decision)
        second = self.workflow.prepare(decision)
        self.assertEqual(first.workflow_id, second.workflow_id)
        self.assertIsNone(second.confirmation_token)
        count = self.store.connection.execute(
            "SELECT COUNT(*) FROM agent_action_workflows"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def _decision(self, action: Action, *, confirmed: bool):
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"test:{action}"))
        return PolicyEngine().evaluate(
            ActionRequest(
                action=action,
                source_id="source-1",
                user_permissions=ALL,
                agent_permissions=ALL,
                tool_permissions=ALL,
                policy_permissions=ALL,
                idempotency_key=key,
                human_confirmation=confirmed,
            )
        )
