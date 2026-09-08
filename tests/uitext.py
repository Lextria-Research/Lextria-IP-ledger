"""Matching against text as a browser renders it.

Three times now a UI assertion has failed on styling rather than substance, so
the normalisation lives in one place instead of being re-improvised per test.

Two things make a naive `"Locarno Class" in page.inner_text("body")` unreliable:

1. **CSS text-transform.** `inner_text` returns text *as rendered*, and the
   stylesheet upper-cases table headers, stat labels and form labels
   (app.css: `thead th`, `.stat-label`, `.field label`). "Locarno Class" comes
   back as "LOCARNO CLASS".

2. **Line wrapping.** A narrow table cell wraps, and `inner_text` preserves the
   break as a newline. "Acme Innovations Ltd" in a client column comes back as
   "Acme\\nInnovations\\nLtd", so the substring is simply not there.

`normalise` folds both away: collapse every run of whitespace to one space, then
upper-case. Assertions then test what the page says, not how it is styled or how
wide the column happened to be.
"""

# Injected into a page so browser-side checks normalise identically to the
# Python ones. Defines window.__has(needle) -> bool.
BROWSER_HELPER = """
window.__norm = function (s) {
  return String(s == null ? '' : s).replace(/\\s+/g, ' ').trim().toUpperCase();
};
window.__has = function (needle) {
  return window.__norm(document.body.innerText).indexOf(window.__norm(needle)) !== -1;
};
window.__text = function () { return document.body.innerText; };
"""


def normalise(text):
    """Collapse whitespace runs to single spaces and upper-case."""
    return " ".join(str(text or "").split()).upper()


def contains(haystack, needle):
    """Whether `needle` appears in `haystack`, ignoring case and wrapping."""
    return normalise(needle) in normalise(haystack)


def missing(haystack, needle):
    return not contains(haystack, needle)
