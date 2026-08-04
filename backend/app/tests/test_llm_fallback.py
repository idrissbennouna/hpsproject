import unittest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage

from app.core.config import LLM_FALLBACK_CHAIN
from app.services.llm_util import (
    invoke_llm_with_retry,
    _estimate_token_count,
    _adapt_inputs_for_model,
    GeminiOverloadedError,
    GeminiQuotaExhaustedError,
    LLMOverloadedError,
    LLMQuotaExhaustedError,
)


class TestLLMFallback(unittest.TestCase):

    def test_config_fallback_chain_structure(self):
        """Vérifie que LLM_FALLBACK_CHAIN contient les modèles Gemini avec max_context_tokens."""
        self.assertTrue(len(LLM_FALLBACK_CHAIN) >= 2)
        providers = [item["provider"] for item in LLM_FALLBACK_CHAIN]
        self.assertIn("gemini", providers)
        self.assertNotIn("groq", providers)
        for item in LLM_FALLBACK_CHAIN:
            self.assertIn("max_context_tokens", item)
            self.assertGreater(item["max_context_tokens"], 0)

    def test_token_estimation_and_truncation(self):
        """Vérifie l'estimation des tokens et le tronquage adaptatif du payload."""
        short_prompt = "Ceci est une question courte."
        self.assertLess(_estimate_token_count(short_prompt), 100)

        # Créer un gros prompt de ~10,000 caractères (~2500 tokens)
        large_log_data = "LINE LOG DATA EXAMPLE " * 500
        inputs_dict = {
            "user_prompt": "Analyse ces logs.",
            "log_data_json": large_log_data
        }

        # Demander une adaptation pour une limite stricte de 1000 tokens (80% = 800 tokens)
        adapted, should_skip, new_tokens = _adapt_inputs_for_model(
            inputs_dict,
            max_context_tokens=1000,
            model_name="gemini-3.5-flash"
        )

        self.assertFalse(should_skip)
        self.assertLessEqual(new_tokens, 800)
        self.assertIn("PAYLOAD_TRUNCATED", adapted["log_data_json"])

    @patch("app.services.llm_util.ChatGoogleGenerativeAI")
    def test_fallback_on_503_success_on_second_model(self, mock_chat_cls):
        """
        Vérifie que si le premier modèle (gemini-3.5-flash) renvoie une erreur 503,
        le système bascule immédiatement sur le modèle suivant (gemini-3.6-flash)
        et réussit.
        """
        primary_mock = MagicMock()
        primary_mock.invoke.side_effect = Exception("503 Service Unavailable: High Demand")

        secondary_response = AIMessage(content="Réponse du modèle de secours gemini-3.6-flash")
        secondary_response.response_metadata = {}
        secondary_mock = MagicMock()
        secondary_mock.invoke.return_value = secondary_response

        def side_effect(**kwargs):
            model = kwargs.get("model")
            if model == "gemini-3.5-flash":
                return primary_mock
            elif model == "gemini-3.6-flash":
                return secondary_mock
            return secondary_mock

        mock_chat_cls.side_effect = side_effect

        dummy_llm = MagicMock()
        dummy_llm.model = "gemini-3.5-flash"
        dummy_llm.temperature = 0.0
        dummy_llm.google_api_key = "fake_key"

        response = invoke_llm_with_retry(
            dummy_llm,
            "User question",
            max_retries_per_model=1,
            fallback_chain=["gemini-3.5-flash", "gemini-3.6-flash"]
        )

        self.assertEqual(response.content, "Réponse du modèle de secours gemini-3.6-flash")
        self.assertEqual(response.response_metadata.get("model_used"), "gemini-3.6-flash")
        primary_mock.invoke.assert_called_once()
        secondary_mock.invoke.assert_called_once()

    @patch("app.services.llm_util.ChatGoogleGenerativeAI")
    def test_fallback_on_404_not_found_skips_immediately(self, mock_chat_cls):
        """
        Vérifie que si le modèle renvoie 404 NOT_FOUND (déprécié), il est sauté immédiatement
        sans retries sur ce modèle.
        """
        deprecated_mock = MagicMock()
        deprecated_mock.invoke.side_effect = Exception("404 NOT_FOUND: This model is no longer available to new users.")

        valid_response = AIMessage(content="Réponse du modèle GA valide")
        valid_response.response_metadata = {}
        valid_mock = MagicMock()
        valid_mock.invoke.return_value = valid_response

        def side_effect(**kwargs):
            model = kwargs.get("model")
            if model == "gemini-3.5-flash":
                return deprecated_mock
            return valid_mock

        mock_chat_cls.side_effect = side_effect

        dummy_llm = MagicMock()
        dummy_llm.model = "gemini-3.5-flash"

        response = invoke_llm_with_retry(
            dummy_llm,
            "User question",
            max_retries_per_model=3,
            fallback_chain=["gemini-3.5-flash", "gemini-3.6-flash"]
        )

        self.assertEqual(response.content, "Réponse du modèle GA valide")
        self.assertEqual(response.response_metadata.get("model_used"), "gemini-3.6-flash")
        self.assertEqual(deprecated_mock.invoke.call_count, 1, "Une erreur 404 ne doit pas être retentée !")
        valid_mock.invoke.assert_called_once()

    @patch("app.services.llm_util.ChatGoogleGenerativeAI")
    def test_fallback_raises_overloaded_error_when_all_models_fail(self, mock_chat_cls):
        """
        Vérifie que si TOUS les modèles Gemini échouent sur des 503,
        GeminiOverloadedError / LLMOverloadedError est levée.
        """
        gemini_mock = MagicMock()
        gemini_mock.invoke.side_effect = Exception("503 Service Unavailable: High Demand")
        mock_chat_cls.return_value = gemini_mock

        dummy_llm = MagicMock()
        dummy_llm.model = "gemini-3.5-flash"

        with self.assertRaises(GeminiOverloadedError):
            invoke_llm_with_retry(
                dummy_llm,
                "User question",
                max_retries_per_model=1,
                fallback_chain=[
                    {"provider": "gemini", "model": "gemini-3.5-flash"},
                    {"provider": "gemini", "model": "gemini-3.6-flash"}
                ]
            )

    @patch("app.services.llm_util.ChatGoogleGenerativeAI")
    def test_fallback_raises_quota_error_when_all_models_429(self, mock_chat_cls):
        """
        Vérifie que si TOUS les modèles échouent avec 429, GeminiQuotaExhaustedError / LLMQuotaExhaustedError est levée.
        """
        gemini_mock = MagicMock()
        gemini_mock.invoke.side_effect = Exception("429 ResourceExhausted: Quota exceeded")
        mock_chat_cls.return_value = gemini_mock

        dummy_llm = MagicMock()
        dummy_llm.model = "gemini-3.5-flash"

        with self.assertRaises(GeminiQuotaExhaustedError):
            invoke_llm_with_retry(
                dummy_llm,
                "User question",
                max_retries_per_model=1,
                fallback_chain=[
                    {"provider": "gemini", "model": "gemini-3.5-flash"},
                    {"provider": "gemini", "model": "gemini-3.6-flash"}
                ]
            )

    def test_safe_truncate_json_string_preserves_valid_json(self):
        """Vérifie que le tronquage d'un tableau JSON conserve une syntaxe JSON valide et lisible."""
        import json
        from app.services.llm_util import _safe_truncate_json_string

        items = [{"id": i, "name": f"Transaction {i}", "data": "X" * 100} for i in range(50)]
        json_str = json.dumps(items)
        self.assertGreater(len(json_str), 5000)

        # Tronquer à une taille max de 1000 caractères
        truncated = _safe_truncate_json_string(json_str, target_len=1000, model_name="gemini-3.5-flash")

        # La sortie doit être du JSON valide sans exception lors du loads()
        parsed = json.loads(truncated)
        self.assertIsInstance(parsed, list)
        self.assertGreater(len(parsed), 0)
        self.assertLess(len(parsed), 50)


if __name__ == "__main__":
    unittest.main()
