# backend/app/services/llm_util.py
import time
from google.api_core.exceptions import ResourceExhausted

def invoke_llm_with_retry(chain_or_llm, inputs, max_retries=3, initial_wait=17):
    """
    Invoque un modèle ou une chaîne LangChain avec une logique de retry
    en cas d'erreur de quota (ResourceExhausted / HTTP 429).
    """
    for attempt in range(max_retries):
        try:
            return chain_or_llm.invoke(inputs)
        except Exception as e:
            # Détection de l'erreur de quota / rate limit (429)
            is_rate_limit = (
                isinstance(e, ResourceExhausted) or
                "429" in str(e) or
                "resourceexhausted" in str(e).lower() or
                "quota" in str(e).lower()
            )
            
            if is_rate_limit and attempt < max_retries - 1:
                wait_time = initial_wait * (attempt + 1)
                print(f"[WARN] Rate limit detecte ({str(e)[:100]}...). Essai de secours ({attempt + 1}/{max_retries}) apres une pause de {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise e
