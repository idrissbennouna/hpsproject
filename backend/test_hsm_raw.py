import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from app.services.hsm_doc_loader import parse_hsm_code, _docs_from_rag

def test():
    parsed = parse_hsm_code("ED05")
    print("Parsed code:", parsed)
    docs = _docs_from_rag(parsed, None)
    print("Found docs in RAG count:", len(docs))
    for i, d in enumerate(docs):
        print(f"\n--- DOC {i+1} ---")
        print("Metadata:", d.metadata)
        print("Content:")
        print(d.page_content)

if __name__ == "__main__":
    test()
