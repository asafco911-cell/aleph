from pypdf import PdfReader
import chromadb
from rank_bm25 import BM25Okapi

# --- Chunker מבנה-מודע מפרק 2 ---
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

# נטען כמה עמודים כדי שיהיה מאגר אמיתי לחפש בו (לא רק עמוד אחד)
reader = PdfReader("data/uber_10k.pdf")
full_text = ""
for page_num in range(55, 75):          # ~20 עמודים מאזור הדוחות הכספיים
    full_text += reader.pages[page_num].extract_text() + "\n"

chunks = structure_chunk(full_text)
print(f"Total chunks: {len(chunks)}")

# --- מנוע 1: Dense (ChromaDB) ---
client = chromadb.Client()
collection = client.create_collection(name="uber_hybrid")
collection.add(documents=chunks, ids=[f"c{i}" for i in range(len(chunks))])

# --- מנוע 2: BM25 (lexical) ---
# BM25 עובד על "טוקנים" - מילים. נפצל כל chunk למילים קטנות
tokenized_chunks = [chunk.lower().split() for chunk in chunks]
bm25 = BM25Okapi(tokenized_chunks)

print("Both engines ready: dense (ChromaDB) + lexical (BM25)")

def reciprocal_rank_fusion(dense_ids, bm25_ids, k=60):
    """
    מקבל שתי רשימות מדורגות של chunk-ids ומאחד לפי מקום (rank).
    score של כל chunk = סכום 1/(k + rank) על פני שתי הרשימות.
    """
    scores = {}
    for rank, chunk_id in enumerate(dense_ids):
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank)
    for rank, chunk_id in enumerate(bm25_ids):
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank)
    # ממיינים לפי הציון המשולב, מהגבוה לנמוך
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked
query = "Uber Freight revenue"      # שאלה עם מילה נדירה: "Freight"

# --- חיפוש Dense ---
dense_results = collection.query(query_texts=[query], n_results=10)
dense_ids = dense_results["ids"][0]

# --- חיפוש BM25 ---
tokenized_query = query.lower().split()
bm25_scores = bm25.get_scores(tokenized_query)
# ממיינים אינדקסים לפי ציון BM25, לוקחים top-10, וממירים לפורמט id ("c0","c1"...)
top_bm25_idx = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:10]
bm25_ids = [f"c{i}" for i in top_bm25_idx]

print(f"\nQuery: {query}")
print(f"\nDense top-3 ids:  {dense_ids[:3]}")
print(f"BM25 top-3 ids:   {bm25_ids[:3]}")

# --- איחוד עם RRF ---
fused = reciprocal_rank_fusion(dense_ids, bm25_ids)
print(f"\nRRF fused top-3:  {[cid for cid, score in fused[:3]]}")
print("\n" + "="*70)
print("Final fused results (text):")
print("="*70)
id_to_chunk = {f"c{i}": chunks[i] for i in range(len(chunks))}
for rank, (chunk_id, score) in enumerate(fused[:3]):
    print(f"\n--- Rank {rank+1}  (id={chunk_id}, rrf_score={score:.4f}) ---")
    print(id_to_chunk[chunk_id][:250])