import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "pico" / "picoclaw.py"
SPEC = importlib.util.spec_from_file_location("picoclaw_orchestrator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("websockets", types.SimpleNamespace())
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PicoclawBlackRotRoutingTest(unittest.TestCase):
    def test_explicit_black_rot_plot_uses_only_black_rot_skill(self):
        payload = {
            "status": "success",
            "send_text": "Black-rot report",
            "media": [{
                "type": "photo",
                "path": "/tmp/black_rot.png",
                "disease": "black_rot",
            }],
        }
        with mock.patch.object(MODULE, "_run_skill", return_value=payload) as run_skill:
            response = MODULE._direct_vineyard_plot_response("Show the plot of black rot")

        self.assertIsNotNone(response)
        run_skill.assert_called_once()
        skill_name, params = run_skill.call_args.args
        self.assertEqual(skill_name, "black-rot-risk")
        self.assertEqual(params["mode"], "report")
        self.assertNotIn("board_only", params)
        self.assertEqual(response.payload["media"][0]["disease"], "black_rot")
        self.assertEqual(response.tool_calls[0].name, "black-rot-risk")

    def test_generic_vineyard_plot_keeps_combined_report(self):
        payload = {"status": "success", "send_text": "Combined report"}
        with mock.patch.object(MODULE, "_run_skill", return_value=payload) as run_skill:
            response = MODULE._direct_vineyard_plot_response("Show the vineyard risk plots")

        self.assertIsNotNone(response)
        skill_name, params = run_skill.call_args.args
        self.assertEqual(skill_name, "daily-vineyard-briefing")
        self.assertEqual(params["mode"], "both_disease_report")
        self.assertTrue(params["board_only"])

    def test_explicit_mildew_plots_use_one_disease_only(self):
        cases = (
            ("Mostra el gràfic de míldiu", "downy_mildew"),
            ("Mostra el gràfic d'oïdi", "powdery_mildew"),
            ("Show the powdery mildew plot", "powdery_mildew"),
        )
        for question, disease in cases:
            with self.subTest(question=question):
                payload = {
                    "status": "success",
                    "send_text": disease,
                    "media": [{"type": "photo", "path": f"/tmp/{disease}.png", "disease": disease}],
                }
                with mock.patch.object(MODULE, "_run_skill", return_value=payload) as run_skill:
                    response = MODULE._direct_vineyard_plot_response(question)
                skill_name, params = run_skill.call_args.args
                self.assertEqual(skill_name, "daily-vineyard-briefing")
                self.assertEqual(params["mode"], "single_disease_report")
                self.assertEqual(params["disease"], disease)
                self.assertEqual(response.payload["media"][0]["disease"], disease)

    def test_black_rot_names_are_recognized_in_supported_languages(self):
        for text in (
            "black rot",
            "Guignardia bidwellii",
            "Phyllosticta ampelicida",
        ):
            with self.subTest(text=text):
                self.assertTrue(MODULE._black_rot_intent_text(text))

    def test_unqualified_local_rot_name_requires_clarification(self):
        for text in ("podridura negra", "podredumbre negra"):
            with self.subTest(text=text):
                self.assertTrue(MODULE._ambiguous_rot_intent_text(text))
                self.assertFalse(MODULE._black_rot_intent_text(text))

    def test_secondary_bunch_rot_is_not_mapped_to_guignardia_model(self):
        for text in (
            "Podridures secundàries per Aspergillus niger",
            "secondary bunch rot caused by Penicillium",
            "podredumbre secundaria por Cladosporium",
        ):
            with self.subTest(text=text):
                self.assertFalse(MODULE._black_rot_intent_text(text))

    def test_comparison_question_requires_clarification(self):
        text = "És podridura secundària per Aspergillus o black rot per Guignardia bidwellii?"
        self.assertTrue(MODULE._ambiguous_rot_intent_text(text))
        self.assertFalse(MODULE._black_rot_intent_text(text))

    def test_orchestrated_prompt_does_not_request_mildew_plots_for_black_rot(self):
        prompt = MODULE._build_orchestrated_question(
            "Mostra el gràfic del Black rot de la vinya per Guignardia bidwellii"
        )
        route = prompt.rsplit("## Deterministic Vineyard Route", 1)[1]
        route = route.split("## User Request", 1)[0]
        self.assertIn("`black-rot-risk`", route)
        self.assertIn("Do not attach downy-mildew or powdery-mildew plots", route)
        self.assertNotIn('"mode":"both_disease_report"', route)

    def test_ambiguous_rot_prompt_does_not_run_a_disease_model(self):
        prompt = MODULE._build_orchestrated_question(
            "Quan dius podridura negra, és Aspergillus o Guignardia?"
        )
        route = prompt.rsplit("## Deterministic Rot Clarification Route", 1)[1]
        route = route.split("## User Request", 1)[0]
        self.assertIn("`vineyard-model-explainer`", route)
        self.assertIn('"disease":"rot_clarification"', route)
        self.assertIn("Do not call the Guignardia model", route)

    def test_direct_ambiguous_plot_request_returns_question_without_media(self):
        payload = {
            "status": "needs_clarification",
            "send_text": "Et refereixes a Guignardia o a podridures secundàries?",
        }
        with mock.patch.object(MODULE, "_run_skill", return_value=payload) as run_skill:
            response = MODULE._direct_rot_clarification_response(
                "Mostra el gràfic de podridura negra"
            )

        self.assertIsNotNone(response)
        run_skill.assert_called_once()
        skill_name, params = run_skill.call_args.args
        self.assertEqual(skill_name, "vineyard-model-explainer")
        self.assertEqual(params["disease"], "rot_clarification")
        self.assertEqual(response.payload["media"], [])
        self.assertEqual(response.payload["telegram"]["method"], "sendMessage")

    def test_orchestrated_prompt_isolates_explicit_mildew_disease(self):
        prompt = MODULE._build_orchestrated_question("Mostra el gràfic d'oïdi")
        route = prompt.rsplit("## Deterministic Vineyard Route", 1)[1]
        route = route.split("## User Request", 1)[0]
        self.assertIn('"mode":"single_disease_report"', route)
        self.assertIn('"disease":"powdery_mildew"', route)
        self.assertIn("only the requested disease", route)


if __name__ == "__main__":
    unittest.main()
