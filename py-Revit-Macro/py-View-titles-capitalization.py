# py-View-titles-capitalization.py
# Encoding ??utc-8??
# Dynamo CPython3

# Revit: set "Title on Sheet" casing for all non-template views.
# IN[0] = case mode (default 3):
#         3 = ALL CAPS
#         2 = Title Case
#         1 = Sentence case
#         0 = all small
# IN[1] = bypass patterns CSV or list, e.g. "AE-*,AS-*"
#         NOTE: if a pattern has NO '*' wildcard (e.g. "AE,SF"), it matches ABSOLUTE only (not "AEfoobar").

import clr
import re

clr.AddReference("RevitAPI")
import Autodesk.Revit.DB as DB

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument

# ----------------------------
# Inputs
# ----------------------------
mode = IN[0] if (len(IN) > 0 and IN[0] is not None and str(IN[0]).strip() != "") else 3
bypass_in = IN[1] if (len(IN) > 1 and IN[1] is not None) else ""

# Normalize bypass patterns to a list of strings
if isinstance(bypass_in, list):
    bypass_csv = ",".join([str(x) for x in bypass_in if x is not None])
else:
    bypass_csv = str(bypass_in)

raw_patterns = [p.strip() for p in bypass_csv.split(",") if p and p.strip()]

# Compile bypass patterns:
# - If contains '*': wildcard match against entire string (^...$) with '*' => '.*'
# - Else: exact match only (^...$)
bypass_regexes = []
for p in raw_patterns:
    if "*" in p:
        rx = "^" + re.escape(p).replace("\\*", ".*") + "$"
    else:
        rx = "^" + re.escape(p) + "$"
    bypass_regexes.append(re.compile(rx, re.IGNORECASE))

def is_bypassed(s):
    if s is None:
        s = ""
    for rx in bypass_regexes:
        if rx.match(s):
            return True
    return False

def apply_case(s, case_mode):
    if s is None:
        s = ""
    s = s.strip()
    if s == "":
        return s

    if int(case_mode) == 3:
        return s.upper()
    elif int(case_mode) == 2:
        # Python title-cases tokens separated by non-letters reasonably well
        return s.lower().title()
    elif int(case_mode) == 1:
        # sentence case: first non-space char upper, rest lower
        lower = s.lower()
        return lower[:1].upper() + lower[1:] if lower else lower
    else:
        return s.lower()

# ----------------------------
# Process all non-template views
# ----------------------------
views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()

updated = []
skipped = []
failed = []

TransactionManager.Instance.EnsureInTransaction(doc)

for v in views:
    try:
        if v.IsTemplate:
            continue

        p_title = v.LookupParameter("Title on Sheet")
        if p_title is None or p_title.IsReadOnly:
            # Nothing we can safely set
            continue

        current_title = (p_title.AsString() or "").strip()
        base_text = current_title if current_title != "" else (v.Name or "")

        # Bypass check uses the effective text (title if present, else view name)
        if is_bypassed(base_text):
            skipped.append(v.Name)
            continue

        new_title = apply_case(base_text, mode)

        # Only write if change
        if (current_title != new_title):
            p_title.Set(new_title)
            updated.append({"ViewName": v.Name, "OldTitle": current_title, "NewTitle": new_title})

    except Exception as ex:
        failed.append({"ViewName": getattr(v, "Name", "<unknown>"), "Error": str(ex)})

TransactionManager.Instance.TransactionTaskDone()

OUT = {
    "ModeUsed": int(mode),
    "BypassPatterns": raw_patterns,
    "UpdatedCount": len(updated),
    "SkippedCount": len(skipped),
    "FailedCount": len(failed),
    "Updated": updated,
    "Skipped": skipped,
    "Failed": failed
}
