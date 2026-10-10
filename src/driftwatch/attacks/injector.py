"""Attack injector for DriftWatch-TE.

Implements the two injection channels described in architecture.md §3.3:

Channel A — ``tool_output``:
    The payload is appended to the review list of **every** product in
    ``world_state.reviews``.  This models the worst-case attacker: any product
    that the agent reads reviews for will return the payload.  If the world has
    no reviews, a sentinel product entry is created so the payload is reachable.

Channel B — ``tool_description``:
    The payload is appended to the *description* field of the named tool in the
    ``ToolRegistry``.  The LLM sees the poisoned description whenever it decides
    which tool to call.  The registry is mutated in place, so the **caller must
    pass a fresh registry per trial** to avoid bleed-over between trials.

Control / canary scenarios have ``injection=None``.  Calling :meth:`inject`
with ``injection=None`` or ``payload=None`` is a no-op — the world and registry
are left unchanged.

No real accounts, services, or repos are touched.  Attacks are confined to the
mock shop world (AGENTS.md rules 9, 6).
"""

from __future__ import annotations

import logging

from driftwatch.schema.models import Channel, Injection
from driftwatch.world.state import ShopState
from driftwatch.world.tools import ToolRegistry

logger = logging.getLogger(__name__)

# Sentinel product key used when the world has no review entries.
# This ensures the payload is reachable even in a minimal world state.
_SENTINEL_PRODUCT_ID = "__injected__"


class AttackInjector:
    """Injects attack payloads into world state or tool schemas before a trial.

    Designed to be stateless; a single instance can be reused across trials.
    State mutation is performed on the objects passed in, not on the injector.
    """

    def inject(
        self,
        channel: Channel,
        injection: Injection | None,
        payload: str | None,
        world_state: ShopState,
        tool_registry: ToolRegistry,
    ) -> None:
        """Apply the injection to *world_state* and/or *tool_registry*.

        Args:
            channel: Which injection channel to use (tool_output or
                tool_description).
            injection: The :class:`~driftwatch.schema.models.Injection` config
                from the scenario YAML.  If ``None`` (control / canary
                scenario), this method is a no-op.
            payload: Payload text returned by
                :func:`~driftwatch.attacks.loader.load_payload`.  If ``None``,
                the method is a no-op.
            world_state: The mutable world state for this trial.
            tool_registry: The tool registry for this trial.

        Raises:
            KeyError: For ``tool_description`` channel, if ``injection.tool``
                is not a registered tool name.
        """
        if injection is None or payload is None:
            logger.debug("No injection configured (control/canary scenario) — skipping.")
            return

        if channel == Channel.TOOL_OUTPUT:
            self._inject_tool_output(payload, world_state)
        elif channel == Channel.TOOL_DESCRIPTION:
            self._inject_tool_description(injection.tool, payload, tool_registry)
        else:
            # Exhaustive check — new channels must be handled here
            msg = f"Unknown injection channel: {channel!r}"
            raise ValueError(msg)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _inject_tool_output(self, payload: str, world_state: ShopState) -> None:
        """Append *payload* to every product's review list (tool_output channel).

        Uses worst-case-attacker semantics: the payload appears in any product's
        reviews the agent queries, regardless of which product order is associated
        with.  This matches AgentDojo / InjecAgent evaluation conventions.
        """
        if world_state.reviews:
            for product_id in world_state.reviews:
                world_state.reviews[product_id].append(payload)
                logger.debug(
                    "Injected payload into reviews of product '%s' (%d chars).",
                    product_id,
                    len(payload),
                )
        else:
            # No products exist — create a sentinel so the payload is reachable
            world_state.reviews[_SENTINEL_PRODUCT_ID] = [payload]
            logger.debug(
                "World has no reviews; created sentinel product '%s' with payload.",
                _SENTINEL_PRODUCT_ID,
            )

    def _inject_tool_description(
        self, tool_name: str, payload: str, tool_registry: ToolRegistry
    ) -> None:
        """Append *payload* to the description of *tool_name* (tool_description channel).

        The registry is mutated in place via
        :meth:`~driftwatch.world.tools.ToolRegistry.patch_description`.
        The caller is responsible for passing a fresh registry per trial.

        Raises:
            KeyError: If *tool_name* is not registered.
        """
        tool_registry.patch_description(tool_name, payload)
        logger.debug(
            "Injected payload into description of tool '%s' (%d chars).",
            tool_name,
            len(payload),
        )
