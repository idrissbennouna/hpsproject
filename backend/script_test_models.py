import os
from dotenv import load_dotenv
load_dotenv()
import importlib

try:
    genai = importlib.import_module("google.generativeai")
except ImportError as exc:
    raise ImportError(
        "The google-generativeai package is required. Install it with: pip install google-generativeai"
    ) from exc

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise EnvironmentError("GOOGLE_API_KEY environment variable is not set")

# adapte le nom de la variable d'env si différent
genai.configure(api_key=api_key)
for m in genai.list_models():
    if 'embedContent' in m.supported_generation_methods:
        print(m.name)