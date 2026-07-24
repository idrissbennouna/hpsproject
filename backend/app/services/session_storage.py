# backend/app/services/session_storage.py

# Dictionnaire global en mémoire : { session_id: [ {"name": str, "content": str, "stats": dict}, ... ] }
EPHEMERAL_SESSIONS = {}

def compute_file_stats(content: str) -> dict:
    """Calcule des statistiques exactes sur le contenu du fichier (lignes et caractères)."""
    lines = content.splitlines()
    line_count = len(lines)
    non_empty_line_count = sum(1 for line in lines if line.strip())
    char_count = len(content)
    return {
        "line_count": line_count,
        "non_empty_line_count": non_empty_line_count,
        "char_count": char_count
    }

def add_session_file(session_id: str, filename: str, content: str, full_stats: dict = None, is_rag: bool = False):
    """
    Ajoute un fichier extrait à la session en cours avec ses statistiques.
    """
    if session_id not in EPHEMERAL_SESSIONS:
        EPHEMERAL_SESSIONS[session_id] = []
    
    # Supprimer l'ancienne version du fichier s'il a le même nom
    EPHEMERAL_SESSIONS[session_id] = [
        f for f in EPHEMERAL_SESSIONS[session_id] if f["name"] != filename
    ]
    
    stats = full_stats if full_stats is not None else compute_file_stats(content)
    EPHEMERAL_SESSIONS[session_id].append({
        "name": filename,
        "content": content,
        "stats": stats,
        "is_rag": is_rag
    })
    print(f"Fichier '{filename}' ajoute a la session '{session_id}' (is_rag={is_rag}).")


def get_session_files(session_id: str) -> list[dict]:
    """Récupère tous les fichiers associés à une session."""
    return EPHEMERAL_SESSIONS.get(session_id, [])
