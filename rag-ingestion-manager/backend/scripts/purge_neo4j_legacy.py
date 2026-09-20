"""Delete the Neo4j graph nodes the removed graph_neo4j destination wrote.

Neo4j is no longer a destination, so migration 010 deletes the graph_neo4j rows
from knowledge_product_destinations. A migration must not do network I/O, so the
nodes it left behind are removed by this one-shot script instead.

Usage:
    uv run python scripts/purge_neo4j_legacy.py
    uv run python scripts/purge_neo4j_legacy.py --bolt-uri bolt://localhost:7687 \
        --user neo4j --password password --database neo4j
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bolt-uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="password")
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--auth-disabled", action="store_true")
    args = parser.parse_args()

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("The neo4j package is not installed. Install it, or delete the nodes by hand.")
        return 1

    auth = None if args.auth_disabled else (args.user, args.password)
    total = 0
    try:
        with GraphDatabase.driver(args.bolt_uri, auth=auth) as driver:
            with driver.session(database=args.database) as session:
                for label in ["Chunk", "Document", "Entity"]:
                    # Count first: a count in the same statement as DETACH DELETE
                    # reports the rows after the nodes are gone.
                    record = session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
                    deleted = int(record["c"]) if record else 0
                    if deleted:
                        session.run(f"MATCH (n:{label}) DETACH DELETE n")
                    total += deleted
                    print(f"deleted {deleted} {label} node(s)")
    except Exception as exc:
        print(f"Could not reach Neo4j at {args.bolt_uri}: {exc}")
        return 1

    print(f"total nodes deleted: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
