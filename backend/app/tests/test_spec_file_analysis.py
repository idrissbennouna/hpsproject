# backend/app/tests/test_spec_file_analysis.py
import unittest
from unittest.mock import MagicMock, patch
import io
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.main import app, _process_and_index_pdf
from app.core.agent_graph import rag_spec_retriever_node


class TestSpecFileAnalysis(unittest.TestCase):

    @patch("pdfplumber.open")
    @patch("app.rag.retriever.get_session_vectorstore")
    @patch("app.rag.retriever.batch_add_documents")
    @patch("app.rag.retriever.find_chunks_by_file_hash")
    @patch("app.rag.retriever.delete_session_documents")
    def test_pdf_ingestion_and_hash_dedup(
        self, mock_delete, mock_find_hash, mock_batch_add, mock_get_vs, mock_pdf_open
    ):
        """Vérifie que l'ingestion d'un PDF de spec fonctionne et réutilise le hash si déjà indexé."""
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Spécification PowerCARD Field 039 Code Reponse 00"
        mock_pdf.pages = [mock_page]
        mock_pdf_open.return_value.__enter__.return_value = mock_pdf

        mock_batch_add.return_value = 1
        # First run: not indexed yet
        mock_find_hash.return_value = {"found": False, "existing_chunk_indices": set()}
        res1 = _process_and_index_pdf(b"%PDF-1.4 spec content", "spec_test.pdf", "session_abc")
        self.assertTrue(res1.get("success"), f"res1 failed with: {res1}")
        self.assertFalse(res1["reused"])
        self.assertIn("file_hash", res1)

        # Second run with same file hash: deduplicated / reused
        mock_find_hash.return_value = {"found": True, "existing_chunk_indices": {0}}
        res2 = _process_and_index_pdf(b"%PDF-1.4 spec content", "spec_test.pdf", "session_xyz")
        self.assertTrue(res2["success"])
        self.assertTrue(res2["reused"])

    @patch("app.rag.retriever.get_session_vectorstore")
    def test_rag_spec_retriever_node_merges_uploaded_doc(self, mock_get_vs):
        """Vérifie que rag_spec_retriever_node extrait les règles du PDF téléversé sans interroger la base statique."""
        mock_vs = MagicMock()
        mock_vs.similarity_search.return_value = [
            Document(
                page_content="Exigence spécifique client : Le champ 39 doit valoir 00 en cas de succès.",
                metadata={"source": "spec_client_custom.pdf", "page": 1}
            )
        ]
        mock_get_vs.return_value = mock_vs

        state = {
            "user_prompt": "Vérifie les transactions",
            "file_name": "trace.txt",
            "doc_session_id": "analysis_session_123",
            "log_data_json": '[{"failed_functions": ["AuthProcess"]}]',
            "current_agent": "",
            "rag_context": "",
            "final_response": ""
        }

        res = rag_spec_retriever_node(state)
        rag_context = res.get("rag_context", "")

        self.assertIn("=== DOCUMENT DE SPÉCIFICATION FOURNI POUR CETTE ANALYSE ===", rag_context)
        self.assertIn("spec_client_custom.pdf", rag_context)
        self.assertIn("Le champ 39 doit valoir 00", rag_context)

    @patch("app.main.compliance_agent_app.invoke")
    @patch("app.main._process_and_index_pdf")
    @patch("app.main._generate_reportlab_pdf")
    def test_analyze_logs_endpoint_with_spec_file(self, mock_gen_pdf, mock_process_pdf, mock_agent_invoke):
        """Vérifie que POST /api/v1/logs/analyze accepte à la fois le fichier de trace et la spec PDF."""
        mock_process_pdf.return_value = {
            "success": True,
            "file_hash": "dummyhash123",
            "filename": "custom_spec.pdf",
            "message": "Indexed successfully"
        }
        mock_agent_invoke.return_value = {
            "final_response": "Analyse effectuée avec succès d'après la spec fournie.",
            "current_agent": "ComplianceAuditorAgent"
        }

        client = TestClient(app)

        trace_content = b"2026-07-27 10:00:00 [INFO] AuthProcess failed"
        spec_content = b"%PDF-1.4 custom spec..."

        response = client.post(
            "/api/v1/logs/analyze",
            data={"user_prompt": "Analyse la conformité"},
            files={
                "file": ("trace.txt", io.BytesIO(trace_content), "text/plain"),
                "doc_file": ("custom_spec.pdf", io.BytesIO(spec_content), "application/pdf")
            }
        )

        self.assertEqual(response.status_code, 200)
        mock_process_pdf.assert_called_once()
        mock_agent_invoke.assert_called_once()
        
        passed_inputs = mock_agent_invoke.call_args[0][0]
        self.assertTrue(passed_inputs["doc_session_id"].startswith("analysis_"))


if __name__ == "__main__":
    unittest.main()
