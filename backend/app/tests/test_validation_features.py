# backend/app/tests/test_validation_features.py
import unittest
from unittest.mock import MagicMock, patch
import io

from app.core.config import MAX_UPLOAD_SIZE_BYTES, MAX_PDF_PAGES, EMBEDDING_BATCH_SIZE
from app.rag.retriever import batch_add_documents
from app.main import _process_and_index_pdf, app
from app.core.validation_agent_graph import retriever_node


class TestValidationFeatures(unittest.TestCase):

    def test_batch_add_documents(self):
        """Vérifie que batch_add_documents ingère par lots et réessaie en cas d'échec."""
        mock_db = MagicMock()
        mock_docs = [MagicMock() for _ in range(120)]
        
        # Test batching simple (120 docs avec batch_size=50 -> 3 lots: 50, 50, 20)
        with patch("time.sleep", return_value=None):
            batch_add_documents(mock_db, mock_docs, batch_size=50, inter_batch_delay=0)
        self.assertEqual(mock_db.add_documents.call_count, 3)

    def test_batch_add_documents_retry(self):
        """Vérifie le retry avec backoff sur échec temporaire 429 d'un lot."""
        mock_db = MagicMock()
        # Faire échouer la première tentative suite à 429 puis réussir
        mock_db.add_documents.side_effect = [Exception("429 RESOURCE_EXHAUSTED"), None]
        mock_docs = [MagicMock() for _ in range(10)]
        
        with patch("time.sleep", return_value=None):
            batch_add_documents(mock_db, mock_docs, batch_size=50, max_retries=3, initial_delay=0.01, inter_batch_delay=0)
        self.assertEqual(mock_db.add_documents.call_count, 2)


    @patch("pdfplumber.open")
    @patch("app.rag.retriever.delete_session_documents")
    def test_scanned_pdf_detection(self, mock_delete_docs, mock_pdfplumber_open):
        """Vérifie que les PDF scannés/sans texte retournent un message clair sans succès."""
        # Simuler un PDF de 5 pages dont toutes les pages retournent "" (scanné)
        mock_pdf = MagicMock()
        pages = []
        for _ in range(5):
            page = MagicMock()
            page.extract_text.return_value = ""
            pages.append(page)
        mock_pdf.pages = pages
        mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf

        res = _process_and_index_pdf(b"%PDF-1.4...", "scanned.pdf", "session_123")
        
        self.assertFalse(res["success"])
        self.assertIn("Aucun texte extractible", res["message"])
        mock_delete_docs.assert_called_once_with("session_123")


    @patch("app.core.validation_agent_graph.query_specs", return_value="")
    @patch("app.rag.retriever.get_session_vectorstore")
    @patch("app.core.validation_agent_graph.get_session_files")
    def test_broad_query_intent_k_tuning(self, mock_get_session_files, mock_get_vectorstore, mock_query_specs):
        """Vérifie que k augmente de 4 à 16 pour les requêtes de résumé/vue d'ensemble."""
        mock_get_session_files.return_value = [{"name": "spec.pdf", "is_rag": True, "content": ""}]
        mock_db = MagicMock()
        mock_db.similarity_search.return_value = []
        mock_get_vectorstore.return_value = mock_db

        # 1. Question spécifique -> k=4
        state_specific = {
            "user_question": "Quelle est la valeur du champ 039 ?",
            "session_id": "sess_1",
            "chat_history": []
        }
        retriever_node(state_specific)
        mock_db.similarity_search.assert_called_with("Quelle est la valeur du champ 039 ?", k=4, filter={"session_id": "sess_1"})

        # 2. Question globale / résumé -> k=16
        state_broad = {
            "user_question": "Résume-moi l'ensemble de ce document",
            "session_id": "sess_1",
            "chat_history": []
        }
        retriever_node(state_broad)
        mock_db.similarity_search.assert_called_with("Résume-moi l'ensemble de ce document", k=16, filter={"session_id": "sess_1"})

    @patch("app.core.validation_agent_graph.query_specs", return_value="")
    @patch("app.rag.retriever.get_session_vectorstore")
    @patch("app.core.validation_agent_graph.get_session_files")
    def test_session_id_isolation(self, mock_get_session_files, mock_get_vectorstore, mock_query_specs):
        """Vérifie que les recherches de session A n'incluent jamais les chunks de session B."""
        mock_get_session_files.side_effect = lambda session_id: [
            {"name": f"doc_{session_id}.pdf", "is_rag": True, "content": ""}
        ]
        mock_db = MagicMock()
        mock_get_vectorstore.return_value = mock_db

        doc_a = MagicMock()
        doc_a.metadata = {"session_id": "session_A", "page": 1}
        doc_a.page_content = "Session A content"

        mock_db.similarity_search.return_value = [doc_a]

        state_a = {
            "user_question": "Quelles sont les spécifications ?",
            "session_id": "session_A",
            "chat_history": []
        }
        res_a = retriever_node(state_a)

        mock_db.similarity_search.assert_called_with("Quelles sont les spécifications ?", k=4, filter={"session_id": "session_A"})
        self.assertIn("Session A content", res_a["rag_context"])

    @patch("app.rag.retriever.delete_session_documents")
    def test_batch_add_documents_quota_exhausted(self, mock_delete_docs):
        """Vérifie la levée de QuotaExhaustedError et la conservation des chunks déjà indexés en cas de quota épuisé."""
        from app.rag.retriever import QuotaExhaustedError
        mock_db = MagicMock()
        mock_db.add_documents.side_effect = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded")
        mock_docs = [MagicMock() for _ in range(10)]

        with patch("time.sleep", return_value=None):
            with self.assertRaises(QuotaExhaustedError):
                batch_add_documents(mock_db, mock_docs, batch_size=5, max_retries=2, initial_delay=0.01, inter_batch_delay=0, session_id="test_sess_429")

        mock_delete_docs.assert_not_called()

    @patch("app.core.validation_agent_graph.query_specs", return_value="")
    @patch("app.rag.retriever.get_session_vectorstore")
    @patch("app.core.validation_agent_graph.get_session_files")
    @patch("app.rag.retriever.search_session_chunks_keyword")
    def test_hybrid_field_keyword_search(self, mock_keyword_search, mock_get_session_files, mock_get_vectorstore, mock_query_specs):
        """Vérifie que la présence de 'Field 37' dans la question déclenche la recherche ILIKE directe."""
        mock_get_session_files.return_value = [{"name": "spec.pdf", "is_rag": True, "content": ""}]
        mock_db = MagicMock()
        mock_db.similarity_search.return_value = []
        mock_get_vectorstore.return_value = mock_db

        doc_field = MagicMock()
        doc_field.metadata = {"session_id": "sess_f37", "page": 12}
        doc_field.page_content = "Field 37 - Retrieval Reference Number definition"
        mock_keyword_search.return_value = [doc_field]

        state = {
            "user_question": "Quelle est la définition du Field 37 ?",
            "session_id": "sess_f37",
            "chat_history": []
        }
        res = retriever_node(state)

        mock_keyword_search.assert_called()
        self.assertIn("Field 37 - Retrieval Reference Number definition", res["rag_context"])



if __name__ == "__main__":
    unittest.main()


