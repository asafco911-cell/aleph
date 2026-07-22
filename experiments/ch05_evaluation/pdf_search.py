import sys
from pypdf import PdfReader

PDF_PATH = "data/uber_10k.pdf"


def search_pdf(term, context_chars=500, max_hits=5):
    """Find pages containing a term and print the surrounding text for manual verification."""
    reader = PdfReader(PDF_PATH)
    hits = 0
    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if not text:
            continue
        lower = text.lower()
        if term.lower() in lower:
            idx = lower.find(term.lower())
            start = max(0, idx - context_chars // 2)
            end = min(len(text), idx + context_chars // 2)
            print(f"\n{'='*70}")
            print(f"PAGE {page_num}")
            print(f"{'='*70}")
            print(text[start:end].strip())
            hits += 1
            if hits >= max_hits:
                print(f"\n[stopped after {max_hits} hits]")
                break
    if hits == 0:
        print(f"No pages found containing: {term}")


if __name__ == "__main__":
    # Usage: python experiments/ch05_evaluation/pdf_search.py "Freight revenue"
    if len(sys.argv) < 2:
        print('Usage: python pdf_search.py "search term"')
    else:
        search_pdf(" ".join(sys.argv[1:]))