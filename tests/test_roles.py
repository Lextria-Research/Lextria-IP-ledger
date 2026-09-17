"""What each role may see and change.

The headline rule under test: a trademark admin never receives financial data,
for trademark, copyright or design matters alike -- not in the record, not in
the audit log, and not by writing one back.
"""

import copy

import pytest

from backend import db, roles
from conftest import sign_in

FINANCIALS = {
    "officialFee": 9000,
    "professionalFee": 25000,
    "amountPaid": 9000,
    "paymentStatus": "part-paid",
    "invoiceRef": "INV-2026-0042",
    "currency": "INR",
    "feeNotes": "Balance due on registration",
}


def ledger():
    """One matter of each IP type, all carrying financials."""
    return {
        "clients": [
            {"id": "c-1", "name": "Nova Foods"},
            {"id": "c-2", "name": "Harbour Press"},
        ],
        "records": [
            dict({"id": "t-001", "clientId": "c-1", "ipType": "trademark",
                  "brand": "NOVA", "cls": "30", "appno": "1234567",
                  "status": "objected", "assignedTo": "dee", "timeline": []},
                 **FINANCIALS),
            dict({"id": "t-002", "clientId": "c-2", "ipType": "copyright",
                  "brand": "The Long Quiet", "cls": "Literary work",
                  "appno": "CR-9981", "status": "cr_examination",
                  "assignedTo": "", "timeline": []},
                 **FINANCIALS),
            dict({"id": "t-003", "clientId": "c-1", "ipType": "design",
                  "brand": "Bottle silhouette", "cls": "09-01",
                  "appno": "ID-5522", "status": "id_filed",
                  "assignedTo": "", "timeline": []},
                 **FINANCIALS),
        ],
        "log": [
            {"ts": "2026-01-01T00:00:00+00:00", "summary": "Created NOVA",
             "by": "boss", "financial": False},
            {"ts": "2026-01-02T00:00:00+00:00",
             "summary": "Set professional fee to 25,000 for NOVA",
             "by": "boss", "financial": True},
        ],
        "nextClientSeq": 3,
        "nextRecordSeq": 4,
    }


# --- Reading -----------------------------------------------------------------

@pytest.mark.parametrize("ip_type,record_id",
                         [("trademark", "t-001"),
                          ("copyright", "t-002"),
                          ("design", "t-003")])
def test_trademark_admin_never_receives_financials(ip_type, record_id):
    """Every IP type, not just trademarks."""
    doc = roles.redact_for_role(ledger(), roles.TRADEMARK_ADMIN, "tma")
    record = next(r for r in doc["records"] if r["id"] == record_id)
    assert record["ipType"] == ip_type
    for field in roles.FINANCIAL_FIELDS:
        assert field not in record, "%s leaked on a %s matter" % (field, ip_type)
    # The non-financial substance is still all there.
    assert record["brand"]
    assert record["status"]


def test_trademark_admin_sees_every_matter_type():
    """Scoping is by field, not by IP type: a trademark admin administers
    copyright and design matters too."""
    doc = roles.redact_for_role(ledger(), roles.TRADEMARK_ADMIN, "tma")
    assert {r["ipType"] for r in doc["records"]} == set(roles.IP_TYPES)
    assert len(doc["clients"]) == 2


def test_superadmin_receives_financials_intact():
    doc = roles.redact_for_role(ledger(), roles.SUPERADMIN, "boss")
    for record in doc["records"]:
        for field, value in FINANCIALS.items():
            assert record[field] == value


def test_financial_log_entries_are_withheld():
    """A fee change described in the log would hand back the number that was
    just stripped from the record."""
    doc = roles.redact_for_role(ledger(), roles.TRADEMARK_ADMIN, "tma")
    summaries = [e["summary"] for e in doc["log"]]
    assert "Created NOVA" in summaries
    assert not any("25,000" in s for s in summaries)

    full = roles.redact_for_role(ledger(), roles.SUPERADMIN, "boss")
    assert any("25,000" in e["summary"] for e in full["log"])


def test_drafter_sees_only_assigned_matters():
    doc = roles.redact_for_role(ledger(), roles.DRAFTER, "dee")
    assert [r["id"] for r in doc["records"]] == ["t-001"]
    for field in roles.FINANCIAL_FIELDS:
        assert field not in doc["records"][0]


def test_drafter_client_list_is_narrowed_to_their_own_matters():
    """Shipping the whole client roster would disclose who the firm acts for."""
    doc = roles.redact_for_role(ledger(), roles.DRAFTER, "dee")
    assert [c["id"] for c in doc["clients"]] == ["c-1"]


def test_drafter_log_is_only_their_own_entries():
    doc = roles.redact_for_role(ledger(), roles.DRAFTER, "dee")
    assert doc["log"] == []


# --- Writing -----------------------------------------------------------------

def as_loaded_and_edited(role, username):
    """(stored, baseline, incoming) for a save by `role`.

    baseline is what that role was last served; incoming starts as a copy of it,
    for the test to then edit. They must be separate objects -- the merge
    compares them to tell a deliberate edit from an untouched record, so passing
    one object as both makes every change look like no change at all.
    """
    stored = ledger()
    baseline = roles.redact_for_role(stored, role, username)
    return stored, baseline, copy.deepcopy(baseline)


def test_trademark_admin_cannot_write_financials_back():
    """A payload that invents fee values must not overwrite the stored ones."""
    stored, baseline, incoming = as_loaded_and_edited(roles.TRADEMARK_ADMIN, "tma")
    incoming["records"][0]["professionalFee"] = 1
    incoming["records"][0]["invoiceRef"] = "INV-FORGED"
    incoming["records"][0]["brand"] = "NOVA RENAMED"

    merged, _ = roles.merge_for_role(stored, incoming, roles.TRADEMARK_ADMIN, "tma",
                                     baseline=baseline)
    record = next(r for r in merged["records"] if r["id"] == "t-001")
    assert record["professionalFee"] == 25000
    assert record["invoiceRef"] == "INV-2026-0042"
    # The edit it WAS entitled to make still lands.
    assert record["brand"] == "NOVA RENAMED"


def test_trademark_admin_save_cannot_blank_financials_by_omission():
    """The payload legitimately has no fee keys at all -- that is not a delete.

    The unrelated edit matters: it forces the merge down the "apply this change"
    path, which is where an omitted field could plausibly be dropped.
    """
    stored, baseline, incoming = as_loaded_and_edited(roles.TRADEMARK_ADMIN, "tma")
    incoming["records"][0]["status"] = "response_filed"
    merged, _ = roles.merge_for_role(stored, incoming, roles.TRADEMARK_ADMIN, "tma",
                                     baseline=baseline)
    for record in merged["records"]:
        assert record["professionalFee"] == 25000


def test_trademark_admin_cannot_forge_a_financial_log_entry():
    """The flag is recomputed from the role, not trusted from the payload."""
    stored, baseline, incoming = as_loaded_and_edited(roles.TRADEMARK_ADMIN, "tma")
    incoming["log"] = [{"ts": None, "summary": "Fee note", "financial": True}]
    merged, _ = roles.merge_for_role(stored, incoming, roles.TRADEMARK_ADMIN, "tma",
                                     baseline=baseline)
    fresh = merged["log"][0]
    assert fresh["summary"] == "Fee note"
    assert fresh["financial"] is False
    assert fresh["by"] == "tma"


def test_new_matter_from_trademark_admin_has_no_financials():
    stored, baseline, incoming = as_loaded_and_edited(roles.TRADEMARK_ADMIN, "tma")
    incoming["records"].append({
        "id": "t-004", "clientId": "c-1", "ipType": "copyright",
        "brand": "New work", "status": "cr_filed",
        "professionalFee": 999, "invoiceRef": "INV-SNEAK",
    })
    merged, _ = roles.merge_for_role(stored, incoming, roles.TRADEMARK_ADMIN, "tma",
                                     baseline=baseline)
    created = next(r for r in merged["records"] if r["brand"] == "New work")
    for field in roles.FINANCIAL_FIELDS:
        assert field not in created


def test_drafter_may_only_change_permitted_fields():
    stored = ledger()
    incoming = roles.redact_for_role(stored, roles.DRAFTER, "dee")
    incoming["records"][0]["status"] = "response_filed"
    incoming["records"][0]["brand"] = "HIJACKED"
    incoming["records"][0]["assignedTo"] = "someone-else"

    merged, _ = roles.merge_for_role(stored, incoming, roles.DRAFTER, "dee")
    record = next(r for r in merged["records"] if r["id"] == "t-001")
    assert record["status"] == "response_filed"   # permitted
    assert record["brand"] == "NOVA"              # not permitted
    assert record["assignedTo"] == "dee"          # cannot reassign away


def test_drafter_save_does_not_delete_the_matters_they_cannot_see():
    """A filtered read written back literally would empty the firm's ledger."""
    stored = ledger()
    incoming = roles.redact_for_role(stored, roles.DRAFTER, "dee")
    assert len(incoming["records"]) == 1
    merged, _ = roles.merge_for_role(stored, incoming, roles.DRAFTER, "dee")
    assert len(merged["records"]) == 3


def test_drafter_status_change_is_recorded_on_the_timeline_by_the_server():
    stored = ledger()
    incoming = roles.redact_for_role(stored, roles.DRAFTER, "dee")
    incoming["records"][0]["status"] = "response_filed"
    merged, _ = roles.merge_for_role(stored, incoming, roles.DRAFTER, "dee")
    entry = next(r for r in merged["records"] if r["id"] == "t-001")["timeline"][0]
    assert entry["fromStatus"] == "objected"
    assert entry["toStatus"] == "response_filed"
    assert entry["by"] == "dee"
    assert entry["serverGenerated"] is True


def test_drafter_cannot_forge_timeline_history():
    """Backdating a filing is the most damaging thing a restricted account
    could do to a legal ledger."""
    stored = ledger()
    incoming = roles.redact_for_role(stored, roles.DRAFTER, "dee")
    incoming["records"][0]["timeline"] = [
        {"id": "forged", "fromStatus": "filed", "toStatus": "registered",
         "effectiveDate": "2020-01-01", "by": "dee"}]
    merged, _ = roles.merge_for_role(stored, incoming, roles.DRAFTER, "dee")
    timeline = next(r for r in merged["records"] if r["id"] == "t-001")["timeline"]
    assert all(e.get("id") != "forged" for e in timeline)


def test_unknown_ip_type_is_filed_under_the_default_rather_than_dropped():
    stored, baseline, incoming = as_loaded_and_edited(roles.SUPERADMIN, "boss")
    incoming["records"].append({"id": "t-009", "clientId": "c-1",
                                "ipType": "patent", "brand": "Widget"})
    merged, _ = roles.merge_for_role(stored, incoming, roles.SUPERADMIN, "boss",
                                     baseline=baseline)
    created = next(r for r in merged["records"] if r["id"] == "t-009")
    assert created["ipType"] == roles.DEFAULT_IP_TYPE


# --- Capabilities ------------------------------------------------------------

def test_capability_matrix():
    assert roles.can(roles.SUPERADMIN, "view_financials")
    assert not roles.can(roles.TRADEMARK_ADMIN, "view_financials")
    assert not roles.can(roles.DRAFTER, "view_financials")

    assert not roles.can(roles.TRADEMARK_ADMIN, "manage_users")
    assert not roles.can(roles.TRADEMARK_ADMIN, "bulk_manage")
    assert roles.can(roles.TRADEMARK_ADMIN, "create_matter")
    assert roles.can(roles.TRADEMARK_ADMIN, "export")

    assert roles.can(roles.DRAFTER, "change_status")
    for denied in ("create_matter", "edit_matter", "delete_matter", "export",
                   "import", "manage_clients", "assign_matter"):
        assert not roles.can(roles.DRAFTER, denied)


def test_validate_assignments_clears_names_that_are_not_active_accounts():
    doc = ledger()
    doc["records"][1]["assignedTo"] = "ghost"
    cleared = roles.validate_assignments(doc, ["dee", "tma", "boss"])
    assert cleared == ["t-002"]
    assert doc["records"][1]["assignedTo"] == ""
    assert doc["records"][0]["assignedTo"] == "dee"


# --- End to end through the API ---------------------------------------------

def test_financials_never_cross_the_wire_to_a_trademark_admin(env, accounts):
    """The whole point, exercised through the real endpoints."""
    sign_in(env, *accounts[roles.SUPERADMIN])
    assert env.put("/api/state", json=ledger()).status_code == 200
    env.post("/api/logout")

    sign_in(env, *accounts[roles.TRADEMARK_ADMIN])
    body = env.get("/api/state")
    assert body.status_code == 200
    raw = body.text
    # Not "is the key absent from the parsed record" -- is the VALUE anywhere in
    # the bytes the browser received at all.
    assert "INV-2026-0042" not in raw
    assert "25000" not in raw
    assert "feeNotes" not in raw
    # ...while the matters themselves arrived.
    assert "NOVA" in raw
    assert "The Long Quiet" in raw
