import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from app.services.hsm_doc_loader import lookup_hsm_documentation

def test():
    print("Testing lookup_hsm_documentation for 'ED05'...")
    res = lookup_hsm_documentation("ED05")
    print("Found:", res.get("found"))
    print("Display:", res.get("display"))
    print("Sources:", res.get("sources"))
    print("Excerpts count:", len(res.get("excerpts", [])))
    for idx, ex in enumerate(res.get("excerpts", [])):
        print(f"\n--- Excerpt {idx+1} ({ex['source']}) ---")
        print(ex["content"])
    print("\n--- Synthesis ---")
    print(res.get("llm_synthesis"))

if __name__ == "__main__":
    test()
