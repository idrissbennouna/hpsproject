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

    def test_field_010_resolves_via_standard_never_session(self):
        """
        BUG 1 — REGRESSION TEST : FLD 010 (Conversion Rate, Cardholder Billing)
        doit TOUJOURS être résolu via le référentiel ISO 8583 standard (8 N),
        JAMAIS via une recherche dans un document de session (PDF HSM ou autre),
        même si ce PDF contient une mention "Field 010" dans un contexte différent.
        """
        # Cas 1 : valeur conforme → aucune alerte, pas d'appel RAG
        with patch("app.services.field_validator.search_session_chunks_keyword") as mock_search:
            alerts = validate_transaction_fields(
                {"010": {"value": "61000000"}},  # 8 chiffres = valide pour 8 N
                session_id="session_with_hsm_pdf"  # session avec un PDF payShield
            )
            # search_session_chunks_keyword ne doit JAMAIS être appelé pour un champ standard
            mock_search.assert_not_called()

        # Cas 2 : valeur non conforme → alerte avec source "Standard ISO 8583", jamais "document de session"
        with patch("app.services.field_validator.search_session_chunks_keyword") as mock_search:
            alerts = validate_transaction_fields(
                {"010": {"value": "ABC"}},  # lettres dans un champ numérique → non-conforme
                session_id="session_with_hsm_pdf"
            )
            mock_search.assert_not_called()
            self.assertEqual(len(alerts), 1)
            alert = alerts[0]
            self.assertEqual(alert["field_number"], "010")
            self.assertEqual(alert["field_name"], "Conversion Rate, Cardholder Billing")
            self.assertEqual(alert["expected_type"], "N")
            self.assertEqual(alert["source"], "Standard ISO 8583")
            self.assertEqual(alert["source_file"], "Standard ISO 8583")
            # Le type attendu doit être 8 N (norme ISO 8583), jamais 3 ANS (payShield HSM)
            self.assertEqual(alert["attributes"], "8 N")
            self.assertIn("contient des lettres/symboles non conformes", alert["non_conformity_type"])

    def test_standard_fields_never_use_rag(self):
        """
        Tous les champs ISO 8583 standard (002, 003, 004, 007, 009, 010, 011, 012, 022...)
        ne doivent jamais déclencher une recherche RAG dans le document de session.
        """
        standard_fields = {
            "002": {"value": "4111111111111111"},
            "003": {"value": "000000"},
            "004": {"value": "000000010000"},
            "007": {"value": "0806101500"},
            "010": {"value": "61000000"},
            "011": {"value": "593604"},
            "012": {"value": "101500"},
            "022": {"value": "051"},
            "039": {"value": "00"},
        }
        with patch("app.services.field_validator.search_session_chunks_keyword") as mock_search:
            validate_transaction_fields(standard_fields, session_id="session_any_pdf")
            mock_search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
