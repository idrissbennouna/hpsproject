import unittest
from unittest.mock import patch, MagicMock
from app.services.field_validator import validate_transaction_fields

class TestFieldAnalysisFix(unittest.TestCase):
    def test_validation_non_numeric_characters_in_numeric_field(self):
        # PAN (002) is a numeric field. If it has characters, it should return an alert.
        sample_fields = {
            "002": {"value": "12345a789"}
        }
        # Call validate_transaction_fields with no session_id (should fallback to standard fields)
        alerts = validate_transaction_fields(sample_fields, session_id=None)
        
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["field_number"], "002")
        self.assertEqual(alert["field_name"], "Primary Account Number (PAN)")
        self.assertEqual(alert["expected_type"], "N")
        self.assertEqual(alert["source"], "Standard ISO 8583")
        self.assertEqual(alert["observed_value"], "12345a789")
        self.assertIn("contient des lettres/symboles non conformes (attendu numérique)", alert["non_conformity_type"])
        self.assertIn("Champ Primary Account Number (PAN) (FLD 002)", alert["message"])
        self.assertIn("type attendu 19 N", alert["message"])
        self.assertIn("valeur observée '12345a789'", alert["message"])

    def test_validation_empty_values(self):
        # Empty field should return "Champ absent de la trace"
        sample_fields = {
            "003": {"value": ""}
        }
        alerts = validate_transaction_fields(sample_fields, session_id=None)
        
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["field_number"], "003")
        self.assertEqual(alert["observed_value"], "(vide)")
        self.assertEqual(alert["non_conformity_type"], "Champ absent de la trace")
        self.assertIn("Champ Processing Code (FLD 003)", alert["message"])
        self.assertIn("valeur observée '(vide)'", alert["message"])
        self.assertIn("Champ absent de la trace", alert["message"])

    def test_correct_keys_returned(self):
        sample_fields = {
            "011": {"value": "12345a"}  # STAN should be numeric
        }
        alerts = validate_transaction_fields(sample_fields, session_id=None)
        
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        expected_keys = {
            "field_number",
            "field_name",
            "value",
            "observed_value",
            "expected_type",
            "expected_type_label",
            "attributes",
            "source",
            "source_file",
            "non_conformity_type",
            "message"
        }
        for key in expected_keys:
            self.assertIn(key, alert)

if __name__ == "__main__":
    unittest.main()
