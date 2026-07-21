import os
import json
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def judge_faithfulness(answer, context):
    """
    Use Claude as a judge to score whether an answer is faithful to the context.
    Returns a score from 0.0 (fully hallucinated) to 1.0 (fully supported).
    """
    prompt = f"""You are evaluating whether an ANSWER is faithful to the provided CONTEXT.
Faithful means: every factual claim in the answer is directly supported by the context.
If the answer states facts not present in the context, it is NOT faithful.

CONTEXT:
{context}

ANSWER:
{answer}

Score faithfulness from 0.0 to 1.0, where:
- 1.0 = every claim is fully supported by the context
- 0.0 = the answer contains claims not supported by the context (hallucination)

Return ONLY a JSON object: {{"score": <float>, "reason": "<short explanation>"}}
Start with {{ and end with }}."""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()

    # Robustness layer from Ch4: extract the JSON object
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end + 1]
    return json.loads(raw)


# --- Test with two cases: one faithful, one hallucinated ---
context = "Uber Technologies Freight segment: Freight revenue decreased $42 million, or 1%, in the year ended December 31, 2025."

faithful_answer = "Uber Freight revenue declined by $42 million, or about 1%."
hallucinated_answer = "Uber Freight revenue collapsed by $200 million, a 15% drop."

print("--- Faithful answer ---")
print(judge_faithfulness(faithful_answer, context))
print("\n--- Hallucinated answer ---")
print(judge_faithfulness(hallucinated_answer, context))