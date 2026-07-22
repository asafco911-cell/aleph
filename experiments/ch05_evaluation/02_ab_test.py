import os
import json
from collections import defaultdict
from dotenv import load_dotenv
from anthropic import Anthropic
from pypdf import PdfReader
import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PDF_PATH = "data/uber_10k.pdf"
GOLDEN_PATH = "experiments/ch05_evaluation/golden_dataset.json"


def structure_chunk(text, max_chars=500):
    """Structure-aware chunker from Ch2: never cuts a line in half."""
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) > max_chars and current:
            chunks.append(current.strip())
            current = line
        else:
            current += "\n" + line
    if current.strip():
        chunks.append(current.strip())
    return chunks


# Chunk page by page so every chunk remembers its source page
print("Loading and chunking the filing...")
reader = PdfReader(PDF_PATH)
chunk_texts, chunk_pages = [], []
for page_num, page in enumerate(reader.pages):
    text = page.extract_text()
    if not text:
        continue
    for c in structure_chunk(text):
        chunk_texts.append(c)
        chunk_pages.append(page_num)

chunk_ids = [f"c{i}" for i in range(len(chunk_texts))]
id_to_text = dict(zip(chunk_ids, chunk_texts))
id_to_page = dict(zip(chunk_ids, chunk_pages))
print(f"Indexed {len(chunk_texts)} chunks across {len(reader.pages)} pages")

# Engine 1: dense (ChromaDB)
chroma = chromadb.Client()
collection = chroma.create_collection(name="uber_ab")
collection.add(documents=chunk_texts, ids=chunk_ids)

# Engine 2: lexical (BM25)
bm25 = BM25Okapi([c.lower().split() for c in chunk_texts])

# Re-ranker for System B
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
print("Engines ready.\n")

def retrieve_system_a(query, k=5):
    """System A: dense retrieval only (Ch3)."""
    return collection.query(query_texts=[query], n_results=k)["ids"][0]


def retrieve_system_b(query, k=5, pool=10):
    """System B: hybrid (dense + BM25 + RRF) then cross-encoder re-rank (Ch4)."""
    dense_ids = collection.query(query_texts=[query], n_results=pool)["ids"][0]
    scores = bm25.get_scores(query.lower().split())
    bm25_ids = [f"c{i}" for i in sorted(range(len(scores)),
                key=lambda i: scores[i], reverse=True)[:pool]]

    # RRF fusion by rank position
    fused = defaultdict(float)
    for rank, cid in enumerate(dense_ids):
        fused[cid] += 1 / (60 + rank)
    for rank, cid in enumerate(bm25_ids):
        fused[cid] += 1 / (60 + rank)
    candidates = [cid for cid, _ in sorted(fused.items(), key=lambda x: x[1], reverse=True)[:pool]]

    # Cross-encoder re-rank the candidates
    pairs = [(query, id_to_text[cid]) for cid in candidates]
    ranked = sorted(zip(candidates, reranker.predict(pairs)), key=lambda x: x[1], reverse=True)
    return [cid for cid, _ in ranked[:k]]


def generate_answer(query, retrieved_ids):
    """Answer strictly from the retrieved context, or refuse."""
    context = "\n\n".join(f"[{cid}] {id_to_text[cid]}" for cid in retrieved_ids)
    prompt = f"""Answer the question using ONLY the context below.
If the context does not contain the answer, reply exactly:
"This information is not available in the document."

CONTEXT:
{context}

QUESTION: {query}"""
    resp = client.messages.create(
        model="claude-sonnet-4-5", max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip(), context

def judge(question, answer, context, ground_truth):
    """One call returning both correctness (vs ground truth) and faithfulness (vs context)."""
    prompt = f"""Evaluate an answer produced by a RAG system.

QUESTION: {question}
GROUND TRUTH: {ground_truth}
RETRIEVED CONTEXT: {context[:4000]}
SYSTEM ANSWER: {answer}

Score two things from 0.0 to 1.0:
- "correctness": does the system answer match the ground truth in substance?
- "faithfulness": is every claim in the system answer supported by the retrieved context?

Return ONLY JSON: {{"correctness": <float>, "faithfulness": <float>}}
Start with {{ and end with }}."""
    resp = client.messages.create(
        model="claude-sonnet-4-5", max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    raw = raw[raw.find("{"): raw.rfind("}") + 1]     # Ch4 robustness layer
    return json.loads(raw)


def evaluate(system_name, retrieve_fn, golden):
    """Run every golden question through one system and collect metrics."""
    results = []
    for i, item in enumerate(golden, 1):
        q = item["question"]
        print(f"  [{system_name}] {i}/{len(golden)}: {q[:55]}...")
        ids = retrieve_fn(q)
        answer, context = generate_answer(q, ids)

        # Deterministic retrieval metric: was a required page retrieved?
        retrieved_pages = {id_to_page[cid] for cid in ids}
        required = set(item["source_pages"])
        hit = 1.0 if (not required or (required & retrieved_pages)) else 0.0

        scores = judge(q, answer, context, item["ground_truth"])
        results.append({
            "type": item["question_type"],
            "retrieval_hit": hit,
            "correctness": scores["correctness"],
            "faithfulness": scores["faithfulness"],
        })
    return results


def report(name, results):
    """Print overall averages and a breakdown by question type."""
    def avg(rows, key):
        return sum(r[key] for r in rows) / len(rows) if rows else 0.0

    print(f"\n===== {name} =====")
    print(f"  OVERALL   hit={avg(results,'retrieval_hit'):.2f}  "
          f"correct={avg(results,'correctness'):.2f}  faithful={avg(results,'faithfulness'):.2f}")
    by_type = defaultdict(list)
    for r in results:
        by_type[r["type"]].append(r)
    for t, rows in sorted(by_type.items()):
        print(f"  {t:<15} hit={avg(rows,'retrieval_hit'):.2f}  "
              f"correct={avg(rows,'correctness'):.2f}  faithful={avg(rows,'faithfulness'):.2f}  (n={len(rows)})")


golden = json.load(open(GOLDEN_PATH, encoding="utf-8"))
print(f"Loaded {len(golden)} golden questions.\n")

print("Running System A (dense only)...")
results_a = evaluate("A", retrieve_system_a, golden)
print("\nRunning System B (hybrid + rerank)...")
results_b = evaluate("B", retrieve_system_b, golden)

report("SYSTEM A - dense only", results_a)
report("SYSTEM B - hybrid + rerank", results_b)