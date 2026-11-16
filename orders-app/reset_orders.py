"""Clear orders and attempts, preserving customers for a fresh failure scenario."""

import os
from datetime import UTC, datetime, timedelta

from pymongo import MongoClient
from pymongo.database import Database

from simulate_orders import DATABASE


def reset_orders(db: Database) -> None:
    if db.name in {"admin", "config", "local"}:
        raise ValueError("Choose the demo orders database, not a MongoDB system database.")
    db.orders.delete_many({})
    db.sync_attempts.delete_many({})
    now = datetime.now(UTC)
    for slug in ("aster", "cedar"):
        db.customers.update_many(
            {"slug": slug},
            {"$set": {
                "refresh_allowed": slug != "aster",
                "access_expires_at": now + timedelta(hours=-1 if slug == "aster" else 1),
            }},
        )


def main() -> None:
    with MongoClient(
        os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27029"),
        serverSelectionTimeoutMS=3000,
    ) as client:
        client.admin.command("ping")
        reset_orders(client[DATABASE])
    print(f"Cleared orders and synchronization attempts in {DATABASE}. Run make seed to recreate orders.")
    print("Customer records and indexes preserved; demo connection states reset to the initial scenario.")
    print("Other databases, Gmail, Notion and Logfire were not changed.")


if __name__ == "__main__":
    main()
