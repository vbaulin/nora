import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "skills" / "farmer_notify" / "run.py"
SENDER_PATH = ROOT / "scripts" / "telegram_outbox_sender.py"
SENDER_SPEC = importlib.util.spec_from_file_location("telegram_outbox_sender_test", SENDER_PATH)
SENDER = importlib.util.module_from_spec(SENDER_SPEC)
SENDER_SPEC.loader.exec_module(SENDER)


class FarmerNotifyTest(unittest.TestCase):
    def test_media_notification_preserves_followup_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = pathlib.Path(tmp) / "plot.png"
            image.write_bytes(b"png-smoke-test")
            message = "Evidence-based report text"
            payload = {
                "title": "Black-rot infection watch",
                "message": message,
                "text_after_photo": message,
                "media": [{"type": "photo", "path": str(image)}],
                "outbox_dir": str(pathlib.Path(tmp) / "outbox"),
            }
            proc = subprocess.run(
                [str(RUNNER)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=True,
            )
            result = json.loads(proc.stdout)
            saved = json.loads(pathlib.Path(result["outbox_json"]).read_text())
            self.assertEqual(saved["telegram"]["method"], "sendPhoto")
            self.assertEqual(saved["telegram"]["text_after_photo"], message)

    def test_three_disease_plots_are_packaged_as_one_media_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = []
            for disease in ("downy_mildew", "powdery_mildew", "black_rot"):
                image = pathlib.Path(tmp) / f"{disease}.png"
                image.write_bytes(f"{disease}-png-smoke-test".encode())
                media.append({
                    "type": "photo",
                    "path": str(image),
                    "disease": disease,
                    "caption": disease,
                })
            proc = subprocess.run(
                [str(RUNNER)],
                input=json.dumps({
                    "title": "Three-disease report",
                    "message": "Current vineyard evidence",
                    "text_after_photo": "Current vineyard evidence",
                    "media": media,
                    "outbox_dir": str(pathlib.Path(tmp) / "outbox"),
                }),
                text=True,
                capture_output=True,
                check=True,
            )
            result = json.loads(proc.stdout)
            saved = json.loads(pathlib.Path(result["outbox_json"]).read_text())
            self.assertEqual(saved["telegram"]["method"], "sendMediaGroup")
            self.assertEqual(len(saved["telegram"]["media"]), 3)
            self.assertEqual(
                {item["disease"] for item in saved["telegram"]["media"]},
                {"downy_mildew", "powdery_mildew", "black_rot"},
            )
            self.assertTrue(all(pathlib.Path(item["path"]).exists() for item in saved["telegram"]["media"]))
            dispatched = SENDER.send_payload(
                result["outbox_json"],
                token="dry-run-token",
                chat_id="1",
                dry_run=True,
                save_status=False,
            )
            self.assertEqual(dispatched["telegram_result"][0]["method"], "sendMediaGroup")
            self.assertEqual(dispatched["telegram_result"][0]["media_count"], 3)


if __name__ == "__main__":
    unittest.main()
