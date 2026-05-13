# Py-Arrows.py
# V01-01
# Dynamo Python node for Revit 2025 Arrowhead type standardization.
#
# PURPOSE
# - Find all Revit Arrowhead types.
# - Standardize names using size + kind + optional "Open".
# - Preview changes, rename keepers, merge duplicates, and optionally delete duplicates.
# - Audit Arrow Style values so unknown styles are reported.
# - Optionally snap arrow sizes to a preferred allowable-size list.
#
# INPUTS
# IN[0] = commit_changes (bool, default=False)
# IN[1] = delete_merged_duplicates (bool, default=False)
# IN[2] = case_mode (int, default=2)
#         0 = all lower
#         1 = Sentence
#         2 = Title
#         3 = UPPER
# IN[3] = preferred_sizes_text (str, optional, default="")
#         Comma-separated inch sizes, examples:
#         1/32", 3/32", 1/8", 3/16"
#         1/32,3/32,1/8,3/16
#         0.125, 0.1875
#
# OUTPUT
# OUT = {
#   "summary": str,
#   "text": str,
#   "preview_text": str,
#   "preview_lines": [str],
#   "preview_data": [[...], ...],
#   "renamed_data": [[...], ...],
#   "merged_data": [[...], ...],
#   "failed_data": [[...], ...],
#   "skipped_data": [[...], ...],
#   "style_inventory": [[style_id, count], ...],
#   "unknown_style_data": [[id, old_name, style_id, reason], ...],
#   "preferred_sizes_input": str,
#   "preferred_sizes_inches": [float, ...],
#   "preferred_sizes_text": [str, ...]
# }

import clr  # Revit / .NET interop
import re  # Text parsing

# Revit API assembly
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ElementType,
    BuiltInParameter,
    StorageType,
    ElementId
)

# Dynamo Revit services
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# Active Revit document
doc = DocumentManager.Instance.CurrentDBDocument

# User inputs
commit_changes = bool(IN[0]) if len(IN) > 0 and IN[0] is not None else False  # Commit switch
delete_merged_duplicates = bool(IN[1]) if len(IN) > 1 and IN[1] is not None else False  # Delete merged duplicates switch
case_mode = int(IN[2]) if len(IN) > 2 and IN[2] is not None else 2  # 0=lower, 1=Sentence, 2=Title, 3=UPPER
preferred_sizes_input = IN[3] if len(IN) > 3 and IN[3] is not None else ""  # Optional comma-separated preferred sizes


# Safely convert any value to string
def safe_str(value):
    if value is None:  # Null-safe handling
        return ""
    try:  # Standard string conversion
        return str(value)
    except:  # Fallback conversion
        try:
            return repr(value)
        except:
            return ""


# Normalize text for case-insensitive comparisons
def normalize_compare_text(value):
    return safe_str(value).strip().lower()


# Lowercase split helper for title-casing
def lower_value_split(text):
    return safe_str(text).strip().lower().split()


# Apply requested output casing
def apply_case_style(text, mode):
    value = safe_str(text).strip()  # Normalize incoming text
    if not value:  # Preserve blanks
        return ""

    if mode == 0:  # all lower
        return value.lower()
    elif mode == 1:  # Sentence
        lower_value = value.lower()
        return lower_value[:1].upper() + lower_value[1:] if lower_value else lower_value
    elif mode == 2:  # Title
        words = lower_value_split(value)
        return " ".join([(w[:1].upper() + w[1:]) if w else "" for w in words])
    elif mode == 3:  # UPPER
        return value.upper()

    return value  # Fallback if mode is invalid


# Read family name from an element type
def get_family_name(e):
    try:  # Direct property first
        value = safe_str(e.FamilyName).strip()
        if value:
            return value
    except:
        pass

    try:  # Fallback to built-in parameter
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
        if p:
            value = safe_str(p.AsString()).strip()
            if value:
                return value
    except:
        pass

    return ""  # Final fallback


# Get best available type-name parameter
def get_type_name_param(e):
    builtins = [
        BuiltInParameter.SYMBOL_NAME_PARAM,
        BuiltInParameter.ALL_MODEL_TYPE_NAME
    ]

    for bip in builtins:  # Try preferred built-ins in order
        try:
            p = e.get_Parameter(bip)
            if p:
                return p
        except:
            pass

    return None  # None if nothing found


# Get visible type name
def get_type_name(e):
    p = get_type_name_param(e)
    if p:  # Preferred parameter path
        try:
            value = p.AsString()
            if value and value.strip():
                return value.strip()
        except:
            pass

    try:  # Fallback to .Name
        value = safe_str(e.Name).strip()
        if value:
            return value
    except:
        pass

    return "<Unnamed>"  # Final fallback


# Set visible type name
def set_type_name(e, new_name):
    p = get_type_name_param(e)
    if p and not p.IsReadOnly:  # Use writable parameter when possible
        p.Set(new_name)
        return True

    try:  # Fallback to direct property assignment
        e.Name = new_name
        return True
    except:
        return False


# Get parameter by name, case-insensitive
def get_param_by_name(e, param_name):
    target = normalize_compare_text(param_name)

    for p in e.Parameters:  # Scan all parameters
        try:
            if p.Definition and normalize_compare_text(p.Definition.Name) == target:
                return p
        except:
            pass

    return None


# Read integer parameter safely
def get_int_param(e, param_name, default_value=0):
    p = get_param_by_name(e, param_name)
    if p and p.StorageType == StorageType.Integer:  # Ensure correct storage type
        try:
            return p.AsInteger()
        except:
            pass
    return default_value


# Read double parameter safely
def get_double_param(e, param_name, default_value=None):
    p = get_param_by_name(e, param_name)
    if p and p.StorageType == StorageType.Double:  # Ensure correct storage type
        try:
            return p.AsDouble()
        except:
            pass
    return default_value


# Convert Revit internal feet to inches
def feet_to_inches(feet_value):
    return feet_value * 12.0


# Greatest common divisor for fraction reduction
def gcd_int(a, b):
    a = abs(int(a))
    b = abs(int(b))
    while b:  # Euclidean algorithm
        a, b = b, a % b
    return a if a else 1


# Round inch value to nearest 1/32, minimum 1
def round_to_32nds(inches_value):
    n32 = int(round(inches_value * 32.0))
    return max(1, n32)


# Format reduced inch fraction text
def inches_text_from_32nds(n32):
    g = gcd_int(n32, 32)
    n = n32 // g
    d = 32 // g
    if d == 1:  # Whole inch output
        return '%d"' % n
    return '%d/%d"' % (n, d)


# Format numeric prefix like 01. 02. 03.
def prefix_text_from_32nds(n32):
    return "%02d." % n32


# Parse a single preferred-size token into inches
def parse_size_token_to_inches(token):
    raw = safe_str(token).strip()  # Preserve original for diagnostics
    if not raw:  # Ignore empty tokens
        return None

    value = raw.lower().strip()  # Case-insensitive parsing
    value = value.replace("inches", "")
    value = value.replace("inch", "")
    value = value.replace("in.", "")
    value = value.replace("in", "")
    value = value.replace('"', "")
    value = value.replace(" ", "").strip()

    if not value:  # Ignore blank after cleanup
        return None

    if re.match(r'^\d+/\d+$', value):  # Fraction like 3/32
        parts = value.split("/")
        num = float(parts[0])
        den = float(parts[1])
        if den == 0:
            return None
        return num / den

    if re.match(r'^\d+\.\d+$', value):  # Decimal inches like 0.125
        return float(value)

    if re.match(r'^\d+$', value):  # Whole inches like 1 or 2
        return float(value)

    return None  # Unsupported token format


# Parse comma-separated preferred sizes into sorted unique inches
def parse_preferred_sizes(text):
    parsed = []
    source_text = safe_str(text)

    if not source_text.strip():  # No preferred sizes provided
        return parsed

    tokens = source_text.split(",")  # Comma-separated list
    for token in tokens:  # Parse each token independently
        inches_value = parse_size_token_to_inches(token)
        if inches_value is None:
            continue
        if inches_value <= 0:
            continue
        parsed.append(inches_value)

    unique_sorted = []
    seen_keys = set()

    for value in sorted(parsed):  # Deduplicate with tolerance
        key = round(value, 8)
        if key not in seen_keys:
            seen_keys.add(key)
            unique_sorted.append(value)

    return unique_sorted


# Snap a size to the nearest preferred size or nearest 1/32
def get_target_size_32nds(size_inches, preferred_sizes_inches):
    if preferred_sizes_inches:  # Snap to nearest preferred size when list exists
        nearest_inches = min(
            preferred_sizes_inches,
            key=lambda x: (abs(x - size_inches), x)
        )
        return round_to_32nds(nearest_inches)

    return round_to_32nds(size_inches)  # Default 1/32 rounding


# Increment inventory count for an Arrow Style value
def style_count_add(style_counts, style_value):
    if style_value not in style_counts:  # Initialize bucket on first sighting
        style_counts[style_value] = 0
    style_counts[style_value] += 1


# Canonical kind mapping from known style ids
def get_canonical_kind_from_style(style, centered):
    if style == 0:  # Known style mapping
        return "Diagonal"
    if style == 3:  # Known style mapping
        return "Dot"
    if style == 7:  # Known style mapping
        return "Tick Heavy"
    if style == 8:  # Known style mapping
        return "Arrow"
    if style == 9:  # Known style mapping
        return "Arrow"
    if style == 10:  # Known style mapping
        return "Box"
    if style == 11:  # Known style mapping
        return "Target"

    return None  # Unknown style id


# Fallback kind mapping from name tokens, case-insensitive
def get_canonical_kind_from_name(current_name, centered):
    name_upper = safe_str(current_name).upper()

    if "TICK" in name_upper and centered == 1:  # TICK + centered indicates Tick Heavy
        return "Tick Heavy"
    if "DOT" in name_upper:  # Name token fallback
        return "Dot"
    if "BOX" in name_upper:  # Name token fallback
        return "Box"
    if "TARGET" in name_upper or "ELEVATION TARGET" in name_upper:  # Name token fallback
        return "Target"
    if "DATUM" in name_upper:  # Name token fallback
        return "Datum"
    if "LOOP" in name_upper:  # Name token fallback
        return "Loop"
    if "DIAGONAL" in name_upper:  # Name token fallback
        return "Diagonal"
    if "TICK" in name_upper:  # Name token fallback
        return "Tick Heavy"
    if "ARROW" in name_upper or "TRIANGLE" in name_upper:  # Name token fallback
        return "Arrow"

    return None  # Unknown by name as well


# Build output label for a canonical kind using requested case mode
def format_kind_label(canonical_kind, mode):
    return apply_case_style(canonical_kind, mode)


# Decide canonical kind using style first, then name fallback
def classify_arrowhead(e, current_name):
    style = get_int_param(e, "Arrow Style", -1)  # Style id
    centered = get_int_param(e, "Tick Mark Centered", 0)  # Tick centering flag

    kind = get_canonical_kind_from_style(style, centered)
    if kind:  # Prefer style-based mapping
        return kind, style, "style"

    kind = get_canonical_kind_from_name(current_name, centered)
    if kind:  # Fallback to name-based mapping
        return kind, style, "name"

    return None, style, "unknown"  # Explicit unknown result


# Determine whether the symbol should include "Open"
def is_open_symbol(e, canonical_kind):
    arrow_closed = get_int_param(e, "Arrow Closed", 0)  # Closed/open arrow state
    fill_tick = get_int_param(e, "Fill Tick", 0)  # Fill state

    if canonical_kind in ["Arrow", "Dot", "Box", "Target", "Datum", "Loop"]:  # Filled-style symbol families
        return arrow_closed == 0 and fill_tick == 0

    return False  # Diagonal / Tick Heavy do not get Open label


# Build the target rename info for a single arrowhead type
def build_target_info(e, preferred_sizes_inches):
    current_name = get_type_name(e)  # Existing type name

    tick_size_ft = get_double_param(e, "Tick Size", None)  # Revit internal feet
    if tick_size_ft is None or tick_size_ft <= 0:  # Require usable size
        return None, "Missing Tick Size"

    size_inches_raw = feet_to_inches(tick_size_ft)  # Convert to inches
    n32 = get_target_size_32nds(size_inches_raw, preferred_sizes_inches)  # Snap to preferred sizes or 1/32
    size_text = inches_text_from_32nds(n32)  # Build displayed fraction

    canonical_kind, style_id, classify_source = classify_arrowhead(e, current_name)
    if not canonical_kind:  # Reject unclassified types
        return None, "Could not classify Arrow Style"

    kind_label = format_kind_label(canonical_kind, case_mode)  # Apply output case
    open_label = format_kind_label("Open", case_mode)  # Apply output case
    open_text = (" " + open_label) if is_open_symbol(e, canonical_kind) else ""  # Optional Open suffix

    target_name = "%s %s%s %s" % (
        prefix_text_from_32nds(n32),
        kind_label,
        open_text,
        size_text
    )

    return {
        "id": e.Id.IntegerValue,
        "element": e,
        "old_name": current_name,
        "new_name": target_name,
        "canonical_kind": canonical_kind,
        "kind": kind_label,
        "size_text": size_text,
        "size_32nds": n32,
        "tick_size_ft": tick_size_ft,
        "size_inches_raw": size_inches_raw,
        "arrow_style": style_id,
        "arrow_closed": get_int_param(e, "Arrow Closed", 0),
        "fill_tick": get_int_param(e, "Fill Tick", 0),
        "tick_mark_centered": get_int_param(e, "Tick Mark Centered", 0),
        "classify_source": classify_source
    }, None


# Collect all arrowhead ElementType objects
def get_arrowhead_types(document):
    result = []
    collector = FilteredElementCollector(document).OfClass(ElementType).ToElements()

    for e in collector:  # Scan all element types
        if normalize_compare_text(get_family_name(e)) == "arrowhead":  # Family match is case-insensitive
            result.append(e)

    return result


# Collect all instances and all types for reference scanning
def all_elements_and_types(document):
    model_elems = list(FilteredElementCollector(document).WhereElementIsNotElementType().ToElements())  # All instances
    type_elems = list(FilteredElementCollector(document).WhereElementIsElementType().ToElements())  # All types
    return model_elems + type_elems


# Repoint any references from one type id to another
def repoint_type_references(document, old_id, new_id):
    touched = 0  # Count elements that changed

    for e in all_elements_and_types(document):  # Scan full document
        changed = False  # Track whether current element changed

        try:  # Attempt direct type replacement first
            type_id = e.GetTypeId()
            if type_id and type_id != ElementId.InvalidElementId and type_id.IntegerValue == old_id.IntegerValue:
                try:
                    e.ChangeTypeId(new_id)
                    changed = True
                except:
                    pass
        except:
            pass

        try:  # Attempt parameter-based ElementId replacement
            for p in e.Parameters:
                try:
                    if p.IsReadOnly:  # Skip read-only params
                        continue
                    if p.StorageType != StorageType.ElementId:  # Only ElementId params matter
                        continue
                    eid = p.AsElementId()
                    if eid and eid != ElementId.InvalidElementId and eid.IntegerValue == old_id.IntegerValue:
                        p.Set(new_id)
                        changed = True
                except:
                    pass
        except:
            pass

        if changed:  # Increment touched count once per changed element
            touched += 1

    return touched


# Format a preview row as readable multiline text
def row_to_block(row):
    return (
        "ID: {0}\n"
        "\tAction: {1}\n"
        "\tFrom: {2}\n"
        "\tTo:   {3}\n"
        "\tKind: {4}\n"
        "\tSize: {5}\n"
        "\tStyle:{6}"
    ).format(
        row[0], row[1], row[2], row[3], row[4], row[5], row[6]
    )


# Parse preferred sizes once up front
preferred_sizes_inches = parse_preferred_sizes(preferred_sizes_input)  # Parsed allowable sizes
preferred_sizes_text = [inches_text_from_32nds(round_to_32nds(x)) for x in preferred_sizes_inches]  # Display text list

# Main data collection
arrowheads = get_arrowhead_types(doc)  # All arrowhead types in project

# Working collections
groups = {}  # Group target names to candidate types
preview_data = []  # Preview rows
skipped_data = []  # Skipped items
renamed_data = []  # Rename results
merged_data = []  # Merge results
failed_data = []  # Failures
unknown_style_data = []  # Explicit unknown style cases
style_counts = {}  # Style inventory

# Analyze each arrowhead type
for e in arrowheads:
    current_style = get_int_param(e, "Arrow Style", -1)  # Read style for audit
    style_count_add(style_counts, current_style)  # Count every style encountered

    info, err = build_target_info(e, preferred_sizes_inches)  # Build rename target
    if err:  # Record skipped / unknown items
        skipped_data.append([e.Id.IntegerValue, get_type_name(e), err])
        if err == "Could not classify Arrow Style":
            unknown_style_data.append([e.Id.IntegerValue, get_type_name(e), current_style, err])
        continue

    groups.setdefault(info["new_name"], []).append(info)  # Group by final target name

# Sort each target-name group so an exact-match keeper is preferred
for target_name in groups.keys():
    groups[target_name].sort(
        key=lambda x: (
            0 if safe_str(x["old_name"]).strip() == safe_str(target_name).strip() else 1,
            x["id"]
        )
    )

# Build preview rows
for target_name in sorted(groups.keys(), key=lambda x: normalize_compare_text(x)):
    items = groups[target_name]
    for i, item in enumerate(items):
        if i == 0 and normalize_compare_text(item["old_name"]) == normalize_compare_text(target_name):  # Exact keeper
            action = "Keep"
        elif i == 0:  # First item becomes renamed keeper
            action = "Rename"
        else:  # Remaining items are duplicates to merge
            action = "Merge"

        preview_data.append([
            item["id"],
            action,
            item["old_name"],
            item["new_name"],
            item["kind"],
            item["size_text"],
            item["arrow_style"]
        ])

# Build preview text lines
preview_lines = [row_to_block(row) for row in preview_data]
preview_text = "\n\n".join(preview_lines)

# Execute rename / merge transaction when commit is enabled
if commit_changes:
    TransactionManager.Instance.EnsureInTransaction(doc)  # Start Revit transaction
    try:
        for target_name in sorted(groups.keys(), key=lambda x: normalize_compare_text(x)):
            items = groups[target_name]
            keeper = items[0]  # First sorted item is keeper
            keeper_elem = keeper["element"]

            if safe_str(keeper["old_name"]).strip() != safe_str(target_name).strip():  # Rename keeper if needed
                try:
                    ok = set_type_name(keeper_elem, target_name)
                    if ok:
                        renamed_data.append([keeper["id"], keeper["old_name"], target_name])
                    else:
                        failed_data.append([keeper["id"], "rename", keeper["old_name"], target_name, "Could not set type name"])
                except Exception as ex:
                    failed_data.append([keeper["id"], "rename", keeper["old_name"], target_name, safe_str(ex)])

            for dup in items[1:]:  # Process duplicate items
                dup_elem = dup["element"]
                references_repointed = 0
                deleted = False

                try:
                    references_repointed = repoint_type_references(doc, dup_elem.Id, keeper_elem.Id)  # Move references

                    if delete_merged_duplicates:  # Optional delete after repoint
                        try:
                            doc.Delete(dup_elem.Id)
                            deleted = True
                        except Exception as ex:
                            failed_data.append([dup["id"], "delete", dup["old_name"], target_name, safe_str(ex)])

                    merged_data.append([
                        dup["id"],
                        dup["old_name"],
                        target_name,
                        keeper["id"],
                        references_repointed,
                        deleted
                    ])
                except Exception as ex:
                    failed_data.append([dup["id"], "merge", dup["old_name"], target_name, safe_str(ex)])

        TransactionManager.Instance.TransactionTaskDone()  # Commit transaction
    except Exception:  # Roll back on fatal error
        TransactionManager.Instance.ForceCloseTransaction()
        raise

# Build summary lines
summary_lines = []
summary_lines.append("Commit: {0}".format(commit_changes))
summary_lines.append("Delete merged duplicates: {0}".format(delete_merged_duplicates))
summary_lines.append("Case mode: {0}".format(case_mode))
summary_lines.append("Preferred sizes input: {0}".format(safe_str(preferred_sizes_input)))
summary_lines.append("Preferred sizes parsed: {0}".format(", ".join(preferred_sizes_text) if preferred_sizes_text else "<none>"))
summary_lines.append("Total found: {0}".format(len(arrowheads)))
summary_lines.append("Processable: {0}".format(len(preview_data)))
summary_lines.append("Skipped: {0}".format(len(skipped_data)))
summary_lines.append("Unknown styles: {0}".format(len(unknown_style_data)))
summary_lines.append("Renamed: {0}".format(len(renamed_data)))
summary_lines.append("Merged: {0}".format(len(merged_data)))
summary_lines.append("Failed: {0}".format(len(failed_data)))

# Build full text report
text_blocks = ["\n".join(summary_lines)]

if preview_lines:  # Include preview/results section
    header = "PREVIEW" if not commit_changes else "RESULTS"
    text_blocks.append(header + "\n" + "\n\n".join(preview_lines))

if renamed_data:  # Include renamed section
    renamed_lines = []
    for row in renamed_data:
        renamed_lines.append("ID: {0}\n\tRenamed: {1}\n\tTo:      {2}".format(row[0], row[1], row[2]))
    text_blocks.append("RENAMED\n" + "\n\n".join(renamed_lines))

if merged_data:  # Include merged section
    merged_lines = []
    for row in merged_data:
        merged_lines.append(
            "ID: {0}\n\tMerged From: {1}\n\tMerged To:   {2}\n\tKeeper ID:   {3}\n\tRefs Moved:  {4}\n\tDeleted:     {5}".format(
                row[0], row[1], row[2], row[3], row[4], row[5]
            )
        )
    text_blocks.append("MERGED\n" + "\n\n".join(merged_lines))

if skipped_data:  # Include skipped section
    skipped_lines = []
    for row in skipped_data:
        skipped_lines.append("ID: {0}\n\tName: {1}\n\tReason: {2}".format(row[0], row[1], row[2]))
    text_blocks.append("SKIPPED\n" + "\n\n".join(skipped_lines))

if unknown_style_data:  # Include unknown style section
    unknown_lines = []
    for row in unknown_style_data:
        unknown_lines.append("ID: {0}\n\tName: {1}\n\tStyle: {2}\n\tReason: {3}".format(row[0], row[1], row[2], row[3]))
    text_blocks.append("UNKNOWN STYLES\n" + "\n\n".join(unknown_lines))

if failed_data:  # Include failures section
    failed_lines = []
    for row in failed_data:
        failed_lines.append("ID: {0}\n\tAction: {1}\n\tFrom: {2}\n\tTo:   {3}\n\tError: {4}".format(row[0], row[1], row[2], row[3], row[4]))
    text_blocks.append("FAILED\n" + "\n\n".join(failed_lines))

# Include style inventory section
style_inventory = [[style_id, style_counts[style_id]] for style_id in sorted(style_counts.keys())]
if style_inventory:
    style_lines = []
    for row in style_inventory:
        style_lines.append("Style: {0}\n\tCount: {1}".format(row[0], row[1]))
    text_blocks.append("STYLE INVENTORY\n" + "\n\n".join(style_lines))

# Final combined text
final_text = "\n\n".join(text_blocks)

# Dynamo output
OUT = {
    "summary": "\n".join(summary_lines),
    "text": final_text,
    "preview_text": preview_text,
    "preview_lines": preview_lines,
    "preview_data": preview_data,
    "renamed_data": renamed_data,
    "merged_data": merged_data,
    "failed_data": failed_data,
    "skipped_data": skipped_data,
    "style_inventory": style_inventory,
    "unknown_style_data": unknown_style_data,
    "preferred_sizes_input": safe_str(preferred_sizes_input),
    "preferred_sizes_inches": preferred_sizes_inches,
    "preferred_sizes_text": preferred_sizes_text
}
