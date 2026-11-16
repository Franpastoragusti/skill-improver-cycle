"""Two customers, one broken credential refresh, real Mongo data and Logfire spans."""

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta

import logfire
from bson import ObjectId
from pymongo import MongoClient, ReturnDocument
from pymongo.database import Database

DATABASE = os.getenv("MONGODB_DATABASE", "skill_orders_demo")
SERVICE = "orders-sync-demo"
CUSTOMERS = (
    ("aster", "Aster Labs", os.getenv("CUSTOMER_EMAIL", "support@aster.example")),
    ("cedar", "Cedar Systems", "support@cedar.example"),
)


class CredentialRefreshRejected(Exception):
    """The simulated order provider rejects this customer's renewal request."""


def seed(db: Database, scenario: str) -> None:
    """Insert missing fixtures; reruns never reset orders or erase evidence."""
    now = datetime.now(UTC)
    db.customers.create_index([("scenario", 1), ("slug", 1)], unique=True)
    db.orders.create_index([("customer_id", 1), ("number", 1)], unique=True)
    for slug, name, email in CUSTOMERS:
        customer = db.customers.find_one_and_update(
            {"scenario": scenario, "slug": slug},
            {"$setOnInsert": {
                "scenario": scenario,
                "name": name,
                "email": email,
                "provider": "Demo Orders",
                "access_expires_at": now + timedelta(hours=-1 if slug == "aster" else 1),
                "refresh_allowed": slug != "aster",
            }},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        for number in range(1, 4):
            db.orders.update_one(
                {"customer_id": customer["_id"], "number": number},
                {"$setOnInsert": {
                    "scenario": scenario,
                    "total_cents": 2500 * number,
                    "currency": "EUR",
                    "created_at": now,
                    "status": "pending",
                    "attempts": 0,
                }},
                upsert=True,
            )


def deliver_order(db: Database, customer: dict, order: dict) -> str:
    """Simulate the provider locally; no HTTP request or real credentials."""
    now = datetime.now(UTC)
    if customer["access_expires_at"] <= now:
        with logfire.span("Refresh provider credentials", customer_id=str(customer["_id"])):
            if not customer["refresh_allowed"]:
                raise CredentialRefreshRejected(
                    "Demo Orders rejected credential renewal; reconnect the customer account."
                )
            db.customers.update_one(
                {"_id": customer["_id"]},
                {"$set": {"access_expires_at": now + timedelta(hours=1)}},
            )
            logfire.info("Provider credentials renewed", customer_id=str(customer["_id"]))
    # A stable receipt models an idempotent destination for this synthetic order.
    return f"demo-receipt:{order['_id']}"


def simulate(db: Database, mode: str, scenario: str) -> dict:
    if mode not in {"fail", "recover"}:
        raise ValueError("Use fail or recover.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", scenario):
        raise ValueError("Use 1–60 letters, numbers, underscores or hyphens for the scenario.")
    affected_customer = {"scenario": scenario, "slug": "aster"}
    if mode == "recover" and db.customers.find_one(affected_customer) is None:
        raise ValueError("Run fail for this scenario before recovering it.")

    run_id = ObjectId()
    summary = {"scenario": scenario, "run_id": str(run_id), "mode": mode, "synced": 0, "failed": 0}
    with logfire.span("Synchronize orders", **summary) as batch:
        summary["trace_id"] = f"{batch.get_span_context().trace_id:032x}"
        seed(db, scenario)
        if mode == "recover":
            # Model the human repair: renewal is now allowed. The normal code path retries.
            repaired = db.customers.find_one_and_update(
                affected_customer,
                {"$set": {"refresh_allowed": True}},
                return_document=ReturnDocument.AFTER,
            )
            logfire.info("Customer connection repaired", customer_id=str(repaired["_id"]))

        orders = db.orders.find({"scenario": scenario, "status": {"$ne": "synced"}}).sort("_id", 1)
        for order in orders:
            customer = db.customers.find_one({"_id": order["customer_id"]})
            attempt_id = ObjectId()
            references = {
                "scenario": scenario,
                "run_id": run_id,
                "customer_id": customer["_id"],
                "order_id": order["_id"],
                "attempt_id": attempt_id,
                "attempt_number": order["attempts"] + 1,
            }
            # BSON in Mongo; plain hexadecimal text only at the telemetry boundary.
            attributes = {
                key: str(value) if isinstance(value, ObjectId) else value
                for key, value in references.items()
            }
            with logfire.span("Synchronize order {order_id}", **attributes) as span:
                attempt = {
                    "_id": attempt_id,
                    **references,
                    "started_at": datetime.now(UTC),
                    "trace_id": summary["trace_id"],
                    "span_id": f"{span.get_span_context().span_id:016x}",
                }
                try:
                    receipt = deliver_order(db, customer, order)
                except CredentialRefreshRejected:
                    attempt.update(status="failed", error_code="credential_refresh_rejected")
                    logfire.exception("Order synchronization failed", **attributes)
                    state = {"status": "failed", "last_error": attempt["error_code"]}
                    summary["failed"] += 1
                else:
                    attempt.update(status="synced", provider_receipt=receipt)
                    logfire.info("Order synchronized", **attributes, provider_receipt=receipt)
                    state = {"status": "synced", "last_error": None, "provider_receipt": receipt}
                    summary["synced"] += 1
                attempt["finished_at"] = datetime.now(UTC)
                db.sync_attempts.insert_one(attempt)
                db.orders.update_one(
                    {"_id": order["_id"]},
                    {"$set": {
                        **state,
                        "updated_at": attempt["finished_at"],
                        "last_attempt_id": attempt_id,
                        "last_trace_id": attempt["trace_id"],
                    }, "$inc": {"attempts": 1}},
                )

        for name in ("synced", "failed"):
            batch.set_attribute(name, summary[name])
        logfire.info("Batch finished: {synced} synchronized, {failed} failed", **summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["fail", "recover"])
    parser.add_argument("--scenario", default="demo", help="Use a new name for a fresh demonstration.")
    args = parser.parse_args()
    token = os.getenv("LOGFIRE_TOKEN", "").strip()
    if not token:
        parser.error("Set LOGFIRE_TOKEN to a project write token in orders-app/.env before generating or recovering orders.")
    logfire.configure(
        service_name=SERVICE,
        service_version="0.1.0",
        environment="demo",
        token=token,
        send_to_logfire=True,
        console=logfire.ConsoleOptions(output=sys.stderr),
        metrics=False,
    )
    try:
        with MongoClient(
            os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27029"),
            serverSelectionTimeoutMS=3000,
            tz_aware=True,
        ) as client:
            client.admin.command("ping")
            result = simulate(client[DATABASE], args.mode, args.scenario)
            print(json.dumps(result, indent=2))
    finally:
        logfire.force_flush()


if __name__ == "__main__":
    main()
