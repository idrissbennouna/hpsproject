import unittest
from unittest.mock import patch, MagicMock

from app.core.agent_graph import rag_spec_retriever_node
from app.services.field_validator import validate_transaction_fields


class TestOptionalSpecAndSessionRAG(unittest.TestCase):

    def test_case_a_no_spec_pdf_attached(self):
        """Test Case A: No spec PDF attached. rag_context must be clear message and no vector queries run."""
        state = {
            "user_prompt": "Analyse ce fichier de traces",
            "doc_session_id": "",
            "log_data_json": '[{"failed_functions": ["GetOriginalAuthData"]}]'
        }

        # Execute rag_spec_retriever_node
        res = rag_spec_retriever_node(state)

        # Assert rag_context is explicit message and static query_specs was NOT called
        self.assertEqual(res["rag_context"], "Aucun document de spécification fourni pour cette analyse.")

        # Test field_validator with no session_id
        sample_fields = {
            "003": {"value": "000000"},
            "011": {"value": "123456"},
            "037": {"value": "402812345678"},
            "039": {"value": "00"}
        }

        # With session_id=None or "", validate_transaction_fields returns [] immediately with 0 embedding calls
        with patch("app.services.field_validator.search_session_chunks_keyword") as mock_search:
            alerts = validate_transaction_fields(sample_fields, session_id="")
            self.assertEqual(alerts, [])
            mock_search.assert_not_called()

    def test_case_b_with_spec_pdf_attached(self):
        """Test Case B: Spec PDF attached. rag_context built strictly from session DB & field lookups deduplicated."""
        state = {
            "user_prompt": "Analyse ce fichier",
            "doc_session_id": "session_test_123",
            "log_data_json": '[{"failed_functions": ["GetOriginalAuthData"]}]'
        }

        mock_doc = MagicMock()
        mock_doc.metadata = {"source": "uploaded_spec.pdf", "page": 5}
        mock_doc.page_content = "Règle ISO8583 : GetOriginalAuthData doit retourner 00."

        mock_vs = MagicMock()
        mock_vs.similarity_search.return_value = [mock_doc]

        with patch("app.rag.retriever.get_session_vectorstore", return_value=mock_vs):
            res = rag_spec_retriever_node(state)

            # Assert similarity_search was called with session_id filter
            mock_vs.similarity_search.assert_called_once_with(
                "GetOriginalAuthData", k=8, filter={"session_id": "session_test_123"}
            )
            self.assertIn("=== DOCUMENT DE SPÉCIFICATION FOURNI POUR CETTE ANALYSE ===", res["rag_context"])
            self.assertIn("uploaded_spec.pdf", res["rag_context"])

        # Test deduplicated field lookups
        sample_fields = {
            "003": {"value": "000000"},
            "011": {"value": "123456"},
            "037": {"value": "402812345678"},
            "039": {"value": "00"}
        }

        with patch("app.services.field_validator.search_session_chunks_keyword", return_value=[]) as mock_keyword:
            alerts = validate_transaction_fields(sample_fields, session_id="session_test_123")
            # Verify search_session_chunks_keyword was called exactly 4 times (1 per unique field), not per transaction
            self.assertEqual(mock_keyword.call_count, 4)


if __name__ == "__main__":
    unittest.main()
