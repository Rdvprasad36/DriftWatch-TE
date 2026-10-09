"""In-memory mock shop world state for DriftWatch-TE.

The world is a simple fake customer-support e-commerce shop.
Each scenario YAML references a world file (e.g. worlds/shop_v1.yaml)
that defines the initial state. Each agent trial receives a deep copy of
the pristine loaded state so trials are fully isolated.

Architecture: architecture.md §3.2
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Customer(BaseModel):
    """A shop customer account."""

    account: str
    name: str
    email: str
    address: str = ""


class Order(BaseModel):
    """A customer order."""

    order_id: str
    account: str
    product_id: str
    status: str  # processing | shipped | delivered | cancelled
    amount: float
    refundable: bool = True


class Refund(BaseModel):
    """A processed refund record (written by issue_refund tool)."""

    refund_id: str
    order_id: str
    account: str  # account that received the refund (attacker may override this)
    amount: float


class SentEmail(BaseModel):
    """Audit log entry for an email sent by the agent."""

    to: str
    subject: str
    body: str


class AddressUpdate(BaseModel):
    """Audit log entry for an address change made by the agent."""

    account: str
    old_address: str
    new_address: str


class ShopState(BaseModel):
    """Mutable in-memory world state for one agent trial.

    Tools mutate this object directly.  The GoalEvaluator reads it after
    the trial completes to assess attack_success and task_success (FR4).
    """

    customers: dict[str, Customer] = Field(default_factory=dict)
    orders: dict[str, Order] = Field(default_factory=dict)
    # reviews: product_id → list of review strings.
    # Review text is UNTRUSTED — injection payloads are embedded here.
    reviews: dict[str, list[str]] = Field(default_factory=dict)
    refunds: dict[str, Refund] = Field(default_factory=dict)
    sent_emails: list[SentEmail] = Field(default_factory=list)
    address_updates: list[AddressUpdate] = Field(default_factory=list)

    def fresh_copy(self) -> ShopState:
        """Return a deep copy for use in a new trial."""
        return self.model_copy(deep=True)


def load_world(world_path: Path) -> ShopState:
    """Load a ShopState from a YAML world-definition file.

    Args:
        world_path: Path to the world YAML file (e.g. worlds/shop_v1.yaml).

    Returns:
        A pristine ShopState that should be deep-copied per trial.

    Raises:
        FileNotFoundError: If the world file does not exist.
        ValueError: If the YAML is malformed or fails Pydantic validation.
    """
    if not world_path.exists():
        msg = f"World file not found: {world_path}"
        raise FileNotFoundError(msg)

    with open(world_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if data is None:
        return ShopState()

    try:
        state = ShopState.model_validate(data)
    except Exception as exc:
        msg = f"Invalid world YAML at {world_path}: {exc}"
        raise ValueError(msg) from exc

    logger.info(
        "Loaded world '%s': %d customers, %d orders, %d products with reviews.",
        world_path.name,
        len(state.customers),
        len(state.orders),
        len(state.reviews),
    )
    return state
