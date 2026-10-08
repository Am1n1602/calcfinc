"""Example 5: amounts in different currencies are listed but never ranked; ratios compare freely."""
from pathlib import Path

from calcfinc import FinancialEngine

eng = FinancialEngine.from_csv(Path(__file__).parent / "data" / "two_currencies.csv")

revenue = eng.compare_companies("revenue", ["UsCo", "InCo"])
print("revenue ranked:", any("rank" in row for row in revenue["results"]))
print("why not:", revenue["limitations"][0])

roe = eng.compare_companies("roe", ["UsCo", "InCo"])
for row in roe["results"]:
    print(f"#{row['rank']} {row['entity']}: roe {row['value'].normalize():f}%")
