"""Integration checks against a local MongoDB; telemetry stays in memory."""

import os
from uuid import uuid4

import pytest
from bson import ObjectId
from logfire.testing import capfire  # noqa: F401 -- pytest fixture
from pymongo import MongoClient

from simulate_orders import simulate


@pytest.fixture
def db():
    with MongoClient(
        os.getenv("TEST_MONGODB_URI", "mongodb://127.0.0.1:27029"),
        serverSelectionTimeoutMS=3000,
        tz_aware=True,
    ) as client:
        client.admin.command("ping")
        name = f"orders_demo_test_{uuid4().hex}"
        try:
            yield client[name]
        finally:
            client.drop_database(name)


def test_failure_recovery_and_repeated_execution_preserve_evidence(db, capfire):
    failed = simulate(db, "fail", "test")
    aster = db.customers.find_one({"scenario": "test", "slug": "aster"})["_id"]
    cedar = db.customers.find_one({"scenario": "test", "slug": "cedar"})["_id"]
    assert (failed["synced"], failed["failed"]) == (3, 3)
    assert db.orders.count_documents({"customer_id": aster, "status": "failed"}) == 3
    assert db.orders.count_documents({"customer_id": cedar, "status": "synced"}) == 3
    assert db.sync_attempts.count_documents({}) == 6

    retried = simulate(db, "fail", "test")
    assert (retried["synced"], retried["failed"]) == (0, 3)

    recovered = simulate(db, "recover", "test")
    assert (recovered["synced"], recovered["failed"]) == (3, 0)
    assert db.orders.count_documents({"status": "synced"}) == 6
    assert db.sync_attempts.count_documents({"status": "failed"}) == 6
    assert db.sync_attempts.count_documents({}) == 12
    assert db.orders.count_documents({"customer_id": cedar, "attempts": 1}) == 3
    assert db.orders.count_documents({"customer_id": aster, "attempts": 3}) == 3
    assert db.orders.count_documents({"last_error": {"$ne": None}}) == 0

    repeated = simulate(db, "recover", "test")
    assert (repeated["synced"], repeated["failed"]) == (0, 0)
    assert db.sync_attempts.count_documents({}) == 12

    spans = capfire.exporter.exported_spans_as_dict()
    span_refs = {
        (f"{span['context']['trace_id']:032x}", f"{span['context']['span_id']:016x}")
        for span in spans
    }
    for attempt in db.sync_attempts.find({}):
        assert (attempt["trace_id"], attempt["span_id"]) in span_refs
        for field in ("_id", "customer_id", "order_id", "attempt_id", "run_id"):
            assert isinstance(attempt[field], ObjectId)
        order = db.orders.find_one({"_id": attempt["order_id"]})
        assert order["customer_id"] == attempt["customer_id"]
        assert db.customers.find_one({"_id": order["customer_id"]}) is not None
        assert isinstance(order["last_attempt_id"], ObjectId)
        assert db.sync_attempts.find_one({"_id": order["last_attempt_id"]}) is not None
        assert any(
            span["attributes"].get("attempt_id") == str(attempt["_id"])
            and span["attributes"].get("order_id") == str(order["_id"])
            for span in spans
        )
    assert any(span["attributes"].get("exception.type") for span in spans) or any(
        event["name"] == "exception" for span in spans for event in span.get("events", [])
    )


def test_scenarios_are_isolated_and_recovery_needs_existing_data(db, capfire):
    with pytest.raises(ValueError):
        simulate(db, "recover", "missing")
    assert db.orders.count_documents({}) == 0
    simulate(db, "fail", "first")
    simulate(db, "fail", "second")
    simulate(db, "recover", "second")
    assert db.orders.count_documents({"scenario": "first", "status": "failed"}) == 3
    assert db.orders.count_documents({"scenario": "second", "status": "synced"}) == 6


def test_reset_allows_recreating_the_failed_scenario(db, capfire):
    from reset_orders import reset_orders

    simulate(db, "fail", "demo")
    simulate(db, "recover", "demo")
    original_ids = {row["_id"] for row in db.orders.find({})}
    customers_before = {
        row["_id"]: (row["name"], row["email"]) for row in db.customers.find({})
    }
    indexes_before = db.orders.index_information()
    db.extra_fixture.insert_one({"note": "Keep unrelated collections."})

    reset_orders(db)
    assert db.orders.count_documents({}) == 0
    assert db.sync_attempts.count_documents({}) == 0
    assert db.extra_fixture.count_documents({}) == 1
    assert db.orders.index_information() == indexes_before
    assert {
        row["_id"]: (row["name"], row["email"]) for row in db.customers.find({})
    } == customers_before

    recreated = simulate(db, "fail", "demo")
    assert (recreated["synced"], recreated["failed"]) == (3, 3)
    assert db.customers.count_documents({}) == 2
    assert db.sync_attempts.count_documents({}) == 6
    assert original_ids.isdisjoint({row["_id"] for row in db.orders.find({})})
    assert {row["_id"] for row in db.customers.find({})} == set(customers_before)
    simulate(db, "fail", "demo")
    assert db.customers.count_documents({}) == 2
    assert db.orders.count_documents({}) == 6
