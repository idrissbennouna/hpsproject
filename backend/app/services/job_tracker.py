import time
from typing import Dict, Any, Optional

_jobs_store: Dict[str, Dict[str, Any]] = {}

def create_job(job_id: str, job_type: str = "log_analysis") -> Dict[str, Any]:
    job = {
        "job_id": job_id,
        "job_type": job_type,
        "status": "processing",
        "stage": "started",
        "detail": "Initialisation du traitement...",
        "progress_pct": 0,
        "updated_at": time.time(),
        "error": None,
        "result": None
    }
    _jobs_store[job_id] = job
    return job

def update_job(job_id: str, stage: str, detail: str, progress_pct: Optional[int] = None, error: Optional[str] = None, result: Optional[Any] = None):
    if job_id not in _jobs_store:
        create_job(job_id)
    
    job = _jobs_store[job_id]
    job["stage"] = stage
    job["detail"] = detail
    job["updated_at"] = time.time()
    
    if progress_pct is not None:
        job["progress_pct"] = progress_pct
        
    if error:
        job["status"] = "error"
        job["error"] = error
    elif stage == "done":
        job["status"] = "completed"
        job["progress_pct"] = 100
        if result is not None:
            job["result"] = result

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return _jobs_store.get(job_id)
