"""SMC Event Engine — translate SMC indicators into timestamped event streams.

Faithfully replicates LuxAlgo Pine Script logic for Smart Money Concepts,
with extended lifecycle tracking, snapshot logging, and no-lookahead guards.

Output: events.csv, snapshots.csv, objects.csv — the foundation for serious backtesting.
"""

__version__ = "0.1.0"
