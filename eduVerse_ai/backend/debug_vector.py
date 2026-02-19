"""
debug_vector.py — Run this to diagnose why certain queries return empty

Usage:
  cd backend
  python3 debug_vector.py
"""

import sys
sys.path.insert(0, '.')

import vectordb
import router

# Test queries that are failing
failing_queries = [
    "minimum mandatory attendance for students",
    "necessary things to remember before exam",
    "what will happen if student forgot to mark attendance on attendance sheet",
]

print("="*70)
print("VECTOR SEARCH DEBUG")
print("="*70)

for query in failing_queries:
    print(f"\nQuery: '{query}'")
    print("-" * 70)
    
    # 1. Check intent classification
    intent = router.classify_intent(query)
    print(f"  Intent: {intent}")
    
    # 2. Try different score thresholds
    for threshold in [0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35]:
        hits = vectordb.search(query, top_k=6, min_score=threshold)
        if hits:
            print(f"\n  Threshold {threshold:.2f} → {len(hits)} hits:")
            for i, h in enumerate(hits[:3], 1):
                print(f"    [{i}] score={h['score']:.3f} source={h['source']}")
                print(f"        {h['text'][:120]}...")
            break
    else:
        print(f"\n  ⚠️  NO HITS even at threshold 0.0 — document may not contain this info")

print("\n" + "="*70)
print("DB STATS")
print("="*70)
stats = vectordb.stats()
for doc_type, count in stats.items():
    print(f"  {doc_type:12s}: {count:4d} chunks")

print("\n" + "="*70)
print("COLLECTION THRESHOLDS (current)")
print("="*70)
print(f"  timetables: {vectordb.MIN_SCORE['timetables']}")
print(f"  policies:   {vectordb.MIN_SCORE['policies']}")
print(f"  notices:    {vectordb.MIN_SCORE['notices']}")
print(f"  general:    {vectordb.MIN_SCORE['general']}")

print("\n" + "="*70)
print("RECOMMENDATION")
print("="*70)
print("If scores are in 0.15-0.25 range but being filtered:")
print("  → Lower MIN_SCORE['policies'] from 0.32 to 0.18 in vectordb.py")
print("  → Restart server")
print("\nIf NO HITS even at threshold 0.0:")
print("  → Document doesn't contain that specific info")
print("  → Upload the correct policy PDF that covers this topic")