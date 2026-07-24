# debug_toc.py — à lancer depuis backend/ avec : python -m debug_toc
import fitz

doc = fitz.open("app/storage/vip-system-BASE-i-tech-specs-volume-1.pdf")
toc = doc.get_toc()

for level, title, page in toc:
    if "field" in title.lower() or "data field" in title.lower():
        print(f"[niveau {level}] page {page} : {title!r}")

doc.close()