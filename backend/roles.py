"""Role definitions and the server-side rules that enforce them.

Three roles:

  superadmin       full access, including per-matter financials and user admin.
  trademark_admin  sees every matter, but never financial fields.
  drafter          sees only matters assigned to them, never financial fields,
                   and may only advance status / set deadlines -- not create,
                   edit, delete or export.

WHY THIS IS ENFORCED HERE AND NOT IN THE BROWSER
------------------------------------------------
The client holds the ledger as one JSON document and PUTs the whole thing on
every save. Two consequences drive this module's design:

1. A filtered read cannot be written straight back. A drafter is shown only
   their own matters; if their save were applied literally, every other matter
   in the firm would vanish. So a write is never "replace the document" for a
   restricted role -- it is a *merge* of the changes that role is allowed to
   make onto the stored document (see merge_for_role).

2. Hiding a field in the UI is not hiding it. Anything sent to the browser can
   be read from dev tools, so financial values are stripped from the payload
   server-side (see redact_for_role) rather than merely not rendered.
"""

import copy
import uuid
from datetime import datetime, timezone

SUPERADMIN = "superadmin"
TRADEMARK_ADMIN = "trademark_admin"
DRAFTER = "drafter"

ALL_ROLES = (SUPERADMIN, TRADEMARK_ADMIN, DRAFTER)

ROLE_LABELS = {
    SUPERADMIN: "Super admin",
    TRADEMARK_ADMIN: "Trademark admin",
    DRAFTER: "Drafter",
}

# Per-matter financial fields. Present on a record for superadmin only; removed
# from the payload entirely for everyone else.
FINANCIAL_FIELDS = (
    "officialFee",
    "professionalFee",
    "amountPaid",
    "paymentStatus",
    "invoiceRef",
)

# The only record fields a drafter may change, on a matter assigned to them.
#
# 'timeline' is deliberately NOT here. It is a matter's stage history, and a
# drafter able to write it could backdate a filing, invent a transition, or
# delete the record of a missed deadline -- on a legal ledger that is the most
# damaging thing a restricted account could do. The server appends timeline
# entries itself instead (see _stage_entry).
DRAFTER_EDITABLE_FIELDS = ("status", "actionDate", "action")

# Ledger-wide settings (the shared login passphrase and its hash) belong to the
# superadmin. They travel in the same document as the matters, so without this
# any role permitted to save would carry them along and could overwrite them.
PROTECTED_SETTINGS = True

# Most log entries one save can add. A save is one user action; anything
# wildly beyond this is a client bug or an attempt to flood the history.
MAX_NEW_LOG_ENTRIES = 25


def can(role, capability):
    """Whether a role has a named capability."""
    return capability in CAPABILITIES.get(role, ())


CAPABILITIES = {
    SUPERADMIN: (
        "view_all", "view_financials", "edit_financials",
        "create_matter", "edit_matter", "delete_matter",
        "change_status", "manage_clients", "export", "import", "manage_users",
    ),
    TRADEMARK_ADMIN: (
        "view_all",
        "create_matter", "edit_matter", "delete_matter",
        "change_status", "manage_clients", "export", "import",
    ),
    DRAFTER: (
        "change_status",
    ),
}


def capabilities(role):
    return list(CAPABILITIES.get(role, ()))


def _record_is_visible(record, role, username):
    if role == DRAFTER:
        return (record.get("assignedTo") or "").lower() == (username or "").lower()
    return True


def redact_for_role(document, role, username):
    """The ledger as this role is allowed to receive it.

    Financial fields are removed rather than blanked, so a value never reaches
    a browser that is not entitled to it.
    """
    if document is None:
        return None
    doc = copy.deepcopy(document)

    if role == SUPERADMIN:
        return doc

    records = []
    for record in doc.get("records", []):
        if not _record_is_visible(record, role, username):
            continue
        for field in FINANCIAL_FIELDS:
            record.pop(field, None)
        records.append(record)
    doc["records"] = records

    if role == DRAFTER:
        # The activity log names every matter in the firm, including ones this
        # drafter cannot see. Withhold it rather than leak matter names through
        # the back door.
        doc["log"] = []

        # Same reasoning for the client list. Filtering the records but shipping
        # every client still discloses the firm's whole client roster in the
        # dropdown -- who a firm acts for is itself confidential. Keep only the
        # clients this drafter's own matters point at.
        visible_client_ids = {r.get("clientId") for r in records}
        doc["clients"] = [c for c in doc.get("clients", [])
                          if c.get("id") in visible_client_ids]

    return doc


def _stage_entry(from_status, to_status, username, remarks, deadline):
    """A timeline entry the SERVER wrote, for a change it actually observed."""
    return {
        "id": "st-" + uuid.uuid4().hex[:12],
        "fromStatus": from_status,
        "toStatus": to_status,
        "effectiveDate": datetime.now(timezone.utc).date().isoformat(),
        "deadline": deadline or None,
        "remarks": remarks or "",
        "by": username,
        "serverGenerated": True,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _merge_record(stored, incoming, role, username=""):
    """One record, merged according to what `role` may change."""
    merged = copy.deepcopy(stored)

    if role == DRAFTER:
        for field in DRAFTER_EDITABLE_FIELDS:
            if field in incoming:
                merged[field] = copy.deepcopy(incoming[field])

        # The stored timeline is authoritative; the payload's copy is ignored.
        # If the status really moved, record that here so the history still
        # grows -- attributed, and stamped with the server's clock.
        timeline = copy.deepcopy(stored.get("timeline") or [])
        old_status = stored.get("status")
        new_status = merged.get("status")
        if new_status and new_status != old_status:
            timeline.insert(0, _stage_entry(
                old_status, new_status, username,
                merged.get("action"), merged.get("actionDate")))
        merged["timeline"] = timeline
        return merged

    # trademark_admin: everything except the financial fields, which it never
    # received and therefore cannot be allowed to overwrite (or blank).
    merged.update({k: copy.deepcopy(v) for k, v in incoming.items()
                   if k not in FINANCIAL_FIELDS})
    for field in FINANCIAL_FIELDS:
        if field in stored:
            merged[field] = stored[field]
        else:
            merged.pop(field, None)
    return merged


def merge_for_role(stored, incoming, role, username):
    """Apply a role's permitted changes onto the stored ledger.

    `stored` is the authoritative document (may be None on a first save);
    `incoming` is what the browser sent. Returns the document to persist.
    Anything the role may not change is taken from `stored`, so a filtered or
    tampered payload can neither delete nor reveal what it never had.
    """
    if role == SUPERADMIN:
        return incoming

    base = copy.deepcopy(stored) if stored else {
        "clients": [], "records": [], "log": [],
        "nextClientSeq": 1, "nextRecordSeq": 1,
    }

    stored_records = {r.get("id"): r for r in base.get("records", []) if r.get("id")}
    incoming_records = {r.get("id"): r for r in incoming.get("records", []) if r.get("id")}

    if role == DRAFTER:
        # A drafter may not add, remove or reassign matters -- only edit the
        # permitted fields on matters already assigned to them. The record list
        # therefore always comes from storage, never from the payload.
        result_records = []
        for record in base.get("records", []):
            rid = record.get("id")
            if rid in incoming_records and _record_is_visible(record, DRAFTER, username):
                result_records.append(
                    _merge_record(record, incoming_records[rid], DRAFTER, username))
            else:
                result_records.append(record)
        base["records"] = result_records
        # Clients, sequences and settings stay as stored; only the log grows.
        base["log"] = _merged_log(base, incoming, username)
        return base

    # trademark_admin -- may add, edit and delete matters and clients, but must
    # not touch financial values on matters that already exist.
    result_records = []
    for record in incoming.get("records", []):
        rid = record.get("id")
        if rid in stored_records:
            result_records.append(_merge_record(stored_records[rid], record, TRADEMARK_ADMIN))
        else:
            # A newly created matter: it simply has no financial values yet.
            fresh = {k: v for k, v in record.items() if k not in FINANCIAL_FIELDS}
            result_records.append(fresh)

    merged = copy.deepcopy(incoming)
    merged["records"] = result_records
    merged["log"] = _merged_log(base, incoming, username)
    # Ledger-wide settings (the shared login passphrase hash) are the
    # superadmin's; a trademark admin's save must carry the stored value rather
    # than whatever its payload happens to contain.
    if "settings" in base:
        merged["settings"] = copy.deepcopy(base["settings"])
    else:
        merged.pop("settings", None)
    return merged


def _merged_log(base, incoming, username=""):
    """Keep stored log entries, prepending any new ones from the client.

    A restricted client may have been given a trimmed log (or none), so its
    payload must never be treated as the whole history -- only as a source of
    entries to ADD.

    Every added entry is re-stamped: the timestamp comes from the server's
    clock and the author from the session. Otherwise a client could backdate an
    entry, or attribute its own action to someone else, and the log would be
    worthless as a record of who did what.
    """
    stored_log = base.get("log", []) or []
    incoming_log = incoming.get("log", []) or []
    known = {(e.get("ts"), e.get("summary")) for e in stored_log}
    known_summaries = {e.get("summary") for e in stored_log}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fresh = []
    for entry in incoming_log:
        if not isinstance(entry, dict):
            continue
        summary = entry.get("summary")
        if (entry.get("ts"), summary) in known or summary in known_summaries:
            continue
        fresh.append({"ts": now, "summary": summary, "by": username})
        if len(fresh) >= MAX_NEW_LOG_ENTRIES:
            break

    return (fresh + stored_log)[:500]
