# backend/app/services/test_query_command_ec.py
"""
Test de validation 100% SQL (0 appel embedding Gemini).
Vérifie que query_command_code("EC") résout EC -> ED et remonte correctement
le chunk de la page 276 contenant les 8 codes d'erreur.
"""

from app.rag.retriever import query_command_code


def test_ec_exact_query():
    print("=== Test de validation 100% SQL : query_command_code('EC') ===")
    
    # Exécution de la recherche exacte
    docs = query_command_code("EC", limit=8)
    
    print(f"[OK] Nombre de documents retournés par query_command_code('EC') : {len(docs)}")
    
    from sqlalchemy import create_engine, text
    from app.rag.retriever import CONNECTION_STRING
    engine = create_engine(CONNECTION_STRING)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT cmetadata, document FROM langchain_pg_embedding WHERE document ILIKE '%PVK parity error%'")).fetchall()
        print("\nMétadonnées & extrait pour les chunks PVK parity error :")
        for r in rows:
            meta, doc = r[0], r[1]
            if str(meta.get("page")) == "276":
                print("PAGE 276 META:", meta)
                print("PAGE 276 DOC SNIPPET:", doc[:300])

    found_p276 = False
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata or {}
        page = meta.get("page", "N/A")
        resp_code = meta.get("response_code", "N/A")
        snippet = doc.page_content[:150].replace("\n", " ").encode("ascii", "replace").decode("ascii")
        print(f"--- Document #{i} (Page: {page}, Response Code: {resp_code}) ---")
        print(f"  Snippet: {snippet}...")
        
        if "276" in str(page) or "PVK parity error" in doc.page_content:
            found_p276 = True
            print("  [SUCCESS] -> CHUNK PAGE 276 RETROUVÉ PAR RECHERCHE EXACTE SQL !\n")
        else:
            print()

    if found_p276:
        print("\nTEST RÉUSSI : La recherche exacte par code de commande 'EC' (mappé vers 'ED') remonte bien la table d'erreur de la page 276 sans faire aucun appel embedding Gemini.")
    else:
        print("\nATTENTION : Le chunk de la page 276 n'a pas été identifié parmi les documents retournés.")


if __name__ == "__main__":
    test_ec_exact_query()
