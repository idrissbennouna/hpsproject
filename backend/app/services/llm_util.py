import json
import os
import time
import logging
from typing import List, Dict, Any, Optional, Union, Tuple
from google.api_core.exceptions import ResourceExhausted, NotFound
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from pydantic import SecretStr

from app.core.config import LLM_FALLBACK_CHAIN, GEMINI_MODEL_FALLBACK_CHAIN, GEMINI_MAX_RETRIES_PER_MODEL

logger = logging.getLogger("llm_util")


class LLMOverloadedError(Exception):
    """Exception levée lorsque tous les modèles/fournisseurs de la chaîne de fallback sont surchargés (503 Service Unavailable)."""
    pass


class LLMQuotaExhaustedError(Exception):
    """Exception levée lorsque les quotas de tous les fournisseurs de la chaîne de fallback sont épuisés (429)."""
    pass


# Aliases de compatibilité pour conserver les exceptions attrapées dans main.py
GeminiOverloadedError = LLMOverloadedError
GeminiQuotaExhaustedError = LLMQuotaExhaustedError


def _estimate_token_count(data: Any) -> int:
    """
    Calcule une estimation approximative du nombre de tokens sans dépendance externe (~4 caractères par token).
    """
    if data is None:
        return 0
    if isinstance(data, str):
        return max(1, len(data) // 4)
    if isinstance(data, (list, tuple)):
        return sum(_estimate_token_count(item) for item in data)
    if isinstance(data, dict):
        return sum(_estimate_token_count(v) for v in data.values())
    if hasattr(data, "content"):
        return _estimate_token_count(getattr(data, "content", ""))
    return max(1, len(str(data)) // 4)


def _safe_truncate_json_string(json_str: str, target_len: int, model_name: str) -> str:
    """
    Tronque une chaîne textuelle ou JSON (ex: log_data_json) en préservant une structure JSON valide si possible.
    """
    cleaned = json_str.strip()
    if (cleaned.startswith("[") and cleaned.endswith("]")) or (cleaned.startswith("{") and cleaned.endswith("}")):
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                # Binary search du sous-ensemble maximal de transactions qui rentre dans target_len
                low, high = 0, len(data)
                best = data
                while low <= high:
                    mid = (low + high) // 2
                    subset = data[:mid]
                    test_str = json.dumps(subset, ensure_ascii=False)
                    if len(test_str) <= target_len:
                        best = subset
                        low = mid + 1
                    else:
                        high = mid - 1
                return json.dumps(best, ensure_ascii=False)
            elif isinstance(data, dict):
                truncated_dict = dict(data)
                for k, v in truncated_dict.items():
                    if isinstance(v, list) and len(v) > 0:
                        truncated_dict[k] = v[:max(1, len(v) // 2)]
                test_str = json.dumps(truncated_dict, ensure_ascii=False)
                if len(test_str) <= target_len:
                    return test_str
                return json.dumps(truncated_dict, ensure_ascii=False)[:target_len]
        except Exception:
            pass

    # Fallback pour texte brut : découpage sur fin de ligne pour éviter de hacher le milieu d'un mot
    raw_slice = json_str[:target_len]
    last_newline = raw_slice.rfind("\n")
    if last_newline > 200:
        raw_slice = raw_slice[:last_newline]
    return raw_slice + f"\n\n[PAYLOAD_TRUNCATED: Troncature appliquée pour le modèle {model_name}]"


def _adapt_inputs_for_model(
    inputs: Any,
    max_context_tokens: int,
    model_name: str
) -> Tuple[Any, bool, int]:
    """
    Vérifie si le prompt dépasse la marge de sécurité (80% du max_context_tokens).
    Si nécessaire, tronque la variable la plus volumineuse du prompt (ex: log data / RAG context).
    Retourne (inputs_adaptés, should_skip, tokens_estimés).
    """
    initial_tokens = _estimate_token_count(inputs)
    safe_token_limit = int(max_context_tokens * 0.8)

    if initial_tokens <= safe_token_limit:
        return inputs, False, initial_tokens

    # Le prompt dépasse la marge de sécurité -> Tronquage ciblé
    excess_tokens = initial_tokens - safe_token_limit
    excess_chars = excess_tokens * 4

    logger.warning(
        f"[PAYLOAD_TRUNCATED] Prompt too large for '{model_name}' "
        f"({initial_tokens} tokens > limit {safe_token_limit}). "
        f"Truncating log data to fit before retry."
    )

    if isinstance(inputs, dict):
        adapted = dict(inputs)
        # Trouver la clé textuelle la plus longue
        longest_key = None
        longest_len = 0
        for k, v in adapted.items():
            if isinstance(v, str) and len(v) > longest_len:
                longest_len = len(v)
                longest_key = k

        if longest_key and longest_len > excess_chars + 200:
            target_len = max(200, longest_len - excess_chars - 300)
            adapted[longest_key] = _safe_truncate_json_string(adapted[longest_key], target_len, model_name)
            new_tokens = _estimate_token_count(adapted)
            return adapted, False, new_tokens
        else:
            # Tronquage impossible car données utiles trop petites
            logger.warning(
                f"[PAYLOAD_TOO_LARGE] Truncation would destroy too much payload data for '{model_name}' "
                f"({initial_tokens} tokens vs limit {max_context_tokens}). Skipping model."
            )
            return inputs, True, initial_tokens

    elif isinstance(inputs, list):
        adapted = list(inputs)
        # Trouver le message avec le contenu le plus long
        longest_idx = -1
        longest_len = 0
        for i, item in enumerate(adapted):
            content = getattr(item, "content", item if isinstance(item, str) else "")
            if isinstance(content, str) and len(content) > longest_len:
                longest_len = len(content)
                longest_idx = i

        if longest_idx >= 0 and longest_len > excess_chars + 200:
            target_len = max(200, longest_len - excess_chars - 300)
            orig_text = str(getattr(adapted[longest_idx], "content", adapted[longest_idx]))
            truncated_text = _safe_truncate_json_string(orig_text, target_len, model_name)
            if hasattr(adapted[longest_idx], "content"):
                from copy import copy
                new_msg = copy(adapted[longest_idx])
                new_msg.content = truncated_text
                adapted[longest_idx] = new_msg
            else:
                adapted[longest_idx] = truncated_text

            new_tokens = _estimate_token_count(adapted)
            return adapted, False, new_tokens
        else:
            logger.warning(
                f"[PAYLOAD_TOO_LARGE] Truncation would destroy too much payload data for '{model_name}' "
                f"({initial_tokens} tokens vs limit {max_context_tokens}). Skipping model."
            )
            return inputs, True, initial_tokens

    elif isinstance(inputs, str):
        if len(inputs) > excess_chars + 200:
            target_len = max(200, len(inputs) - excess_chars - 300)
            adapted_str = _safe_truncate_json_string(inputs, target_len, model_name)
            return adapted_str, False, _estimate_token_count(adapted_str)

    logger.warning(
        f"[PAYLOAD_TOO_LARGE] Truncation would destroy too much payload data for '{model_name}' "
        f"({initial_tokens} tokens vs limit {max_context_tokens}). Skipping model."
    )
    return inputs, True, initial_tokens


class ChatGroq(BaseChatModel):
    """
    Client LangChain réutilisable pour le fournisseur Groq.
    Groq est utilisé comme fournisseur de secours pour contourner les limitations de quota quotidiennes de Gemini.
    """
    model: str
    temperature: float = 0.0
    groq_api_key: Optional[str] = None
    max_retries: int = 1
    max_tokens: int = 4096
    response_format: Optional[Dict[str, Any]] = None

    @property
    def _llm_type(self) -> str:
        return "groq"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        from groq import Groq
        key = (self.groq_api_key or os.getenv("GROQ_API_KEY", "")).strip()
        if not key:
            raise ValueError("GROQ_API_KEY non configurée dans les variables d'environnement.")

        client = Groq(api_key=key)

        formatted_messages = []
        for msg in messages:
            role = "user"
            msg_type = getattr(msg, "type", "human")
            if msg_type in ("system", "developer"):
                role = "system"
            elif msg_type in ("ai", "assistant"):
                role = "assistant"

            content = getattr(msg, "content", str(msg))
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, str):
                        text_parts.append(block)
                    elif isinstance(block, dict):
                        text_parts.append(block.get("text", str(block)))
                    else:
                        text_parts.append(str(block))
                content = "\n".join(text_parts)

            formatted_messages.append({"role": role, "content": str(content)})

        completion_params = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        resp_fmt = self.response_format or kwargs.get("response_format")
        if resp_fmt:
            completion_params["response_format"] = resp_fmt

        response = client.chat.completions.create(**completion_params)

        content_text = response.choices[0].message.content or ""

        usage_meta = {}
        if hasattr(response, "usage") and response.usage:
            usage_meta = {
                "input_tokens": getattr(response.usage, "prompt_tokens", 0),
                "output_tokens": getattr(response.usage, "completion_tokens", 0),
                "total_tokens": getattr(response.usage, "total_tokens", 0),
            }

        ai_message = AIMessage(
            content=content_text,
            response_metadata={
                "model_used": self.model,
                "provider": "groq",
                "token_usage": usage_meta,
            },
            usage_metadata=usage_meta if usage_meta else None
        )

        return ChatResult(generations=[ChatGeneration(message=ai_message)])


def _extract_llm_and_prefix(chain_or_llm: Any):
    """
    Extrait l'instance LLM de base ainsi que le préfixe de chaîne (Runnable) le cas échéant.
    """
    if hasattr(chain_or_llm, "steps"):
        steps_val = getattr(chain_or_llm, "steps")
        if isinstance(steps_val, (list, tuple)) and len(steps_val) > 0:
            base_llm = steps_val[-1]
            prefix_steps = list(steps_val[:-1])
            if len(prefix_steps) == 1:
                prefix = prefix_steps[0]
            elif prefix_steps:
                from functools import reduce
                prefix = reduce(lambda a, b: a | b, prefix_steps)
            else:
                prefix = None
            return base_llm, prefix

    return chain_or_llm, None


def _normalize_fallback_chain(fallback_chain: Optional[Union[List[str], List[Dict[str, Any]]]]) -> List[Dict[str, Any]]:
    """
    Normalise la structure de la chaîne de fallback en une liste de dicts avec 'provider', 'model', et 'max_context_tokens'.
    """
    if fallback_chain is None:
        return list(LLM_FALLBACK_CHAIN)

    normalized = []
    for item in fallback_chain:
        if isinstance(item, dict):
            provider = item.get("provider", "gemini").lower()
            model = item.get("model", "")
            max_tokens = item.get("max_context_tokens", 1000000)
            normalized.append({
                "provider": provider,
                "model": model,
                "max_context_tokens": max_tokens
            })
        elif isinstance(item, str):
            item_str = item.strip()
            normalized.append({
                "provider": "gemini",
                "model": item_str,
                "max_context_tokens": 1000000
            })
    return normalized


def invoke_llm_with_retry(
    chain_or_llm: Any,
    inputs: Any,
    max_retries_per_model: int = GEMINI_MAX_RETRIES_PER_MODEL,
    fallback_chain: Optional[Union[List[str], List[Dict[str, Any]]]] = None
) -> Any:
    """
    Invoque un modèle ou une chaîne LangChain avec une logique de retry rapide, tronquage de payload, et fallback Gemini.
    
    Référence documentation officielle :
    - Gemini: https://ai.google.dev/gemini-api/docs/models
    """
    normalized_chain = _normalize_fallback_chain(fallback_chain)
    base_llm, prefix_runnable = _extract_llm_and_prefix(chain_or_llm)

    # Récupération des paramètres de configuration du modèle de départ
    if base_llm:
        raw_model = getattr(base_llm, "model", None) or getattr(base_llm, "model_name", None)
        primary_model = raw_model if isinstance(raw_model, str) and raw_model else normalized_chain[0]["model"]

        raw_temp = getattr(base_llm, "temperature", 0.0)
        temperature = raw_temp if isinstance(raw_temp, (float, int)) else 0.0

        api_key = getattr(base_llm, "google_api_key", None)
        primary_provider = "gemini"
        primary_limit = 1000000
    else:
        primary_model = normalized_chain[0]["model"]
        primary_provider = normalized_chain[0]["provider"]
        primary_limit = normalized_chain[0].get("max_context_tokens", 1000000)
        temperature = 0.0
        api_key = None

    # Construction de la séquence ordonnée d'entrées (provider, model, max_context_tokens)
    chain_sequence = [{
        "provider": primary_provider,
        "model": primary_model,
        "max_context_tokens": primary_limit
    }]
    for entry in normalized_chain:
        if not (entry["provider"] == primary_provider and entry["model"] == primary_model):
            chain_sequence.append(entry)

    last_error = None
    last_err_str = ""
    current_provider = None

    for idx, entry in enumerate(chain_sequence):
        provider = entry["provider"]
        model_name = entry["model"]
        max_context_tokens = entry.get("max_context_tokens", 1000000)

        if current_provider is not None and provider != current_provider:
            logger.warning(
                f"[PROVIDER_FALLBACK] Modèle {current_provider} indisponible. "
                f"Bascule vers {provider} ({model_name})."
            )
        current_provider = provider

        # Adaptation et tronquage adaptatif du payload en fonction des limites du modèle
        adapted_inputs, should_skip, approx_tokens = _adapt_inputs_for_model(
            inputs,
            max_context_tokens,
            model_name
        )

        if should_skip:
            logger.warning(
                f"[PAYLOAD_TOO_LARGE] Le prompt ({approx_tokens} tokens) dépasse la capacité utilisable de '{model_name}' "
                f"({max_context_tokens} tokens). Saut direct du modèle."
            )
            continue

        # Création du client LLM Gemini
        try:
            llm_kwargs = {
                "model": model_name,
                "temperature": temperature,
                "max_retries": max_retries_per_model,
            }
            if api_key:
                llm_kwargs["google_api_key"] = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
            current_llm = ChatGoogleGenerativeAI(**llm_kwargs)

            current_runnable = (prefix_runnable | current_llm) if prefix_runnable else current_llm
        except Exception as init_err:
            logger.warning(f"[MODEL_FALLBACK_INIT_ERR] Échec d'initialisation du modèle '{model_name}' ({provider}): {init_err}")
            current_runnable = chain_or_llm

        # Tentative d'invocation sur le modèle courant
        for attempt in range(max_retries_per_model):
            try:
                response = current_runnable.invoke(adapted_inputs)

                # Attachement des métadonnées du modèle effectif
                if hasattr(response, "response_metadata") and isinstance(response.response_metadata, dict):
                    response.response_metadata["model_used"] = model_name
                    response.response_metadata["provider"] = provider
                    response.response_metadata["prompt_tokens_est"] = approx_tokens

                if idx > 0:
                    logger.info(f"[MODEL_FALLBACK_SUCCESS] La requête a été traitée avec succès par le modèle de secours '{model_name}' ({provider}).")

                return response

            except Exception as e:
                last_error = e
                last_err_str = str(e).lower()
                
                # Logging ultra-détaillé de l'erreur brute pour diagnostic (TPM vs RPM vs RPD)
                err_msg_detail = getattr(e, "message", str(e))
                err_details = getattr(e, "details", None)
                logger.error(
                    f"[LLM_CALL_ERROR] Modèle '{model_name}' (Essai {attempt+1}/{max_retries_per_model}) : "
                    f"Type={type(e).__name__} | Repr={repr(e)} | Message={err_msg_detail} | Details={err_details}"
                )

                # 1. Détection modèle déprécié / indisponible définitivement (404 NOT_FOUND)
                is_not_found = (
                    isinstance(e, NotFound) or
                    "404" in last_err_str or
                    "not_found" in last_err_str or
                    "no longer available" in last_err_str or
                    "not found" in last_err_str
                )

                # 2. Détection surcharge temporaire serveur (503 Service Unavailable / High Demand)
                is_overloaded = (
                    "503" in last_err_str or
                    "unavailable" in last_err_str or
                    "high demand" in last_err_str or
                    "overloaded" in last_err_str
                )

                # 3. Détection quota / rate limit / context limit (429 Resource Exhausted / 400 Context Length)
                is_rate_limit = (
                    isinstance(e, ResourceExhausted) or
                    "429" in last_err_str or
                    "resourceexhausted" in last_err_str or
                    "rate limit" in last_err_str or
                    "quota" in last_err_str
                )

                is_context_length_err = (
                    "400" in last_err_str and
                    ("reduce the length" in last_err_str or "context_length" in last_err_str or "too long" in last_err_str)
                )

                if is_not_found:
                    logger.warning(
                        f"[MODEL_DEPRECATED] {model_name} n'est plus disponible, retiré de la chaîne de fallback — pensez à mettre à jour GEMINI_MODEL_FALLBACK_CHAIN"
                    )
                    break

                elif is_context_length_err:
                    logger.warning(
                        f"[MODEL_CONTEXT_EXCEEDED] Modèle '{model_name}' a rejeté la longueur de message (400 context length). Bascule au modèle suivant."
                    )
                    break

                elif is_overloaded:
                    next_entry = chain_sequence[idx + 1] if idx + 1 < len(chain_sequence) else None
                    if next_entry:
                        logger.warning(
                            f"[MODEL_FALLBACK] {model_name} indisponible (503), bascule sur {next_entry['model']}"
                        )
                        break
                    else:
                        err_msg = f"Tous les modèles de la chaîne de fallback sont surchargés (503): {repr(e)}"
                        logger.error(err_msg)
                        raise LLMOverloadedError(err_msg) from e

                elif is_rate_limit:
                    next_entry = chain_sequence[idx + 1] if idx + 1 < len(chain_sequence) else None
                    if attempt < max_retries_per_model - 1:
                        time.sleep(1.0)
                        continue
                    elif next_entry:
                        logger.warning(
                            f"[MODEL_FALLBACK] Quota / Rate limit (429) atteint sur '{model_name}'. "
                            f"Bascule sur le modèle de secours '{next_entry['model']}'..."
                        )
                        break
                    else:
                        err_msg = f"Quota API / Rate limit épuisé sur tous les modèles Gemini après essais: {repr(e)}"
                        logger.error(err_msg)
                        raise LLMQuotaExhaustedError(err_msg) from e
                else:
                    err_msg = f"Échec permanent de l'appel LLM sur le modèle '{model_name}': {repr(e)}"
                    logger.error(err_msg)
                    raise e

    if last_error:
        if "503" in last_err_str or "unavailable" in last_err_str:
            raise LLMOverloadedError(f"Tous les modèles de secours ont échoué (503): {last_error}") from last_error
        elif "429" in last_err_str or "quota" in last_err_str or "rate limit" in last_err_str:
            raise LLMQuotaExhaustedError(f"Tous les modèles de secours ont échoué (429): {last_error}") from last_error
        elif "404" in last_err_str or "not found" in last_err_str or "no longer available" in last_err_str:
            raise LLMOverloadedError(f"Tous les modèles de la chaîne de fallback sont indisponibles/retirés (404): {last_error}") from last_error
        raise last_error

    raise RuntimeError("Invocation LLM impossible : aucun modèle n'a pu traiter la demande.")
