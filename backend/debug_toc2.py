# debug_toc2.py — à lancer depuis backend/ avec : python -m debug_toc2
import fitz

doc = fitz.open("app/storage/vip-system-BASE-i-tech-specs-volume-1.pdf")
toc = doc.get_toc()

print("=== Titres de niveau 1 (chapitres) ===")
for level, title, page in toc:
    if level == 1:
        print(f"page {page} : {title!r}")

doc.close()