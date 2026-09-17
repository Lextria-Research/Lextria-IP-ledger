"""Checks on index.html that catch drift between the page and the server.

The front end is a single hand-edited file with no build step, so nothing else
would notice if one of these lists stopped matching the server's.
"""

import pathlib
import re

from backend import roles

INDEX = pathlib.Path(__file__).resolve().parent.parent / "index.html"


def index_html():
    return INDEX.read_text(encoding="utf-8")


def js_array(name, source):
    """The string entries of a `var NAME = [...]` array literal."""
    m = re.search(r"var\s+" + re.escape(name) + r"\s*=\s*\[(.*?)\]", source, re.S)
    assert m, "%s not found in index.html" % name
    return re.findall(r"'([^']*)'", m.group(1))


def test_financial_field_lists_match():
    """The page must hide exactly what the server strips.

    A field listed here but not there would be rendered for a role the server
    never sends it to (harmless, but it would look broken); a field there but
    not here would be stripped by the server while the form still offered to
    edit it, and the edit would silently vanish on save.
    """
    assert js_array("FINANCIAL_FIELDS", index_html()) == list(roles.FINANCIAL_FIELDS)


def test_drafter_editable_field_lists_match():
    """The form disables everything outside this list; the server ignores
    everything outside its own. If they disagree, a drafter is either offered a
    field whose edit is silently dropped, or denied one they are allowed."""
    assert (js_array("DRAFTER_EDITABLE_FIELDS", index_html())
            == list(roles.DRAFTER_EDITABLE_FIELDS))


def test_ip_types_match():
    source = index_html()
    m = re.search(r"\[\s*'trademark',\s*'copyright',\s*'design'\s*\]", source)
    assert m, "the IP type subtab list has changed shape"
    assert set(roles.IP_TYPES) == {"trademark", "copyright", "design"}


def test_the_page_has_exactly_one_executable_script_tag():
    """The CSP nonce is stamped into one tag by name. A second inline <script>
    would silently fail to run under script-src 'self' 'nonce-...'.

    Real tags start a line; the other occurrence in this file is inside a JS
    string, where the "export a standalone copy" feature writes the same tag
    into the file it generates.
    """
    source = index_html()
    tags = re.findall(r"^<script(?![^>]*type=\"application/json\")[^>]*>",
                      source, re.M)
    assert tags == ['<script id="app-script">'], tags


def test_the_real_script_tag_precedes_the_exported_one():
    """backend/main.py replaces the FIRST occurrence of the tag to insert the
    nonce. If the string literal used by the export feature ever moved above the
    real tag, the nonce would be stamped into exported HTML instead of the page,
    and the live app would stop running with no error anywhere."""
    source = index_html()
    real = source.index('\n<script id="app-script">')
    literal = source.index("'<script id=\"app-script\">'")
    assert real < literal


def test_no_shared_api_key_remains():
    """The old single shared key could not express per-role access; nothing
    should still reach for it."""
    source = index_html()
    for gone in ("LEXTRIA_API_KEY", "X-Lextria-Key", "sessionApiKey", "backendKeyPrompt"):
        assert gone not in source, "%s still referenced in index.html" % gone
