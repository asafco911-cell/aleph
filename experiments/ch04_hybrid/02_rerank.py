from pypdf import PdfReader
import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

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

def reciprocal_rank_fusion(dense_ids, bm25_ids, k=60):
    scores = {}
    for rank, cid in enumerate(dense_ids):
        scores[cid] = scores.get(cid, 0) + 1 / (k + rank)
    for rank, cid in enumerate(bm25_ids):
        scores[cid] = scores.get(cid, 0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)

# Load ~20 pages and chunk
reader = PdfReader("data/uber_10k.pdf")
full_text = ""
for page_num in range(55, 75):
    full_text += reader.pages[page_num].extract_text() + "\n"
chunks = structure_chunk(full_text)
id_to_chunk = {f"c{i}": chunks[i] for i in range(len(chunks))}

# Dense engine
client = chromadb.Client()
collection = client.create_collection(name="uber_rerank")
collection.add(documents=chunks, ids=[f"c{i}" for i in range(len(chunks))])

# BM25 engine
tokenized_chunks = [c.lower().split() for c in chunks]
bm25 = BM25Okapi(tokenized_chunks)

query = "Why did Uber Freight revenue decline?"

# Run both engines, fuse with RRF -> candidate list
dense_ids = collection.query(query_texts=[query], n_results=10)["ids"][0]
bm25_scores = bm25.get_scores(query.lower().split())
bm25_ids = [f"c{i}" for i in sorted(range(len(bm25_scores)),
            key=lambda i: bm25_scores[i], reverse=True)[:10]]
fused = reciprocal_rank_fusion(dense_ids, bm25_ids)

# Take top-10 fused candidates to send to the re-ranker
candidate_ids = [cid for cid, score in fused[:10]]
print(f"Query: {query}")
print(f"Hybrid top-3 (before re-rank): {candidate_ids[:3]}")

# The cross-encoder: reads (query, chunk) pairs TOGETHER and scores relevance
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

# Build (query, chunk_text) pairs for each candidate
pairs = [(query, id_to_chunk[cid]) for cid in candidate_ids]

# Score every pair. This is the slow-but-accurate step (runs per pair)
rerank_scores = reranker.predict(pairs)

# Sort candidates by the cross-encoder score, high to low
reranked = sorted(zip(candidate_ids, rerank_scores),
                  key=lambda x: x[1], reverse=True)

print(f"\nRe-ranked top-3 (after cross-encoder): {[cid for cid, s in reranked[:3]]}")
print("\n" + "="*70)
for rank, (cid, score) in enumerate(reranked[:3]):
    print(f"\n--- Rank {rank+1}  (id={cid}, ce_score={score:.3f}) ---")
    print(id_to_chunk[cid][:250])