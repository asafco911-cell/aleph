import os
import json
from dotenv import load_dotenv
from anthropic import Anthropic

# Load ANTHROPIC_API_KEY from .env
load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def decompose_query(complex_query):
    """Ask Claude to break a complex question into simple sub-questions."""
    prompt = f"""Break the following financial question into simple, \
self-contained sub-questions. Each sub-question must target ONE company \
and ONE metric so it can be retrieved independently.

Return ONLY a JSON array of strings. No preamble, no explanation, \
no markdown code fences. Start your response with [ and end with ].

Question: "{complex_query}"
"""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()

    # Debug: see exactly what the model returned
    print(f"--- RAW model output ---\n{raw}\n------------------------")

    # Robustness layer: strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.strip("`")               # remove backticks
        raw = raw.replace("json", "", 1).strip()  # remove leading "json" label

    # Robustness layer: extract the JSON array by slicing from first [ to last ]
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1:
        raw = raw[start:end + 1]

    sub_questions = json.loads(raw)
    return sub_questions

# Test it
complex_q = "Compare Uber's and Lyft's operating margin in 2024"
subs = decompose_query(complex_q)

print(f"Complex query:\n  {complex_q}\n")
print("Decomposed into:")
for i, q in enumerate(subs, 1):
    print(f"  {i}. {q}")