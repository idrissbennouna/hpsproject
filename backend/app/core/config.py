# backend/app/core/config.py
import os

# Limits and Guardrails for Uploads
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "1000"))

# RAG & Embedding Batching Config
PDF_CHUNK_SIZE = int(os.getenv("PDF_CHUNK_SIZE", "2500"))
PDF_CHUNK_OVERLAP = int(os.getenv("PDF_CHUNK_OVERLAP", "300"))
# Tuned for Gemini API free tier limits (low RPM/daily quota). Gemini batchEmbedContents max batch size is 100.
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))
EMBEDDING_BATCH_DELAY_SECONDS = float(os.getenv("EMBEDDING_BATCH_DELAY_SECONDS", "60.0"))

# Set below the 30K TPM free-tier ceiling for Gemini Embedding 1, leaving headroom for estimation error.
EMBEDDING_MAX_TOKENS_PER_BATCH = int(os.getenv("EMBEDDING_MAX_TOKENS_PER_BATCH", "25000"))


