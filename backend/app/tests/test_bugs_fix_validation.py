# backend/app/tests/test_bugs_fix_validation.py
import unittest
from unittest.mock import patch, MagicMock

from app.rag.retriever import extract_code_tokens, query_command_code
from app.core.validation_agent_graph import _filter_session_trace_content


class TestBugsFixValidation(unittest.TestCase):

    def test_extract_code_tokens_variations(self):
        """Vérifie l'extraction de codes de commande et de réponse selon diverses formulations."""
        self.assertEqual(extract_code_tokens("à quelle commande correspond le code de réponse 'ED'"), ["ED"])
        self.assertEqual(extract_code_tokens("réponse ED"), ["ED"])
        self.assertEqual(extract_code_tokens("la commande EC est-elle valide ?"), ["EC"])
        self.assertEqual(extract_code_tokens("commande dont la réponse est CB"), ["CB"])
        self.assertIn("ED", extract_code_tokens("vérifier l'erreur ED01 et la commande ED"))

    def test_query_command_code_bidirectional_ec_ed(self):
        """Vérifie que query_command_code('ED') retrouve bien la commande EC."""
        docs = query_command_code("ED", limit=5)
        self.assertGreater(len(docs), 0, "query_command_code('ED') doit retourner des documents")
        first_doc = docs[0]
        self.assertIn("EC", first_doc.metadata.get("command_code", ""))
        self.assertEqual("ED", first_doc.metadata.get("response_code", ""))
        self.assertIn("CORRESPONDANCE RAG", first_doc.page_content)

    def test_filter_session_trace_content_preserves_whole_transactions(self):
        """Vérifie que le filtrage ne découpe pas une transaction en plein milieu et indique le ratio exact."""
        tx_blocks = []
        for i in range(1, 13):
            tx_blocks.append(
                f"=== Transaction {i} ===\n"
                f"STAN: {1000+i} | PAN: 400000******1234 | ID: TX_{i}\n"
                f"Payload detail line 1 for transaction {i}\n"
                f"Payload detail line 2 for transaction {i}\n"
                f"Payload detail line 3 for transaction {i}\n"
                f"Alertes: {'ED01 détecté dans TO HSM' if i in [3, 8] else 'Aucune'}"
            )
        raw_trace = "\n\n".join(tx_blocks)

        filtered = _filter_session_trace_content(raw_trace, "combien de fois l'erreur ED01 apparaît", max_chars=1000)
        self.assertNotIn("[... suite de la transaction tronquée ...]", filtered)
        self.assertIn("AVERTISSEMENT TRONCATURAGE DE CONTEXTE", filtered)
        self.assertIn("transactions complètes", filtered)
        self.assertIn("ED01", filtered)

    def test_exact_counting_across_full_trace(self):
        """Vérifie le comptage exact du terme ED01 sur une trace à 12 transactions."""
        tx_blocks = []
        for i in range(1, 13):
            tx_blocks.append(
                f"=== Transaction {i} ===\n"
                f"STAN: {1000+i}\n"
                f"Alertes: {'Erreur ED01 dans échange HSM' if i in [3, 8] else 'Aucune'}"
            )
        raw_trace = "\n\n".join(tx_blocks)
        
        occurrences = raw_trace.count("ED01")
        self.assertEqual(occurrences, 2)

        matched_txs = [f"#{idx}" for idx, b in enumerate(raw_trace.split("=== Transaction ")[1:], 1) if "ED01" in b]
        self.assertEqual(matched_txs, ["#3", "#8"])


if __name__ == "__main__":
    unittest.main()
