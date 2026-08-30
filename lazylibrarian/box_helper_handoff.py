"""Shared contract for the box helper's durable qBittorrent ownership."""

import os


BOX_HELPER_HANDOFF_PROTOCOL = "box-qbit-durable-intent-v1"
BOX_HELPER_HANDOFF_PROTOCOL_ENV = "BOX_LL_HANDOFF_PROTOCOL"
QBITTORRENT_LIFECYCLE_OWNER_ENV = "BOX_LL_QBIT_LIFECYCLE_OWNER"
QBITTORRENT_HELPER_OWNER = "helper"

PRE_REJECTED_PREFIX = "BOX_HELPER_PRE_REJECTED:"
POLICY_QUARANTINE_PREFIX = "BOX_HELPER_POLICY_QUARANTINE:"
DURABLE_OWNED_PREFIX = "BOX_HELPER_DURABLE_OWNED:"
DURABLE_OWNED_RESULT = DURABLE_OWNED_PREFIX + BOX_HELPER_HANDOFF_PROTOCOL


def configured_handoff_protocol():
    return os.environ.get(BOX_HELPER_HANDOFF_PROTOCOL_ENV, "").strip()


def configured_qbittorrent_lifecycle_owner():
    return os.environ.get(QBITTORRENT_LIFECYCLE_OWNER_ENV, "").strip().casefold()


def validate_box_helper_handoff_config():
    """Validate the LL side of the durable helper ownership contract.

    This image always emits durable qBittorrent intents, so it must never
    silently downgrade to LazyLibrarian-owned deletion.  Legacy behavior is
    available only by rolling back to an image that predates durable handoff.
    """
    protocol = configured_handoff_protocol()
    owner = configured_qbittorrent_lifecycle_owner()
    if protocol != BOX_HELPER_HANDOFF_PROTOCOL:
        raise RuntimeError(
            f"{BOX_HELPER_HANDOFF_PROTOCOL_ENV} must be "
            f"{BOX_HELPER_HANDOFF_PROTOCOL!r} when qBittorrent lifecycle ownership is configured"
        )
    if owner != QBITTORRENT_HELPER_OWNER:
        raise RuntimeError(
            f"{QBITTORRENT_LIFECYCLE_OWNER_ENV} must be "
            f"{QBITTORRENT_HELPER_OWNER!r} for durable qBittorrent handoff"
        )


def helper_owns_qbittorrent_lifecycle():
    """Deny LL removal even if startup validation was bypassed or changed."""
    # This durable-outbox image never owns qBittorrent removal. Startup checks
    # configuration correctness; this constant boundary protects runtime even
    # if startup validation is bypassed or the environment later changes.
    return True


def wanted_row_is_durable_helper_owned(row):
    """Identify a qBittorrent wanted row transferred to the durable helper."""
    if not helper_owns_qbittorrent_lifecycle():
        return False

    def row_value(key):
        try:
            return row[key]
        except (KeyError, TypeError):
            return row.get(key) if hasattr(row, "get") else None

    if str(row_value("Source") or "").upper() != "QBITTORRENT":
        return False
    result = str(row_value("DLResult") or "")
    return result.startswith(
        (DURABLE_OWNED_PREFIX, PRE_REJECTED_PREFIX, POLICY_QUARANTINE_PREFIX)
    )
