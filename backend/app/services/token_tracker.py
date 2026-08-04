# backend/app/services/token_tracker.py
import json
import os
import threading
from datetime import datetime

# Verrou pour éviter les écritures concurrentes sur le fichier JSON
FILE_LOCK = threading.Lock()

# Résolution du fichier de stockage de la consommation
STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage")
USAGE_FILE = os.path.join(STORAGE_DIR, "token_usage.json")

def extract_token_usage(llm_response) -> dict:
    """
    Extrait de manière robuste le nombre de tokens consommés à partir d'une réponse de LLM.
    Cette fonction est tolérante aux pannes et retourne des zéros en cas de structure imprévue.
    """
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if not llm_response:
        return usage
        
    try:
        # Extraire le modèle utilisé s'il a été attaché aux métadonnées
        if hasattr(llm_response, "response_metadata") and isinstance(llm_response.response_metadata, dict):
            usage["model"] = llm_response.response_metadata.get("model_used") or llm_response.response_metadata.get("model_name")

        # 1. Structure moderne de LangChain (usage_metadata)
        if hasattr(llm_response, "usage_metadata") and llm_response.usage_metadata:
            meta = llm_response.usage_metadata
            usage["input_tokens"] = meta.get("input_tokens", 0)
            usage["output_tokens"] = meta.get("output_tokens", 0)
            usage["total_tokens"] = meta.get("total_tokens", 0)
            
        # 2. Structure classique (response_metadata -> token_usage)
        elif hasattr(llm_response, "response_metadata") and llm_response.response_metadata:
            meta = llm_response.response_metadata
            token_usage = meta.get("token_usage", {}) or meta.get("usage", {})
            if token_usage:
                usage["input_tokens"] = token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
                usage["output_tokens"] = token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
                usage["total_tokens"] = token_usage.get("total_tokens") or 0
                
        # Sécurité de calcul
        if usage["total_tokens"] == 0 and (usage["input_tokens"] > 0 or usage["output_tokens"] > 0):
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            
    except Exception as e:
        print(f"⚠️ Warning : Impossible d'extraire l'usage des tokens de la réponse LLM : {e}")
        
    return usage

def record_usage(agent_name: str, usage: dict, model_name: str = None):
    """
    Persiste la consommation de tokens dans un fichier JSON local (token_usage.json).
    Cette écriture est thread-safe grâce au verrou FILE_LOCK.
    """
    with FILE_LOCK:
        try:
            # Créer le répertoire de stockage s'il n'existe pas
            os.makedirs(STORAGE_DIR, exist_ok=True)
            
            data = {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "history": []
            }
            
            # Charger les données existantes
            if os.path.exists(USAGE_FILE):
                try:
                    with open(USAGE_FILE, "r", encoding="utf-8") as f:
                        loaded_data = json.load(f)
                        if isinstance(loaded_data, dict):
                            data.update(loaded_data)
                except Exception as e:
                    print(f"⚠️ Lecture du fichier token_usage.json échouée, réinitialisation : {e}")

            # Mise à jour des compteurs cumulés
            input_t = usage.get("input_tokens", 0)
            output_t = usage.get("output_tokens", 0)
            total_t = usage.get("total_tokens", 0)
            effective_model = model_name or usage.get("model") or "gemini-3.5-flash"
            
            data["total_input_tokens"] = data.get("total_input_tokens", 0) + input_t
            data["total_output_tokens"] = data.get("total_output_tokens", 0) + output_t
            data["total_tokens"] = data.get("total_tokens", 0) + total_t

            # Enregistrement dans l'historique
            history_entry = {
                "timestamp": datetime.now().isoformat(),
                "agent": agent_name,
                "model": effective_model,
                "input_tokens": input_t,
                "output_tokens": output_t,
                "total_tokens": total_t
            }
            if "history" not in data:
                data["history"] = []
            data["history"].append(history_entry)

            # Sauvegarde
            with open(USAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as err:
            print(f"❌ Échec de l'écriture dans token_usage.json : {err}")

def get_usage_summary() -> dict:
    """
    Retourne la consommation totale de tokens, le budget configuré,
    les tokens restants et le pourcentage de consommation.
    """
    # Budget configurable via le .env (valeur par défaut : 1 000 000 tokens)
    # Note : ce budget est une limite virtuelle interne au projet pour contrôle, 
    # et non un quota imposé par l'API officielle Google.
    budget = int(os.getenv("TOKEN_BUDGET_LIMIT", "1000000"))
    
    used = 0
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                used = data.get("total_tokens", 0)
        except Exception:
            pass

    remaining = max(0, budget - used)
    percentage = round((used / budget * 100), 1) if budget > 0 else 0.0

    return {
        "used": used,
        "budget": budget,
        "remaining": remaining,
        "percentage": percentage
    }

def get_usage_history(limit: int = 50) -> list:
    """Retourne les n derniers appels enregistrés dans l'historique."""
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                history = data.get("history", [])
                return history[-limit:]
        except Exception:
            pass
    return []
