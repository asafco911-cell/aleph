import json
import networkx as nx

# Load the extraction from step 1
with open("experiments/ch07_graph/extracted_page58.json", encoding="utf-8") as f:
    data = json.load(f)

# MultiDiGraph: directed, and allows multiple edges between the same pair
# (needed because (Mobility)->(Revenue) exists once per period)
G = nx.MultiDiGraph()

for n in data["nodes"]:
    G.add_node(n["id"], type=n["type"])

for e in data["edges"]:
    G.add_edge(
        e["source"], e["target"],
        relation=e["relation"],
        period=e.get("period"),
        value=e.get("value"),
        unit=e.get("unit"),
    )

print(f"Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges\n")
def revenue_growth_by_segment(G):
    """Deterministic: pull each segment's revenue per period and compute the delta."""
    segments = [n for n, d in G.nodes(data=True) if d.get("type") == "Segment"]
    results = []
    for seg in segments:
        by_period = {}
        # Walk every edge from this segment to Revenue
        for _, target, attrs in G.out_edges(seg, data=True):
            if target == "Revenue" and attrs.get("relation") == "REPORTED":
                by_period[attrs.get("period")] = attrs.get("value")
        if "2024" in by_period and "2025" in by_period:
            growth = by_period["2025"] - by_period["2024"]
            pct = growth / by_period["2024"] * 100
            results.append((seg, by_period["2024"], by_period["2025"], growth, pct))
    return sorted(results, key=lambda r: r[3], reverse=True)


print("Q1: Which segment contributed most to revenue growth?")
print(f"{'segment':<12}{'2024':>10}{'2025':>10}{'growth':>10}{'pct':>9}")
for seg, v24, v25, growth, pct in revenue_growth_by_segment(G):
    print(f"{seg:<12}{v24:>10,.0f}{v25:>10,.0f}{growth:>10,.0f}{pct:>8.1f}%")

def metrics_by_level(G):
    """Aggregation: which metrics appear at segment level but not at company level?"""
    company_metrics, segment_metrics = set(), set()
    for source, target, attrs in G.edges(data=True):
        if attrs.get("relation") != "REPORTED":
            continue
        src_type = G.nodes[source].get("type")
        if src_type == "Company":
            company_metrics.add(target)
        elif src_type == "Segment":
            segment_metrics.add(target)
    return company_metrics, segment_metrics


print("\n\nQ2: Which metrics are reported at segment level but NOT at company level?")
company_m, segment_m = metrics_by_level(G)
print(f"  Company level : {sorted(company_m)}")
print(f"  Segment only  : {sorted(segment_m - company_m)}")
print(f"  Both levels   : {sorted(segment_m & company_m)}")