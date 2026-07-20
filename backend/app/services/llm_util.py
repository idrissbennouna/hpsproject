# backend/app/services/llm_util.py
import time
import logging
from google.api_core.exceptions import ResourceExhausted

logger = logging.getLogger("llm_util")

def invoke_llm_with_retry(chain_or_llm, inputs, max_retries=3, initial_wait=17):
    """
    Invoque un modèle ou une chaîne LangChain avec une logique de retry
    en cas d'erreur de quota (ResourceExhausted / HTTP 429).
    """
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logger.info(f"Retrying LLM invocation, attempt {attempt + 1}/{max_retries}...")
            return chain_or_llm.invoke(inputs)
        except Exception as e:
            # Détection de l'erreur temporaire (rate limit 429 ou surcharge 503)
            is_transient = (
                isinstance(e, ResourceExhausted) or
                "429" in str(e) or
                "503" in str(e) or
                "resourceexhausted" in str(e).lower() or
                "unavailable" in str(e).lower() or
                "quota" in str(e).lower() or
                "high demand" in str(e).lower()
            )
            
            if is_transient and attempt < max_retries - 1:
                wait_time = initial_wait * (attempt + 1)
                warn_msg = (
                    f"Transient error (429/503) detected during LLM invocation: {str(e)[:150]}... "
                    f"Retrying (attempt {attempt + 1}/{max_retries}) after sleeping for {wait_time}s..."
                )
                print(f"[WARN] {warn_msg}")
                logger.warning(warn_msg)
                time.sleep(wait_time)
            else:
                err_msg = f"LLM invocation failed permanently on attempt {attempt + 1}/{max_retries}: {str(e)}"
                logger.error(err_msg)
                raise e
