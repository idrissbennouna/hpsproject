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
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "40"))
EMBEDDING_BATCH_DELAY_SECONDS = float(os.getenv("EMBEDDING_BATCH_DELAY_SECONDS", "60.0"))

# Versioning logic for chunking algorithm & metadata extraction schema.
# Increment this version whenever PDF chunking logic, text splitting parameters, or metadata extraction regexes change.
CHUNKING_VERSION = os.getenv("CHUNKING_VERSION", "v2")

# Set below the 30K TPM free-tier ceiling for Gemini Embedding 1, leaving headroom for estimation error.
EMBEDDING_MAX_TOKENS_PER_BATCH = int(os.getenv("EMBEDDING_MAX_TOKENS_PER_BATCH", "12000"))

# Multi-Provider LLM Fallback Config (Resilience against 503 / High Demand & 429 Quota Limits)
# Note: Groq is used as a secondary provider to bypass Gemini daily/rate quota limits.
# Check https://ai.google.dev/gemini-api/docs/models and https://console.groq.com/docs/models periodically for availability.
# CRITICAL: Never include gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-*, or any pre-3.x Gemini models.

DEFAULT_LLM_FALLBACK_CHAIN = [
    {"provider": "gemini", "model": "gemini-3.5-flash", "max_context_tokens": 1000000},
    {"provider": "gemini", "model": "gemini-3.6-flash", "max_context_tokens": 1000000},
]

LLM_FALLBACK_CHAIN = DEFAULT_LLM_FALLBACK_CHAIN

# Backward compatibility alias for Gemini-only chains
GEMINI_MODEL_FALLBACK_CHAIN = [item["model"] for item in LLM_FALLBACK_CHAIN if item["provider"] == "gemini"]
GEMINI_MAX_RETRIES_PER_MODEL = int(os.getenv("GEMINI_MAX_RETRIES_PER_MODEL", "1"))





