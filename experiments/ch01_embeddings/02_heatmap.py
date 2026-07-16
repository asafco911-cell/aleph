from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import matplotlib.pyplot as plt
import seaborn as sns

model = SentenceTransformer("all-MiniLM-L6-v2")

sentences = [
    "Revenue increased 12% year over year.",   # 0
    "Sales grew strongly this quarter.",         # 1
    "Top line expanded compared to last year.",  # 2
    "Revenue declined 12% year over year.",      # 3  <-- ההיפך של 0
    "Sales dropped sharply this quarter.",       # 4  <-- ההיפך של 1
    "The company took on significant new debt.", # 5
    "Leverage rose substantially.",              # 6
    "Net cash position improved.",               # 7
    "The cat sat quietly on the warm mat.",      # 8  <-- זר לגמרי
    "We enjoyed a pizza on a sunny afternoon.",  # 9  <-- זר לגמרי
]
# שלב 1: כל משפט מקבל כתובת מוחלטת (encode) — 10 משפטים -> 10 וקטורים
vectors = model.encode(sentences)

# שלב 2: ההשוואה היחסית — cosine בין כל זוג
# vectors בגודל (10, 384); cosine_similarity מחזיר מטריצה (10, 10)
similarity_matrix = cosine_similarity(vectors)

# נדפיס את השורה של משפט 0 מול כולם, כדי לראות מספרים לפני הגרף
print("cosine of sentence 0 vs all others:")
for i, score in enumerate(similarity_matrix[0]):
    print(f"  0 vs {i}: {score:.3f}   |  {sentences[i]}")

# ציור מפת החום: כל תא = cosine בין שני משפטים
labels = [f"{i}" for i in range(len(sentences))]

plt.figure(figsize=(9, 7))
sns.heatmap(
    similarity_matrix,
    xticklabels=labels,
    yticklabels=labels,
    annot=True,           # להציג את המספר בכל תא
    fmt=".2f",            # שתי ספרות אחרי הנקודה
    cmap="RdYlGn",        # אדום=נמוך, ירוק=גבוה
    vmin=0, vmax=1,
)
plt.title("Cosine similarity between financial sentences")
plt.tight_layout()
plt.savefig("experiments/ch01_embeddings/heatmap.png", dpi=150)
print("Saved heatmap.png")
plt.show()