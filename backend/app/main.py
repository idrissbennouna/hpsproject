import os
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Import de ton application LangGraph compilée
from app.core.agent_graph import compliance_agent_app

app = FastAPI(
    title="ComplianceVerifier API - HPS",
    description="Backend d'analyse agentique de logs monétiques et de spécifications",
    version="1.0.0"
)

# 1. Configuration du CORS (indispensable pour lier FastAPI et React)
# Permet à ton frontend React (généralement sur http://localhost:5173 ou 3000) de requêter l'API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, spécifie l'URL exacte de ton React
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Résolution du dossier storage pour sauvegarder les fichiers téléversés
CURRENT_DIR = Path(__file__).resolve().parent
STORAGE_DIR = CURRENT_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


# 2. Route de base pour vérifier si le serveur tourne
@app.get("/")
def read_root():
    return {"status": "online", "message": "Serveur ComplianceVerifier opérationnel"}


# 3. Route principale : Analyse de Logs par le Système Multi-Agents
@app.post("/api/v1/logs/analyze")
async def analyze_logs(
    user_prompt: str = Form(...), 
    file: UploadFile = File(...)
):
    """
    Reçoit un fichier de traces .TXT et un prompt utilisateur,
    sauvegarde le fichier localement et l'analyse via LangGraph + Gemini.
    """
    # Sécurité : Vérifier le type de fichier
    if not file.filename.endswith('.TXT') and not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers de traces au format .TXT sont acceptés.")
    
    # Définition du chemin de sauvegarde pour le fichier téléversé
    # On garde le nom fixe pour ton parseur, ou on le rend dynamique si nécessaire
    target_file_path = STORAGE_DIR / "BASE1_LCH_2.TRC019.TXT"
    
    try:
        # Sauvegarde du fichier envoyé par React sur le disque dur du serveur
        with target_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Échec de l'écriture du fichier : {str(e)}")
        
    try:
        # Exécution de ton architecture agentique LangGraph
        graph_inputs = {
            "user_prompt": user_prompt,
            "current_agent": "",
            "rag_context": "",
            "log_data_json": "",
            "final_response": ""
        }
        
        # Lancement du graphe
        execution_result = compliance_agent_app.invoke(graph_inputs)
        
        # Retour de la réponse structurée en JSON vers ton application React
        return {
            "success": True,
            "agent_assigned": execution_result.get("current_agent"),
            "log_chronology": execution_result.get("log_data_json"),
            "analysis_report": execution_result.get("final_response")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse agentique : {str(e)}")