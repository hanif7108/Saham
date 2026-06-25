import sys
sys.path.append("/Users/hanif/Saham/sharia_trading_ai")

from app.core import decisions
import json

ranking = decisions.build_ranking()
print(f"Total ranking items: {len(ranking)}")

dewa = next((s for s in ranking if s["ticker"] == "DEWA"), None)
if dewa:
    print("\nDEWA status in ranking:")
    print(json.dumps(dewa, indent=2))
else:
    print("\nDEWA not found in ranking!")

# Test prime pool
pool = decisions._prime_pool(ranking)
print(f"\nTotal items in prime pool: {len(pool)}")
dewa_in_pool = next((item for item in pool if item[1]["ticker"] == "DEWA"), None)
if dewa_in_pool:
    print("DEWA is in prime pool!")
else:
    print("DEWA is NOT in prime pool.")

# Output current Top 5 and candidates
dec = decisions.build_decisions()
print("\nTop 5 Watchlist:")
print(dec["top5"])

print("\nTop 5 Detail:")
print(json.dumps(dec["top5_detail"], indent=2))

print("\nBuy Candidates:")
print([(c["ticker"], c["reason"], c.get("akurasi_pct")) for c in dec["buy"]])
