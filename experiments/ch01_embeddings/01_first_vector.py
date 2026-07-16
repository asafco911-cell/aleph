from sentence_transformers import SentenceTransformer
import numpy as np

# טוענים את מודל האמבדינג. בפעם הראשונה זה מוריד ~90MB ושומר במטמון.
model = SentenceTransformer("all-MiniLM-L6-v2")

sentence = "Revenue increased 12% year over year."
vector = model.encode(sentence)

print("Type:  ", type(vector))
print("Shape: ", vector.shape)
print("First 8 numbers:", vector[:8])
print("Vector length (norm):", np.linalg.norm(vector))