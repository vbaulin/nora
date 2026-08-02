import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "pico" / "picoclaw.py"
SPEC = importlib.util.spec_from_file_location("picoclaw_proactive_router", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("websockets", types.SimpleNamespace())
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PicoclawProactiveRoutingTest(unittest.TestCase):
    def test_status_refreshes_evidence_before_reading_memory(self):
        with mock.patch.object(MODULE, "_run_skill", side_effect=[
            {"status": "success", "mode": "tick"},
            {"status": "success", "mode": "status", "facts": []},
        ]) as run_skill:
            result = MODULE._proactive_preflight("Què ha après la placa sobre el camp?")

        self.assertEqual(result["route"], "status")
        self.assertEqual(run_skill.call_count, 2)
        self.assertEqual(run_skill.call_args_list[0].args[1]["mode"], "tick")
        self.assertEqual(run_skill.call_args_list[1].args[1]["mode"], "status")

    def test_general_operation_is_drafted_not_written(self):
        with mock.patch.object(MODULE, "_run_skill", return_value={
            "status": "confirmation_required",
            "missing": ["field", "date/time"],
            "written": False,
        }) as run_skill:
            result = MODULE._proactive_preflight("Hem fet la poda avui")

        self.assertEqual(result["route"], "draft_operation")
        params = run_skill.call_args.args[1]
        self.assertEqual(params["mode"], "draft_operation")
        self.assertFalse(params["confirmed"])

    def test_proposal_decision_uses_explicit_reference(self):
        with mock.patch.object(MODULE, "_run_skill", return_value={
            "status": "success", "proposal_id": 42, "decision": "deferred",
        }) as run_skill:
            result = MODULE._proactive_preflight("PF-42: ho deixem per més tard")

        self.assertEqual(result["route"], "record_decision")
        params = run_skill.call_args.args[1]
        self.assertEqual(params["proposal_id"], 42)
        self.assertEqual(params["decision"], "deferred")

    def test_negated_acceptance_fails_closed_to_proposal_context(self):
        with mock.patch.object(MODULE, "_run_skill", return_value={
            "status": "confirmation_required", "proposal_id": 42,
        }) as run_skill:
            result = MODULE._proactive_preflight("PF-42: no accepto")

        self.assertEqual(result["route"], "proposal_context")
        params = run_skill.call_args.args[1]
        self.assertEqual(params["mode"], "proposal_context")
        self.assertNotIn("decision", params)

    def test_conflicting_decision_cues_are_not_persisted(self):
        with mock.patch.object(MODULE, "_run_skill", return_value={
            "status": "confirmation_required", "proposal_id": 42,
        }) as run_skill:
            result = MODULE._proactive_preflight("PF-42: accepto, però més tard")

        self.assertEqual(result["route"], "proposal_context")
        self.assertEqual(run_skill.call_args.args[1]["mode"], "proposal_context")

    def test_proposal_outcome_is_resolved_before_any_decision_write(self):
        with mock.patch.object(MODULE, "_run_skill", return_value={
            "status": "success", "proposal_id": 42,
            "next_route": "farmer-feedback-capture",
        }) as run_skill:
            result = MODULE._proactive_preflight("PF-42: cap símptoma")

        self.assertEqual(result["route"], "proposal_context")
        self.assertEqual(run_skill.call_args.args[1]["mode"], "proposal_context")

    def test_explicit_rejection_is_recorded(self):
        with mock.patch.object(MODULE, "_run_skill", return_value={
            "status": "success", "proposal_id": 42, "decision": "rejected",
        }) as run_skill:
            result = MODULE._proactive_preflight("PF-42: rebutjo la proposta")

        self.assertEqual(result["route"], "record_decision")
        self.assertEqual(run_skill.call_args.args[1]["decision"], "rejected")

    def test_nondecision_proposal_reply_resolves_context_instead_of_memory(self):
        with mock.patch.object(MODULE, "_run_skill", return_value={
            "status": "success",
            "proposal_id": 17,
            "next_route": "proactive-field-agent",
            "next_mode": "draft_operation",
            "written": False,
        }) as run_skill:
            result = MODULE._proactive_preflight(
                "PF-17: el vigor sembla equilibrat"
            )

        self.assertEqual(result["route"], "proposal_context")
        params = run_skill.call_args.args[1]
        self.assertEqual(params["mode"], "proposal_context")
        self.assertEqual(params["raw_text"], "PF-17: el vigor sembla equilibrat")

    def test_treatment_feedback_is_not_a_general_operation(self):
        self.assertFalse(MODULE._general_field_operation_intent_text(
            "He aplicat coure contra el míldiu"
        ))
        self.assertIsNone(MODULE._proactive_preflight(
            "He aplicat coure contra el míldiu"
        ))

    def test_current_evidence_guard_accepts_proactive_skill(self):
        response = MODULE.PicoResponse(tool_calls=[
            MODULE.ToolCall(name="proactive-field-agent", args='{"mode":"status"}')
        ])
        self.assertTrue(MODULE._has_current_vineyard_skill_call(response))


if __name__ == "__main__":
    unittest.main()
