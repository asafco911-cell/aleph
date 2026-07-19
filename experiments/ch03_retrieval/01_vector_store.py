from pypdf import PdfReader
import chromadb

# --- Chunker מבנה-מודע מפרק 2 (הקוד שלנו מצטבר) ---
def structure_chunk(text, max_chars=500):
    lines = text.split("\n")
    chunks, current = [], ""
    for line in lines:
        if len(current) + len(line) > max_chars and current:
            chunks.append(current.strip())
            current = line
        else:
            current += "\n" + line
    if current.strip():
        chunks.append(current.strip())
    return chunks

# טוענים את הטקסט של עמוד 60 (העמוד עם הטבלה מפרק 2)
reader = PdfReader("data/uber_10k.pdf")
page_text = reader.pages[60].extract_text()
chunks = structure_chunk(page_text)

print(f"Number of chunks to store: {len(chunks)}")
# יוצרים client של ChromaDB במצב in-memory (נמחק בסוף ההרצה)
client = chromadb.Client()

# collection = "מגירה" שמחזיקה וקטורים + הטקסט המקורי + מזהים
collection = client.create_collection(name="uber_page60")

# מכניסים את ה-chunks. ChromaDB עושה encode פנימית (all-MiniLM ברירת מחדל!)
collection.add(
    documents=chunks,
    ids=[f"chunk_{i}" for i in range(len(chunks))]
)

print(f"Stored {collection.count()} chunks in the vector store.")
query = "How much revenue did Uber Mobility generate?"

results = collection.query(
    query_texts=[query],
    n_results=3          # top-k = 3, בדיוק כמו בקורס הראשון
)

print(f"\nQuery: {query}\n")
print("="*70)
for i, (doc, dist) in enumerate(zip(results["documents"][0], results["distances"][0])):
    print(f"\n--- Result {i+1}  (distance: {dist:.3f}) ---")
    print(doc[:300])