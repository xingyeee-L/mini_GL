from __future__ import annotations

import tempfile
import unittest
import uuid
from dataclasses import asdict
from pathlib import Path

from mini_gl.agent import Action, ActionRequest, DecisionStatus, PolicyEngine, RiskLevel
from mini_gl.storage.sqlite import SQLiteStore

ALL = frozenset(Action)


class AgentPolicyTests(unittest.TestCase):
    def test_permission_is_the_intersection_of_all_four_authorities(self) -> None:
        request = ActionRequest(
            action=Action.SEARCH,
            source_id="source-1",
            user_permissions=ALL,
            agent_permissions=ALL,
            tool_permissions=ALL,
            policy_permissions=frozenset({Action.ANSWER}),
        )
        decision = PolicyEngine().evaluate(request)
        self.assertEqual(decision.status, DecisionStatus.DENY)
        self.assertEqual(decision.reason_code, "permission_intersection")

    def test_read_only_allowed_but_writes_need_idempotency_and_confirmation(self) -> None:
        engine = PolicyEngine()
        read = engine.evaluate(self._request(Action.SHOW_SOURCE))
        self.assertEqual(read.status, DecisionStatus.ALLOW)
        self.assertEqual(read.risk, RiskLevel.READ_ONLY)

        missing_key = engine.evaluate(self._request(Action.PAUSE_SOURCE))
        self.assertEqual(missing_key.status, DecisionStatus.DENY)
        key = str(uuid.uuid4())
        reversible = engine.evaluate(self._request(Action.PAUSE_SOURCE, key=key))
        self.assertEqual(reversible.status, DecisionStatus.ALLOW)
        destructive = engine.evaluate(self._request(Action.REVOKE_SOURCE, key=key))
        self.assertEqual(destructive.status, DecisionStatus.REQUIRE_CONFIRMATION)
        repeated = engine.evaluate(self._request(Action.REVOKE_SOURCE, key=key))
        self.assertEqual(repeated.status, DecisionStatus.REQUIRE_CONFIRMATION)
        self.assertTrue(engine.verify(repeated))

    def test_repeated_decision_has_one_metadata_only_audit_event(self) -> None:
        key = str(uuid.uuid4())
        decision = PolicyEngine().evaluate(self._request(Action.PAUSE_SOURCE, key=key))
        with tempfile.TemporaryDirectory() as temp_dir, SQLiteStore(
            Path(temp_dir) / "state.sqlite3"
        ) as store:
            root = Path(temp_dir) / "source"
            root.mkdir()
            source = store.register_source(root, 1024, 2, frozenset({".txt"}))
            decision = PolicyEngine().evaluate(
                self._request(Action.PAUSE_SOURCE, key=key, source_id=source.source_id)
            )
            values = asdict(decision)
            payload = {
                "event_id": values["event_id"],
                "idempotency_key": values["idempotency_key"],
                "action": decision.action.value,
                "source_id": values["source_id"],
                "decision": decision.status.value,
                "risk": decision.risk.value,
                "reason_code": values["reason_code"],
            }
            self.assertTrue(store.record_agent_decision(**payload))
            self.assertFalse(store.record_agent_decision(**payload))
            row = store.connection.execute("SELECT * FROM agent_action_audit").fetchone()
            self.assertNotIn("content", row.keys())
            self.assertNotIn("prompt", row.keys())

    def test_untrusted_text_cannot_be_supplied_to_policy_as_authority(self) -> None:
        fields = ActionRequest.__dataclass_fields__
        self.assertNotIn("prompt", fields)
        self.assertNotIn("retrieved_content", fields)
        self.assertNotIn("shell", {action.value for action in Action})
        self.assertNotIn("network", {action.value for action in Action})

    @staticmethod
    def _request(
        action: Action, *, key: str | None = None, source_id: str = "source-1"
    ) -> ActionRequest:
        return ActionRequest(
            action=action,
            source_id=source_id,
            user_permissions=ALL,
            agent_permissions=ALL,
            tool_permissions=ALL,
            policy_permissions=ALL,
            idempotency_key=key,
        )
