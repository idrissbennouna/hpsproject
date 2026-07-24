# debug_toc3.py — à lancer depuis backend/ avec : python -m debug_toc3
import fitz

doc = fitz.open("app/storage/vip-system-BASE-i-tech-specs-volume-1.pdf")
toc = doc.get_toc()

print("=== Entrées entre page 105 et page 647 (chapitre 4) ===")
for level, title, page in toc:
    if 105 <= page < 647:
        print(f"[niveau {level}] page {page} : {title!r}")