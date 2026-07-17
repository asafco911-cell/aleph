from pypdf import PdfReader

reader = PdfReader("data/uber_10k.pdf")

# ניקח את הטקסט של עמוד 60 — העמוד עם הטבלה שראינו
page_text = reader.pages[60].extract_text()

# --- Chunker נאיבי: חותך כל N תווים, בלי לחשוב על מבנה ---
def naive_chunk(text, chunk_size=500):
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i + chunk_size])
    return chunks

chunks = naive_chunk(page_text, chunk_size=500)

print(f"Total characters on page: {len(page_text)}")
print(f"Number of chunks: {len(chunks)}")
print(f"\n{'='*70}")
print("CHUNK 1:")
print(f"{'='*70}")
print(chunks[0])
print(f"\n{'='*70}")
print("CHUNK 2:")
print(f"{'='*70}")
print(chunks[1])