"""Tests for ShopState and load_world.

All tests run offline — no real LLM APIs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from driftwatch.world.state import (
    AddressUpdate,
    Customer,
    Order,
    Refund,
    SentEmail,
    ShopState,
    load_world,
)

# Path to the shared world fixture
WORLDS_DIR = Path(__file__).parent.parent / "worlds"
SHOP_V1 = WORLDS_DIR / "shop_v1.yaml"


class TestLoadWorld:
    def test_loads_shop_v1(self) -> None:
        state = load_world(SHOP_V1)
        assert isinstance(state, ShopState)

    def test_customer_count(self) -> None:
        state = load_world(SHOP_V1)
        assert len(state.customers) == 3

    def test_order_count(self) -> None:
        state = load_world(SHOP_V1)
        assert len(state.orders) == 4

    def test_reviews_loaded(self) -> None:
        state = load_world(SHOP_V1)
        assert "WIDGET_PRO" in state.reviews
        assert len(state.reviews["WIDGET_PRO"]) >= 1

    def test_initially_no_refunds(self) -> None:
        state = load_world(SHOP_V1)
        assert state.refunds == {}

    def test_initially_no_emails(self) -> None:
        state = load_world(SHOP_V1)
        assert state.sent_emails == []

    def test_initially_no_address_updates(self) -> None:
        state = load_world(SHOP_V1)
        assert state.address_updates == []

    def test_customer_fields(self) -> None:
        state = load_world(SHOP_V1)
        alice = state.customers["9981"]
        assert alice.name == "Alice Johnson"
        assert alice.email == "alice@example.com"
        assert alice.address != ""

    def test_order_fields(self) -> None:
        state = load_world(SHOP_V1)
        order = state.orders["1042"]
        assert order.account == "9981"
        assert order.refundable is True
        assert order.amount == pytest.approx(49.99)

    def test_non_refundable_order(self) -> None:
        state = load_world(SHOP_V1)
        order = state.orders["1099"]
        assert order.refundable is False

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_world(tmp_path / "no_such_world.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("customers: not_a_dict", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid world YAML"):
            load_world(bad)

    def test_empty_yaml_returns_empty_state(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        state = load_world(empty)
        assert state.customers == {}
        assert state.orders == {}


class TestShopStateFreshCopy:
    def test_fresh_copy_is_independent(self) -> None:
        """Mutations to the copy must not affect the original (trial isolation)."""
        state = load_world(SHOP_V1)
        copy = state.fresh_copy()

        # Mutate the copy
        copy.sent_emails.append(SentEmail(to="x@x.com", subject="s", body="b"))
        assert len(state.sent_emails) == 0
        assert len(copy.sent_emails) == 1

    def test_fresh_copy_order_mutation_isolated(self) -> None:
        state = load_world(SHOP_V1)
        copy = state.fresh_copy()
        copy.orders["1042"].refundable = False
        assert state.orders["1042"].refundable is True

    def test_fresh_copy_refunds_isolated(self) -> None:
        state = load_world(SHOP_V1)
        copy = state.fresh_copy()
        copy.refunds["r1"] = Refund(refund_id="r1", order_id="1042", account="9981", amount=49.99)
        assert "r1" not in state.refunds


class TestShopStateModels:
    def test_customer_model(self) -> None:
        c = Customer(account="1", name="Test", email="t@t.com")
        assert c.address == ""

    def test_order_refundable_default(self) -> None:
        o = Order(order_id="x", account="1", product_id="P", status="delivered", amount=10.0)
        assert o.refundable is True

    def test_sent_email_fields(self) -> None:
        e = SentEmail(to="a@b.com", subject="Hi", body="Hello")
        assert e.to == "a@b.com"

    def test_address_update_fields(self) -> None:
        u = AddressUpdate(account="9981", old_address="Old", new_address="New")
        assert u.new_address == "New"
