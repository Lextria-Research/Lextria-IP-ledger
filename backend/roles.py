"""Role definitions and the server-side rules that enforce them.

Three roles:

  superadmin       full access, including per-matter financials and user admin.
  trademark_admin  sees every matter of every IP type (trademark, copyright and
                   design), but never financial fields.
  drafter          sees only matters assigned to them, never financial fields,
                   and may only advance status / set deadlines -- not create,
                   edit, delete or export.

WHY THIS IS ENFORCED HERE AND NOT IN THE BROWSER
------------------------------------------------
The client holds the ledger as one JSON document and PUTs the whole thing on
every save. Three consequences drive this module's design:

1. A filtered read cannot be written straight back. A drafter is shown only
   their own matters; if their save were applied literally, every other matter
   in the firm would vanish. So a write is never "replace the document" for a
   restricted role -- it is a *merge* of the changes that role is allowed to
   make onto the stored document (see merge_for_role).

2. Hiding a field in the UI is not hiding it. Anything sent to the browser can
   be read from dev tools, so financial values are stripped from the payload
   server-side (see redact_for_role) rather than merely not rendered.

3. Two people saving around the same time must not silently clobber each
   other. Every non-drafter save is a three-way merge against BASELINE (what
   the saver last loaded), STORED (what is actually there now) and INCOMING
   (what they are trying to save) -- see _reconcile_collection. This is what
   stops one admin's save from reverting another's concurrent edit, and what
   stops two people creating a new matter at the same moment from colliding on
   the same id and destroying one of the two matters.
"""

import copy
import re
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

# The IP types the ledger tracks. The roles above are deliberately NOT scoped by
# type -- a trademark admin administers copyright and design matters too. The
# tuple exists so the server can reject a matter with a type the front end has
# no pipeline for, rather than silently storing an unrenderable record.
IP_TYPES = ("trademark", "copyright", "design")
DEFAULT_IP_TYPE = "trademark"

# Per-matter financial fields. Present on a record for superadmin only; removed
# from the payload entirely for everyone else.
FINANCIAL_FIELDS = (
    "officialFee",
    "professionalFee",
    "amountPaid",
    "paymentStatus",
    "invoiceRef",
    "currency",
    "feeNotes",
)

# The only record fields a drafter may change, on a matter assigned to them.
#
# 'timeline' is deliberately NOT here. It is a matter's stage history, and a
# drafter able to write it could backdate a filing, invent a transition, or
# delete the record of a missed deadline -- on a legal ledger that is the most
# damaging thing a restricted account could do. The server appends timeline
# entries itself instead (see _stage_entry).
DRAFTER_EDITABLE_FIELDS = ("status", "actionDate", "action", "renewDate")

# Most log entries one save can add. A save is one user action; anything wildly
# beyond this is a client bug or an attempt to flood the history.
MAX_NEW_LOG_ENTRIES = 25


CAPABILITIES = {
    SUPERADMIN: (
        "view_all", "view_financials", "edit_financials",
        "create_matter", "edit_matter", "delete_matter",
        "change_status", "manage_clients", "export", "import", "manage_users",
        "assign_matter",
        # Bulk, ledger-wide destructive tools (Clear all matters / de-dup).
        # Deliberately separate from delete_matter (deleting one matter at a
        # time) -- a role that may tidy up a single record should not also get
        # a button that empties the entire firm's ledger in one click.
        "bulk_manage",
    ),
    TRADEMARK_ADMIN: (
        "view_all",
        "create_matter", "edit_matter", "delete_matter",
        "change_status", "manage_clients", "export", "import",
        "assign_matter",
    ),
    DRAFTER: (
        "change_status",
    ),
}


def can(role, capability):
    """Whether a role has a named capability."""
    return capability in CAPABILITIES.get(role, ())


def capabilities(role):
    return list(CAPABILITIES.get(role, ()))


def normalize_ip_type(value):
    """A known IP type, defaulting rather than rejecting.

    Anything unrecognised becomes the default type instead of raising: a record
    whose type the server does not know would be unrenderable in the front end,
    and dropping a whole save over one bad field is worse than filing that
    matter under the most common type, where a person will see it and correct it.
    """
    value = (value or "").strip().lower()
    return value if value in IP_TYPES else DEFAULT_IP_TYPE


def _record_is_visible(record, role, username):
    if role == DRAFTER:
        return (record.get("assignedTo") or "").lower() == (username or "").lower()
    return True


def _entry_is_financial(entry):
    """Whether a log entry describes a financial change.

    The client marks these when it writes them. An entry like "Set professional
    fee to 25,000" hands a trademark admin the exact number that redact_for_role
    just stripped from the record, so the log needs the same treatment as the
    fields themselves. Unmarked entries are treated as non-financial: the flag
    is only ever set by the code that edits a fee, so its absence is not a
    silent leak -- and defaulting the other way would blank the whole history
    for everyone but a superadmin.
    """
    return bool(entry.get("financial"))


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

    # Financial log entries name the amounts the loop above just stripped.
    log = [e for e in (doc.get("log") or [])
           if isinstance(e, dict) and not _entry_is_financial(e)]

    if role == DRAFTER:
        # Full log entries name every matter in the firm, including ones this
        # drafter cannot see -- but an entry the SERVER attributed to this
        # drafter is, by construction, only ever about a matter assigned to
        # them, so it is safe (and useful) to show. Entries from before
        # attribution existed (no "by") and everyone else's are withheld.
        log = [e for e in log
               if (e.get("by") or "").lower() == (username or "").lower()]

        # Same reasoning for the client list. Filtering the records but shipping
        # every client still discloses the firm's whole client roster in the
        # dropdown -- who a firm acts for is itself confidential. Keep only the
        # clients this drafter's own matters point at.
        visible_client_ids = {r.get("clientId") for r in records}
        doc["clients"] = [c for c in doc.get("clients", [])
                          if c.get("id") in visible_client_ids]

    doc["log"] = log
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
    """One record, merged according to what `role` may change.

    Used both for a drafter's single-field update and, via _reconcile_collection,
    for a trademark admin's full record edit.
    """
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
    merged["ipType"] = normalize_ip_type(merged.get("ipType"))
    return merged


# --- Three-way reconciliation ------------------------------------------------
#
# Applied to both the client list and the record list, for every role that may
# edit them (superadmin, trademark_admin). Comparing three versions of the same
# collection -- what the saver last loaded (baseline), what is actually stored
# now (stored), and what they are trying to save (incoming) -- is what tells
# apart:
#   - a deliberate edit / delete (present in baseline, changed or missing now)
#   - someone ELSE's concurrent edit (differs between baseline and stored,
#     which must not be thrown away just because this saver's copy predates it)
#   - two people creating a "new" item that happens to land on the same id
#     (present in stored and incoming, but NOT in baseline -- a stranger to
#     both, not an edit of one by the other)
#
# baseline may be None, meaning "unknown" (the client's revision was never
# recorded, or its history has since been pruned). Every branch below has an
# explicit fallback for that case, documented inline.

def _index_by_id(items):
    return {i.get("id"): i for i in (items or []) if isinstance(i, dict) and i.get("id")}


def _make_id_allocator(prefix, width=0):
    """A fresh, collision-free id generator for one save's reconciliation.

    Mirrors the id shape the front end itself uses (t-001.. for records, c-1..
    for clients) so a server-assigned id is indistinguishable from a normal one.
    """
    pattern = re.compile(r"^" + re.escape(prefix) + r"(\d+)$")

    def allocate(used_ids):
        highest = 0
        for uid in used_ids:
            m = pattern.match(uid or "")
            if m:
                highest = max(highest, int(m.group(1)))
        n = highest + 1
        return ("%s%0*d" % (prefix, width, n)) if width else ("%s%d" % (prefix, n))

    return allocate


def _reconcile_collection(baseline_items, stored_items, incoming_items,
                          allocate_id, apply_edit, prepare_new=None):
    """Three-way merge of one id-keyed collection (records, or clients).

    Returns (merged_list, id_remap) where id_remap maps an id the client
    proposed to the id it was actually saved under, for the rare case where a
    genuine collision required a reassignment.
    """
    baseline_by_id = _index_by_id(baseline_items) if baseline_items is not None else None
    stored_by_id = _index_by_id(stored_items)
    incoming_by_id = _index_by_id(incoming_items)

    result = []
    used_ids = set(stored_by_id.keys())
    id_remap = {}
    collided_incoming = []

    for sid, stored_item in stored_by_id.items():
        if sid in incoming_by_id:
            incoming_item = incoming_by_id[sid]
            if baseline_by_id is not None and sid not in baseline_by_id:
                # This id exists in stored but the saver's baseline never had
                # it: it cannot be "their" record to edit. Keep the existing one
                # untouched; the incoming item is a genuinely different, newly
                # created item that only happens to share this id (two people
                # created something at the same moment) -- re-file it under a
                # fresh id below rather than merging it in.
                result.append(copy.deepcopy(stored_item))
                collided_incoming.append((sid, incoming_item))
                continue
            if baseline_by_id is not None and baseline_by_id.get(sid) == incoming_item:
                # Unchanged from what this saver loaded: they didn't touch it,
                # so take the CURRENT stored version, which may carry someone
                # else's newer edit that must not be reverted.
                result.append(copy.deepcopy(stored_item))
            else:
                # Either a deliberate edit, or baseline is unknown and this is a
                # best-effort apply (documented limitation: without a baseline,
                # staleness cannot be detected).
                result.append(apply_edit(stored_item, incoming_item))
        else:
            if baseline_by_id is None:
                # No baseline to consult (the caller sent no revision, or it was
                # too old for history to still hold): fall back to honouring the
                # omission as a delete. Every Delete-button and Clear-All flow
                # relies on exactly this, and a caller that does not participate
                # in revision tracking (an older page still cached in a browser,
                # or a bare API client) must keep working as it did before.
                pass
            elif sid in baseline_by_id:
                # The saver had it, and their save omits it: a deliberate delete
                # (the Delete button, Clear All, or an import that replaces the
                # ledger).
                pass
            else:
                # Neither in the saver's baseline nor in their payload: it was
                # added by someone else after the saver's baseline. They never
                # knew it existed, so omitting it was never a decision to
                # delete it.
                result.append(copy.deepcopy(stored_item))

    for iid, incoming_item in incoming_by_id.items():
        if iid in stored_by_id:
            continue  # handled above (edit, no-op, or flagged as a collision)
        new_item = prepare_new(incoming_item) if prepare_new else copy.deepcopy(incoming_item)
        if iid and iid not in used_ids:
            new_item["id"] = iid
            used_ids.add(iid)
        else:
            fresh_id = allocate_id(used_ids)
            id_remap[iid] = fresh_id
            new_item["id"] = fresh_id
            used_ids.add(fresh_id)
        result.append(new_item)

    for sid, incoming_item in collided_incoming:
        new_item = prepare_new(incoming_item) if prepare_new else copy.deepcopy(incoming_item)
        fresh_id = allocate_id(used_ids)
        id_remap[sid] = fresh_id
        new_item["id"] = fresh_id
        used_ids.add(fresh_id)
        result.append(new_item)

    return result, id_remap


def _max_seq(items, prefix):
    highest = 0
    pattern = re.compile(r"^" + re.escape(prefix) + r"(\d+)$")
    for item in items or []:
        m = pattern.match(item.get("id") or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return highest


def merge_for_role(stored, incoming, role, username, baseline=None):
    """Apply a role's permitted changes onto the stored ledger.

    `stored` is the authoritative document (may be None on a first save);
    `incoming` is what the browser sent; `baseline` is the document as it stood
    the last time this browser successfully loaded it (None if unknown -- see
    backend/main.py for how that is looked up from ledger_history).

    Returns (document_to_persist, id_remap), where id_remap notes any record or
    client whose proposed id had to be replaced (collision with something
    created concurrently) -- shaped {"records": {...}, "clients": {...}}.
    Anything the role may not change is taken from `stored`, so a filtered or
    tampered payload can neither delete nor reveal what it never had.
    """
    empty_remap = {"records": {}, "clients": {}}

    if stored is None:
        stored = {"clients": [], "records": [], "log": [],
                  "nextClientSeq": 1, "nextRecordSeq": 1}

    if role == DRAFTER:
        # A drafter may not add, remove or reassign matters -- only edit the
        # permitted fields on matters already assigned to them. The record list
        # therefore always comes from storage, never from the payload, and there
        # is nothing here that concurrent editing by someone else could put at
        # risk (a drafter never touches a field derived from a stale read of
        # another field).
        base = copy.deepcopy(stored)
        incoming_records = _index_by_id(incoming.get("records", []))
        result_records = []
        for record in base.get("records", []):
            rid = record.get("id")
            if rid in incoming_records and _record_is_visible(record, DRAFTER, username):
                result_records.append(
                    _merge_record(record, incoming_records[rid], DRAFTER, username))
            else:
                result_records.append(record)
        base["records"] = result_records
        base["log"] = _merged_log(base, incoming, username, role)
        return base, empty_remap

    # --- superadmin and trademark_admin: three-way merge --------------------
    stored_clients = stored.get("clients", [])
    incoming_clients = incoming.get("clients", []) if isinstance(incoming.get("clients"), list) else []
    baseline_clients = baseline.get("clients") if isinstance(baseline, dict) else None

    def client_edit(_stored_item, incoming_item):
        return copy.deepcopy(incoming_item)

    merged_clients, client_id_remap = _reconcile_collection(
        baseline_clients, stored_clients, incoming_clients,
        _make_id_allocator("c-"), client_edit)

    # A record in this SAME payload that pointed at a client id which just got
    # reassigned (because of a collision) must follow it, or it would end up
    # referencing a client id that no longer exists.
    incoming_records = copy.deepcopy(incoming.get("records", [])) if isinstance(incoming.get("records"), list) else []
    if client_id_remap:
        for rec in incoming_records:
            if isinstance(rec, dict) and rec.get("clientId") in client_id_remap:
                rec["clientId"] = client_id_remap[rec["clientId"]]

    stored_records = stored.get("records", [])
    baseline_records = baseline.get("records") if isinstance(baseline, dict) else None

    def record_edit(stored_item, incoming_item):
        if role == TRADEMARK_ADMIN:
            return _merge_record(stored_item, incoming_item, TRADEMARK_ADMIN)
        merged = copy.deepcopy(incoming_item)  # superadmin: full authority
        merged["ipType"] = normalize_ip_type(merged.get("ipType"))
        return merged

    def record_prepare_new(incoming_item):
        if role == TRADEMARK_ADMIN:
            # A newly created matter simply has no financial values yet.
            fresh = {k: v for k, v in incoming_item.items()
                     if k not in FINANCIAL_FIELDS}
        else:
            fresh = copy.deepcopy(incoming_item)
        fresh["ipType"] = normalize_ip_type(fresh.get("ipType"))
        return fresh

    merged_records, record_id_remap = _reconcile_collection(
        baseline_records, stored_records, incoming_records,
        _make_id_allocator("t-", width=3), record_edit, record_prepare_new)

    merged = copy.deepcopy(incoming)
    merged["clients"] = merged_clients
    merged["records"] = merged_records
    merged["log"] = _merged_log(stored, incoming, username, role)

    if role == SUPERADMIN:
        # Settings get the same "did you actually touch this" treatment: if
        # unchanged from this saver's baseline, prefer whatever is currently
        # stored, so one superadmin's stale tab cannot clobber another's
        # concurrent settings change.
        if (isinstance(baseline, dict) and
                incoming.get("settings") == baseline.get("settings") and
                "settings" in stored):
            merged["settings"] = copy.deepcopy(stored["settings"])
    else:
        # Ledger-wide settings belong to the superadmin; a trademark admin's
        # save must carry the stored value rather than whatever its payload
        # happens to contain.
        if "settings" in stored:
            merged["settings"] = copy.deepcopy(stored["settings"])
        else:
            merged.pop("settings", None)

    # nextClientSeq / nextRecordSeq are client-side hints for "what to try
    # next"; keep them monotonic across the whole ledger so they never regress
    # below what has actually been allocated, by anyone, ever.
    merged["nextClientSeq"] = max(
        incoming.get("nextClientSeq") or 1, stored.get("nextClientSeq") or 1,
        _max_seq(merged_clients, "c-") + 1)
    merged["nextRecordSeq"] = max(
        incoming.get("nextRecordSeq") or 1, stored.get("nextRecordSeq") or 1,
        _max_seq(merged_records, "t-") + 1)

    return merged, {"records": record_id_remap, "clients": client_id_remap}


def validate_assignments(document, active_usernames):
    """Clear any assignedTo that no longer names a real, active account.

    Returns the list of matter ids that were cleared, so the caller can warn
    about it. A typo'd or stale username is silently invisible to every drafter
    otherwise -- there is no other signal anywhere that it happened.
    """
    valid = {u.lower() for u in (active_usernames or [])}
    cleared = []
    for record in document.get("records", []):
        assigned = (record.get("assignedTo") or "").strip()
        if assigned and assigned.lower() not in valid:
            record["assignedTo"] = ""
            cleared.append(record.get("id"))
    return cleared


def _merged_log(base, incoming, username="", role=SUPERADMIN):
    """Keep stored log entries, prepending any new ones from the client.

    A restricted client may have been given a trimmed log (or none), so its
    payload must never be treated as the whole history -- only as a source of
    entries to ADD.

    Every added entry is re-stamped: the timestamp comes from the server's
    clock and the author from the session. Otherwise a client could backdate an
    entry, or attribute its own action to someone else, and the log would be
    worthless as a record of who did what. The financial flag is likewise
    recomputed rather than trusted -- a client that may not see financial data
    cannot mint an entry claiming to be one, and a trademark admin cannot strip
    the flag off an entry to make a fee change visible to itself later.
    """
    stored_log = base.get("log", []) or []
    incoming_log = incoming.get("log", []) or []
    known = {(e.get("ts"), e.get("summary")) for e in stored_log if isinstance(e, dict)}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    can_write_financial = can(role, "edit_financials")
    fresh = []
    seen_this_batch = set()
    for entry in incoming_log:
        if not isinstance(entry, dict):
            continue
        summary = entry.get("summary")
        # (ts, summary) catches a client re-sending an entry it already has
        # stamped from a prior save (a retry, or the log it mirrored back). A
        # summary seen only elsewhere in the whole stored history is NOT treated
        # as a duplicate -- the same transition can legitimately happen twice
        # for a matter, and text-matching against all of history would silently
        # drop the second, real event.
        if (entry.get("ts"), summary) in known or summary in seen_this_batch:
            continue
        seen_this_batch.add(summary)
        fresh.append({
            "ts": now,
            "summary": summary,
            "by": username,
            "financial": bool(entry.get("financial")) and can_write_financial,
        })
        if len(fresh) >= MAX_NEW_LOG_ENTRIES:
            break

    return (fresh + stored_log)[:500]
