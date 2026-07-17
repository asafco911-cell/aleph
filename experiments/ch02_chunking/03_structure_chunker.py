from pypdf import PdfReader

reader = PdfReader("data/uber_10k.pdf")
page_text = reader.pages[60].extract_text()

# --- Chunker נאיבי (מהשלב הקודם, להשוואה) ---
def naive_chunk(text, chunk_size=500):
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

# --- Chunker מודע-מבנה: חותך לפי שורות, וצובר לפסקאות ---
def structure_chunk(text, max_chars=500):
    # מפצלים לשורות בודדות — כל שורה היא יחידה טבעית מה-PDF
    lines = text.split("\n")
    chunks = []
    current = ""
    for line in lines:
        # אם הוספת השורה הבאה תחרוג מהגבול — סוגרים chunk ומתחילים חדש
        if len(current) + len(line) > max_chars and current:
            chunks.append(current.strip())
            current = line
        else:
            current += "\n" + line
    if current.strip():
        chunks.append(current.strip())
    return chunks

naive = naive_chunk(page_text)
smart = structure_chunk(page_text)

print(f"Naive chunks: {len(naive)}  |  Structure-aware chunks: {len(smart)}")
print(f"\n{'='*70}\nSTRUCTURE-AWARE CHUNK 1:\n{'='*70}")
print(smart[0])
print(f"\n{'='*70}\nSTRUCTURE-AWARE CHUNK 2:\n{'='*70}")
print(smart[1])