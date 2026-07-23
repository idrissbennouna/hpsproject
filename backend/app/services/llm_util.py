# backend/app/services/llm_util.py
import time
import logging
from google.api_core.exceptions import ResourceExhausted

logger = logging.getLogger("llm_util")

class GeminiOverloadedError(Exception):
    """Exception levée lorsque le modèle Gemini est surchargé (503 Service Unavailable)."""
    pass

class GeminiQuotaExhaustedError(Exception):
    """Exception levée lorsque les quotas de l'API de génération Gemini sont épuisés (429)."""
    pass

def invoke_llm_with_retry(chain_or_llm, inputs, max_retries=3, initial_wait=3):
    """
    Invoque un modèle ou une chaîne LangChain avec une logique de retry optimisée
    pour un usage interactif (budget max ~15-20s pour les retries).
    Échoue immédiatement (fail-fast) sur les erreurs 503 (surcharge).
    """
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logger.info(f"Retrying LLM invocation, attempt {attempt + 1}/{max_retries}...")
            return chain_or_llm.invoke(inputs)
        except Exception as e:
            err_str = str(e).lower()
            
            # 1. Détection spécifique de la surcharge serveur (503 / Service Unavailable / High Demand)
            is_overloaded = (
                "503" in err_str or
                "unavailable" in err_str or
                "high demand" in err_str
            )
            if is_overloaded:
                err_msg = f"Gemini is temporarily overloaded (503): {str(e)[:150]}..."
                logger.error(err_msg)
                raise GeminiOverloadedError(err_msg) from e
                
            # 2. Détection du rate limit ou quota épuisé (429 / Resource Exhausted)
            is_rate_limit = (
                isinstance(e, ResourceExhausted) or
                "429" in err_str or
                "resourceexhausted" in err_str or
                "quota" in err_str
            )
            
            if is_rate_limit and attempt < max_retries - 1:
                wait_time = initial_wait * (attempt + 1)
                warn_msg = (
                    f"Transient error (429) detected during LLM invocation: {str(e)[:150]}... "
                    f"Retrying (attempt {attempt + 1}/{max_retries}) after sleeping for {wait_time}s..."
                )
                logger.warning(warn_msg)  # Only log via logger to avoid duplicate log lines on stdout
                time.sleep(wait_time)
            else:
                if is_rate_limit:
                    err_msg = f"Gemini API quota exhausted after {attempt + 1} attempts: {str(e)[:150]}..."
                    logger.error(err_msg)
                    raise GeminiQuotaExhaustedError(err_msg) from e
                else:
                    err_msg = f"LLM invocation failed permanently on attempt {attempt + 1}/{max_retries}: {str(e)}"
                    logger.error(err_msg)
                    raise e
