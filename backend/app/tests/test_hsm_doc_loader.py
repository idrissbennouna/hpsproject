# backend/app/tests/test_hsm_doc_loader.py
import unittest

from app.services.hsm_doc_loader import (
    parse_hsm_code,
    extract_hsm_code_from_text,
    lookup_hsm_documentation,
)


class TestHsmDocLoader(unittest.TestCase):
    def test_parse_numeric_and_ed05(self):
        p = parse_hsm_code("05")
        self.assertEqual(p["error_number"], "05")
        self.assertEqual(p["lookup_key"], "05")

        p2 = parse_hsm_code("ED05")
        self.assertEqual(p2["response_code"], "ED")
        self.assertEqual(p2["error_number"], "05")
        self.assertEqual(p2["command_code"], "EC")

    def test_extract_from_alert_text(self):
        alert = "Erreur HSM détectée : Code d'erreur HSM 05."
        self.assertEqual(extract_hsm_code_from_text(alert), "05")

        step = "Code Résultat HSM (HsmResultCode) : 99"
        self.assertEqual(extract_hsm_code_from_text(step), "99")

    def test_placeholder_lookup_found(self):
        # Doit au minimum trouver le placeholder même sans RAG/PDF
        result = lookup_hsm_documentation("05")
        self.assertTrue(result["found"])
        self.assertIsNotNone(result.get("placeholder"))
        self.assertIn("05", result["placeholder"]["title"] + result.get("code", ""))

    def test_ed_maps_to_ec(self):
        result = lookup_hsm_documentation("ED")
        self.assertTrue(result["found"])
        self.assertEqual(result.get("command_code"), "EC")
        self.assertEqual(result.get("response_code"), "ED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
