# v00-06
# py-line-style-reconcile.py
# Dynamo Python - Revit line style reconcile / remap tool
#
# Purpose:
#   Reconcile Revit line styles from separated system/custom definitions.
#   Modify Revit system line styles such as <Thin Lines> in place.
#   Create / reconcile custom standard line styles such as FINE and WIDE-X.
#   Remap unmanaged custom line styles to managed standards.
#   Infer numeric pen-style names like 9_solid to nearest custom standard.
#   Optionally delete unmanaged custom line styles after remap.
#
# IMPORTANT:
#   Revit system line styles wrapped in < > are NOT remapped and NOT deleted.
#   View-specific element overrides are intentionally NOT scanned,
#   NOT remapped, and NOT preserved.
#
# Dynamo Inputs:
#   IN[0]  = KEEP patterns CSV string
#   IN[1]  = CLEANUP / FORCE REMAP patterns CSV string
#   IN[2]  = SYSTEM line style definitions string/list
#            Format: <Name>|Weight|RGB|Pattern
#   IN[3]  = NEW / CUSTOM standard line style definitions string/list
#            Format: Name|Weight|RGB|Pattern
#   IN[4]  = DryRun bool
#   IN[5]  = RemapPlacedCurveElements bool
#   IN[6]  = ReconcileObjectStyles bool
#   IN[7]  = RemapViewTemplateCategoryOverrides bool
#   IN[8]  = RemapViewCategoryOverrides bool
#   IN[9]  = DeleteUnmanagedLineStyles bool
#   IN[10] = BlockDeleteIfCurveFailures bool
#
# Output:
#   OUT = report list


import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

import csv
import fnmatch
import re

try:
    from io import StringIO
except:
    from StringIO import StringIO

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager


# ============================================================
# Environment
# ============================================================

doc = DocumentManager.Instance.CurrentDBDocument


# ============================================================
# Fallback custom standard definitions
# ============================================================

FALLBACK_CUSTOM_DEFS = [
    {"Name": "FINE-XX", "LineWeight": 1, "Color": (0, 0, 0), "PatternName": "Solid"},
    {"Name": "FINE-X", "LineWeight": 2, "Color": (0, 0, 0), "PatternName": "Solid"},
    {"Name": "FINE", "LineWeight": 3, "Color": (0, 0, 0), "PatternName": "Solid"},
    {"Name": "WIDE-X", "LineWeight": 4, "Color": (0, 0, 0), "PatternName": "Solid"},
    {"Name": "WIDE-XX", "LineWeight": 5, "Color": (0, 0, 0), "PatternName": "Solid"},
    {"Name": "WIDE-XXX", "LineWeight": 6, "Color": (0, 0, 0), "PatternName": "Solid"},
    {"Name": "WIDE-XXXX", "LineWeight": 7, "Color": (0, 0, 0), "PatternName": "Solid"}
]


# ============================================================
# Input helpers
# ============================================================

# Safely gets a Dynamo input by index and returns the default if missing.
def get_in(index, default_value):
    try:
        if len(IN) > index:
            value = IN[index]

            if value is not None:
                return value
    except:
        pass

    return default_value


# Converts Dynamo/string values to bool.
def as_bool(value, default_value):
    if isinstance(value, bool):
        return value

    if value is None:
        return default_value

    text = str(value).strip().lower()

    if text in ["true", "t", "yes", "y", "1"]:
        return True

    if text in ["false", "f", "no", "n", "0"]:
        return False

    return default_value


# Splits a Dynamo string/list into usable definition rows.
def split_lines_or_csv(value):
    if value is None:
        return []

    raw = []

    if isinstance(value, list):
        for item in value:
            if item is None:
                continue

            raw.extend(re.split(r'[\r\n,]+', str(item)))
    else:
        raw.extend(re.split(r'[\r\n,]+', str(value)))

    rows = []

    for item in raw:
        text = str(item).strip()

        if text:
            rows.append(text)

    return rows


# Parses a CSV string or Dynamo list into lowercase wildcard patterns.
def parse_csv_patterns(value):
    if value is None:
        return []

    if isinstance(value, list):
        raw_items = value
    else:
        text = str(value).strip()

        if not text:
            return []

        try:
            raw_items = list(csv.reader(StringIO(text)))[0]
        except:
            raw_items = text.split(",")

    patterns = []

    for item in raw_items:
        if item is None:
            continue

        p = str(item).strip().strip('"').strip("'")

        if p:
            patterns.append(p.lower())

    return patterns


# Parses RGB formatted as 000-000-000.
def parse_rgb(rgb_text):
    parts = str(rgb_text).strip().split("-")

    if len(parts) != 3:
        return None

    try:
        r = int(parts[0])
        g = int(parts[1])
        b = int(parts[2])
    except:
        return None

    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))

    return (r, g, b)


# Parses line style definition rows in Name|Weight|RGB|Pattern format.
def parse_style_definitions(value, require_system):
    defs = []
    bad_rows = []
    skipped_wrong_kind = []

    for raw in split_lines_or_csv(value):
        line = str(raw).strip()

        if not line:
            continue

        parts = [p.strip() for p in line.split("|")]

        if len(parts) < 4:
            bad_rows.append(line)
            continue

        name = parts[0].strip().strip('"').strip("'")
        weight_text = parts[1].strip()
        rgb_text = parts[2].strip()
        pattern_name = parts[3].strip().strip('"').strip("'")

        if not name:
            bad_rows.append(line)
            continue

        is_system = is_system_line_style_name(name)

        if require_system and not is_system:
            skipped_wrong_kind.append(name)
            continue

        if not require_system and is_system:
            skipped_wrong_kind.append(name)
            continue

        try:
            weight = int(weight_text)
        except:
            bad_rows.append(line)
            continue

        rgb = parse_rgb(rgb_text)

        if rgb is None:
            bad_rows.append(line)
            continue

        defs.append({
            "Name": name,
            "LineWeight": weight,
            "Color": rgb,
            "PatternName": pattern_name
        })

    return defs, bad_rows, skipped_wrong_kind


# ============================================================
# Matching helpers
# ============================================================

# Returns True when a line style name is a Revit system style wrapped in < >.
def is_system_line_style_name(name):
    text = str(name).strip()
    return text.startswith("<") and text.endswith(">")


# Returns True when a name matches any wildcard pattern.
def wildcard_match(name, patterns):
    if not patterns:
        return False

    text = str(name).lower()

    for pattern in patterns:
        if fnmatch.fnmatch(text, pattern):
            return True

    return False


# Normalizes names for safer standard comparison.
def normalize_name(name):
    text = str(name).lower()
    text = re.sub(r'[\s_\-]+', '', text)
    return text


# Returns True when a name matches one of the managed custom standards.
def is_standard_name(name, custom_defs):
    if is_system_line_style_name(name):
        return False

    n = normalize_name(name)

    for d in custom_defs:
        if normalize_name(d["Name"]) == n:
            return True

    return False


# Builds default wildcard patterns for managed custom standards.
def get_default_patterns_for_standard(std_name):
    n = normalize_name(std_name)

    if n == "finexx":
        return ["*fine-xx*", "*finexx*"]

    if n == "finex":
        return ["*fine-x*", "*finex*", "*thin-x*", "*x-fine*"]

    if n == "fine":
        return ["*fine*", "*thin*", "*normal*"]

    if n == "widex":
        return ["*wide-x*", "*widex*", "*heavy-x*"]

    if n == "widexx":
        return ["*wide-xx*", "*widexx*", "*heavy-xx*"]

    if n == "widexxx":
        return ["*wide-xxx*", "*widexxx*", "*heavy-xxx*"]

    if n == "widexxxx":
        return ["*wide-xxxx*", "*widexxxx*", "*heavy-xxxx*"]

    return ["*" + std_name.lower() + "*"]


# Builds internal mapper rules from custom standard definitions.
def build_map_rules_from_custom_defs(custom_defs):
    rules = []

    for d in custom_defs:
        target = d["Name"]

        if is_system_line_style_name(target):
            continue

        patterns = [target]
        defaults = get_default_patterns_for_standard(target)

        for p in defaults:
            if p not in patterns:
                patterns.append(p)

        rules.append({
            "Target": target,
            "Patterns": [p.lower() for p in patterns]
        })

    return rules


# Infers a pen weight from names like 2_solid, _2_solid, 9-solid, or 6 solid.
def infer_weight_from_style_name(name):
    text = str(name).strip().lower()

    m = re.match(r'^_?(\d+)[\s_\-]', text)

    if not m:
        return None

    try:
        return int(m.group(1))
    except:
        return None


# Maps numbered unmanaged styles to the nearest managed custom standard by line weight.
def find_standard_by_nearest_weight(source_name, custom_defs):
    source_weight = infer_weight_from_style_name(source_name)

    if source_weight is None:
        return None

    candidates = []

    for d in custom_defs:
        name = d.get("Name", "")

        if is_system_line_style_name(name):
            continue

        weight = d.get("LineWeight", None)

        if weight is None:
            continue

        try:
            weight = int(weight)
        except:
            continue

        candidates.append((abs(weight - source_weight), weight, name))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], -x[1]))

    return candidates[0][2]


# Determines which managed standard a source style maps to by name/pattern.
def find_standard_target_name(source_name, custom_defs, map_rules):
    if is_system_line_style_name(source_name):
        return None

    source_norm = normalize_name(source_name)

    for d in custom_defs:
        std_name = d["Name"]

        if normalize_name(std_name) == source_norm:
            return std_name

    for rule in map_rules:
        target = rule["Target"]

        if is_system_line_style_name(target):
            continue

        for pattern in rule.get("Patterns", []):
            if fnmatch.fnmatch(source_name.lower(), pattern.lower()):
                return target

    return None


# Evaluates KEEP and CLEANUP rules where KEEP wins.
def can_cleanup(name, keep_patterns, cleanup_patterns):
    if is_system_line_style_name(name):
        return False, True, False

    keep_match = wildcard_match(name, keep_patterns)
    cleanup_match = wildcard_match(name, cleanup_patterns)

    if keep_match:
        return False, keep_match, cleanup_match

    if cleanup_match:
        return True, keep_match, cleanup_match

    return False, keep_match, cleanup_match


# ============================================================
# Revit category / graphics helpers
# ============================================================

# Gets the Revit Lines parent category.
def get_line_category():
    return doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)


# Returns subcategories from a parent Revit category.
def get_subcategories(parent_cat):
    return [c for c in parent_cat.SubCategories]


# Safely gets category name.
def get_category_name(cat):
    try:
        return cat.Name
    except:
        return ""


# Gets projection GraphicsStyle for a line subcategory.
def get_graphics_style(cat):
    try:
        return cat.GetGraphicsStyle(GraphicsStyleType.Projection)
    except:
        return None


# Finds a LinePatternElement by name. Solid uses GetSolidPatternId().
def get_line_pattern_id_by_name(pattern_name):
    if pattern_name is None:
        return LinePatternElement.GetSolidPatternId()

    text = str(pattern_name).strip()

    if not text:
        return LinePatternElement.GetSolidPatternId()

    if text.lower() == "solid":
        return LinePatternElement.GetSolidPatternId()

    collector = FilteredElementCollector(doc).OfClass(LinePatternElement)

    for elem in collector:
        try:
            if elem.Name.lower() == text.lower():
                return elem.Id
        except:
            pass

    return None


# Gets an existing custom line subcategory by name or creates it.
def ensure_line_subcategory(parent_cat, name):
    existing = None

    for subcat in get_subcategories(parent_cat):
        if get_category_name(subcat).lower() == name.lower():
            existing = subcat
            break

    if existing:
        return existing, False

    if is_system_line_style_name(name):
        return None, False

    new_cat = doc.Settings.Categories.NewSubcategory(parent_cat, name)
    return new_cat, True


# Applies line weight, color, and pattern to an existing line style category.
def apply_line_style_definition(cat, style_def):
    changed = False
    messages = []

    if cat is None:
        return changed, ["Category not found"]

    try:
        lw = style_def.get("LineWeight", None)

        if lw is not None:
            old_lw = cat.GetLineWeight(GraphicsStyleType.Projection)

            if old_lw != lw:
                cat.SetLineWeight(lw, GraphicsStyleType.Projection)
                changed = True
                messages.append("weight {} -> {}".format(old_lw, lw))
    except Exception as e:
        messages.append("weight failed: {}".format(str(e)))

    try:
        rgb = style_def.get("Color", None)

        if rgb:
            old_color = cat.LineColor
            new_color = Color(rgb[0], rgb[1], rgb[2])

            if (
                old_color.Red != new_color.Red or
                old_color.Green != new_color.Green or
                old_color.Blue != new_color.Blue
            ):
                cat.LineColor = new_color
                changed = True
                messages.append(
                    "color {:03d}-{:03d}-{:03d} -> {:03d}-{:03d}-{:03d}".format(
                        old_color.Red,
                        old_color.Green,
                        old_color.Blue,
                        new_color.Red,
                        new_color.Green,
                        new_color.Blue
                    )
                )
    except Exception as e:
        messages.append("color failed: {}".format(str(e)))

    try:
        pattern_name = style_def.get("PatternName", None)
        pattern_id = get_line_pattern_id_by_name(pattern_name)

        if pattern_id is None:
            messages.append("pattern not found: {}".format(pattern_name))
        else:
            old_pattern_id = cat.GetLinePatternId(GraphicsStyleType.Projection)

            if old_pattern_id != pattern_id:
                cat.SetLinePatternId(pattern_id, GraphicsStyleType.Projection)
                changed = True
                messages.append("pattern -> {}".format(pattern_name))
    except Exception as e:
        messages.append("pattern failed: {}".format(str(e)))

    return changed, messages


# Copies category override graphics from source line subcategory to target.
def copy_category_override(view, source_cat, target_cat):
    try:
        ogs = view.GetCategoryOverrides(source_cat.Id)
        view.SetCategoryOverrides(target_cat.Id, ogs)
        return True, None
    except Exception as e:
        return False, str(e)


# Clears category override graphics from source line subcategory.
def reset_category_override(view, source_cat):
    try:
        empty_ogs = OverrideGraphicSettings()
        view.SetCategoryOverrides(source_cat.Id, empty_ogs)
        return True, None
    except Exception as e:
        return False, str(e)


# Rebuilds lookup dictionaries for line subcategories.
def rebuild_line_style_lookup(line_cat):
    line_subcats = get_subcategories(line_cat)

    name_to_cat = {}
    id_to_cat = {}
    id_to_name = {}
    style_id_to_cat = {}

    for cat in line_subcats:
        name = get_category_name(cat)

        name_to_cat[name.lower()] = cat
        id_to_cat[cat.Id.IntegerValue] = cat
        id_to_name[cat.Id.IntegerValue] = name

        gs = get_graphics_style(cat)

        if gs:
            style_id_to_cat[gs.Id.IntegerValue] = cat

    return line_subcats, name_to_cat, id_to_cat, id_to_name, style_id_to_cat


# Gets a managed standard category by target name.
def get_target_category(target_name, standard_cats, name_to_cat):
    if target_name is None:
        return None

    target_text = str(target_name).strip()
    target_key = target_text.lower()

    if target_text in standard_cats:
        return standard_cats[target_text]

    if target_key in name_to_cat:
        return name_to_cat[target_key]

    target_norm = normalize_name(target_text)

    for key, cat in name_to_cat.items():
        if normalize_name(key) == target_norm:
            return cat

    return None


# Gets readable element context for failure reports.
def get_element_context(elem):
    try:
        elem_id = elem.Id.IntegerValue
    except:
        elem_id = "UnknownId"

    try:
        cat_name = elem.Category.Name if elem.Category else "NoCategory"
    except:
        cat_name = "NoCategory"

    try:
        owner_view_id = elem.OwnerViewId.IntegerValue
    except:
        owner_view_id = "NoOwnerView"

    return "ElementId={}, Category={}, OwnerViewId={}".format(
        elem_id,
        cat_name,
        owner_view_id
    )


# ============================================================
# Inputs
# ============================================================

keep_patterns = parse_csv_patterns(get_in(0, ""))
cleanup_patterns = parse_csv_patterns(get_in(1, ""))

system_input = get_in(2, "")
custom_input = get_in(3, "")

system_defs, bad_system_rows, skipped_system_wrong_kind = parse_style_definitions(
    system_input,
    True
)

custom_defs, bad_custom_rows, skipped_custom_wrong_kind = parse_style_definitions(
    custom_input,
    False
)

if not custom_defs:
    custom_defs = FALLBACK_CUSTOM_DEFS

map_rules = build_map_rules_from_custom_defs(custom_defs)

dry_run = as_bool(get_in(4, True), True)

remap_curve_elements = as_bool(get_in(5, True), True)
reconcile_object_styles = as_bool(get_in(6, True), True)
remap_view_templates = as_bool(get_in(7, True), True)
remap_views = as_bool(get_in(8, True), True)
delete_unmanaged = as_bool(get_in(9, True), True)
block_delete_if_curve_failures = as_bool(get_in(10, True), True)


# ============================================================
# Pre-collect and report header
# ============================================================

results = []

results.append("Line styles reconcile v00-06")
results.append("DryRun: {}".format(dry_run))
results.append("KEEP patterns: {}".format(", ".join(keep_patterns) if keep_patterns else "<none>"))
results.append("CLEANUP patterns: {}".format(", ".join(cleanup_patterns) if cleanup_patterns else "<none>"))
results.append("KEEP wins over CLEANUP: True")
results.append("System <*> styles are modified in place only: True")
results.append("Numeric pen-style mapping enabled: True")
results.append("Block delete if CurveElement failures: {}".format(block_delete_if_curve_failures))
results.append("System definition rows parsed from IN[2]: {}".format(len(system_defs)))
results.append("Custom standard definition rows parsed from IN[3]: {}".format(len(custom_defs)))
results.append("Bad system definition rows skipped: {}".format(len(bad_system_rows)))
results.append("Bad custom definition rows skipped: {}".format(len(bad_custom_rows)))
results.append("Internal map rules built from custom standards: {}".format(len(map_rules)))
results.append("Remap placed CurveElements: {}".format(remap_curve_elements))
results.append("Reconcile Object Styles: {}".format(reconcile_object_styles))
results.append("Remap View Template category overrides: {}".format(remap_view_templates))
results.append("Remap View category overrides: {}".format(remap_views))
results.append("Delete unmanaged custom line styles: {}".format(delete_unmanaged))
results.append("View-specific element overrides: NOT SCANNED / NOT REMAPPED / NOT PRESERVED")
results.append(
    "Manual view-specific element overrides may be obliterated or visually changed. "
    "Replace them with family objects, detail components, line-based families, filters, "
    "object styles, or view template controls."
)

if bad_system_rows:
    results.append("=== Bad system definition rows skipped ===")

    for row in bad_system_rows:
        results.append("Bad system row: {}".format(row))

if bad_custom_rows:
    results.append("=== Bad custom definition rows skipped ===")

    for row in bad_custom_rows:
        results.append("Bad custom row: {}".format(row))

if skipped_system_wrong_kind:
    results.append("=== Rows skipped from IN[2] because they were not system <*> styles ===")

    for name in skipped_system_wrong_kind:
        results.append("Skipped IN[2] non-system row: {}".format(name))

if skipped_custom_wrong_kind:
    results.append("=== Rows skipped from IN[3] because they were system <*> styles ===")

    for name in skipped_custom_wrong_kind:
        results.append("Skipped IN[3] system row: {}".format(name))

line_cat = get_line_category()

(
    line_subcats,
    name_to_cat,
    id_to_cat,
    id_to_name,
    style_id_to_cat
) = rebuild_line_style_lookup(line_cat)


# ============================================================
# Main transaction
# ============================================================

t = None

created_standards = []
updated_standards = []
updated_system_styles = []
missing_system_styles = []
standard_cats = {}

remap_plan = {}
protected_system_styles = []
kept_by_pattern = []
cleanup_forced = []
keep_cleanup_conflicts = []
numeric_weight_mapped = []

curve_remapped = 0
curve_failed = 0
curve_failure_details = []

template_overrides_remapped = 0
template_overrides_failed = 0

view_overrides_remapped = 0
view_overrides_failed = 0

deleted = 0
delete_failed = 0
dryrun_delete = 0
delete_blocked = False

try:
    if not dry_run:
        t = Transaction(doc, "Reconcile line styles v00-06")
        t.Start()

    # --------------------------------------------------------
    # Reconcile system styles in place.
    # --------------------------------------------------------

    if reconcile_object_styles:
        for d in system_defs:
            name = d["Name"]
            cat = name_to_cat.get(name.lower(), None)

            if cat is None:
                missing_system_styles.append(name)
                continue

            if dry_run:
                updated_system_styles.append(name)
                continue

            changed, messages = apply_line_style_definition(cat, d)

            if changed:
                updated_system_styles.append("{} ({})".format(name, "; ".join(messages)))

    # --------------------------------------------------------
    # Create / reconcile custom standard line styles.
    # --------------------------------------------------------

    for d in custom_defs:
        std_name = d["Name"]

        if is_system_line_style_name(std_name):
            continue

        if dry_run:
            existing = name_to_cat.get(std_name.lower(), None)

            if existing:
                standard_cats[std_name] = existing

                if reconcile_object_styles:
                    updated_standards.append(std_name)
            else:
                results.append("DRYRUN: Would create standard: {}".format(std_name))

            continue

        std_cat, was_created = ensure_line_subcategory(line_cat, std_name)

        if std_cat is None:
            continue

        standard_cats[std_name] = std_cat

        if was_created:
            created_standards.append(std_name)

        if reconcile_object_styles:
            changed, messages = apply_line_style_definition(std_cat, d)

            if changed:
                updated_standards.append("{} ({})".format(std_name, "; ".join(messages)))

    # --------------------------------------------------------
    # Refresh category lookups after creating standards.
    # --------------------------------------------------------

    if not dry_run:
        doc.Regenerate()

    (
        line_subcats,
        name_to_cat,
        id_to_cat,
        id_to_name,
        style_id_to_cat
    ) = rebuild_line_style_lookup(line_cat)

    for d in custom_defs:
        std_name = d["Name"]

        target_cat = get_target_category(
            std_name,
            standard_cats,
            name_to_cat
        )

        if target_cat:
            standard_cats[std_name] = target_cat

    # --------------------------------------------------------
    # Build remap plan.
    # --------------------------------------------------------

    for cat in line_subcats:
        name = get_category_name(cat)

        if is_system_line_style_name(name):
            protected_system_styles.append(name)
            continue

        if is_standard_name(name, custom_defs):
            continue

        should_cleanup, keep_match, cleanup_match = can_cleanup(
            name,
            keep_patterns,
            cleanup_patterns
        )

        if keep_match and cleanup_match:
            keep_cleanup_conflicts.append(name)

        if keep_match:
            kept_by_pattern.append(name)
            continue

        target_name = find_standard_target_name(
            name,
            custom_defs,
            map_rules
        )

        if target_name is None and should_cleanup:
            target_name = find_standard_by_nearest_weight(
                name,
                custom_defs
            )

            if target_name:
                numeric_weight_mapped.append(name)

        if target_name:
            target_cat = get_target_category(
                target_name,
                standard_cats,
                name_to_cat
            )

            if target_cat is None:
                curve_failure_details.append(
                    "Remap target category not found for source '{}' -> target '{}'".format(
                        name,
                        target_name
                    )
                )
                continue

            remap_plan[cat.Id.IntegerValue] = {
                "SourceCat": cat,
                "SourceName": name,
                "TargetName": target_name,
                "TargetCat": target_cat
            }

            if should_cleanup:
                cleanup_forced.append(name)

            continue

        if should_cleanup:
            fallback_target = "FINE"
            target_cat = get_target_category(
                fallback_target,
                standard_cats,
                name_to_cat
            )

            if target_cat is None:
                curve_failure_details.append(
                    "Fallback target category not found for source '{}' -> target '{}'".format(
                        name,
                        fallback_target
                    )
                )
                continue

            remap_plan[cat.Id.IntegerValue] = {
                "SourceCat": cat,
                "SourceName": name,
                "TargetName": fallback_target,
                "TargetCat": target_cat
            }

            cleanup_forced.append(name)
            continue

    # --------------------------------------------------------
    # Remap placed detail/model curve elements.
    # --------------------------------------------------------

    if remap_curve_elements:
        curve_elements = list(FilteredElementCollector(doc).OfClass(CurveElement))

        for ce in curve_elements:
            try:
                old_style = ce.LineStyle

                if old_style is None:
                    continue

                old_cat = style_id_to_cat.get(old_style.Id.IntegerValue, None)

                if old_cat is None:
                    continue

                old_name = get_category_name(old_cat)

                if is_system_line_style_name(old_name):
                    continue

                plan = remap_plan.get(old_cat.Id.IntegerValue, None)

                if plan is None:
                    continue

                target_cat = plan["TargetCat"]

                if target_cat is None:
                    curve_failed += 1
                    curve_failure_details.append(
                        "{} | old={} | target category missing: {}".format(
                            get_element_context(ce),
                            old_name,
                            plan["TargetName"]
                        )
                    )
                    continue

                target_style = get_graphics_style(target_cat)

                if target_style is None:
                    curve_failed += 1
                    curve_failure_details.append(
                        "{} | old={} | target graphics style missing: {}".format(
                            get_element_context(ce),
                            old_name,
                            plan["TargetName"]
                        )
                    )
                    continue

                if dry_run:
                    curve_remapped += 1
                else:
                    ce.LineStyle = target_style
                    curve_remapped += 1

            except Exception as e:
                curve_failed += 1
                curve_failure_details.append(
                    "{} | exception: {}".format(
                        get_element_context(ce),
                        str(e)
                    )
                )

    # --------------------------------------------------------
    # Remap View Template category overrides.
    # --------------------------------------------------------

    if remap_view_templates:
        templates = [
            v for v in FilteredElementCollector(doc).OfClass(View)
            if v.IsTemplate
        ]

        for v in templates:
            for source_id, plan in remap_plan.items():
                source_cat = plan["SourceCat"]
                target_cat = plan["TargetCat"]

                if target_cat is None:
                    continue

                if dry_run:
                    continue

                ok, err = copy_category_override(v, source_cat, target_cat)

                if ok:
                    template_overrides_remapped += 1
                    reset_category_override(v, source_cat)
                else:
                    template_overrides_failed += 1

    # --------------------------------------------------------
    # Remap normal View category overrides.
    # --------------------------------------------------------

    if remap_views:
        views = [
            v for v in FilteredElementCollector(doc).OfClass(View)
            if not v.IsTemplate
        ]

        for v in views:
            for source_id, plan in remap_plan.items():
                source_cat = plan["SourceCat"]
                target_cat = plan["TargetCat"]

                if target_cat is None:
                    continue

                if dry_run:
                    continue

                ok, err = copy_category_override(v, source_cat, target_cat)

                if ok:
                    view_overrides_remapped += 1
                    reset_category_override(v, source_cat)
                else:
                    view_overrides_failed += 1

    # --------------------------------------------------------
    # Delete unmanaged custom line subcategories only.
    # --------------------------------------------------------

    delete_blocked = (
        block_delete_if_curve_failures and
        curve_failed > 0
    )

    if delete_unmanaged and not delete_blocked:
        for source_id, plan in remap_plan.items():
            source_cat = plan["SourceCat"]
            source_name = plan["SourceName"]

            if is_system_line_style_name(source_name):
                continue

            if dry_run:
                dryrun_delete += 1
                continue

            try:
                doc.Delete(source_cat.Id)
                deleted += 1
            except:
                delete_failed += 1

    if dry_run and delete_unmanaged and delete_blocked:
        dryrun_delete = 0

    if not dry_run and t:
        t.Commit()

except Exception as ex:
    if not dry_run and t:
        t.RollBack()

    results.append("ERROR: {}".format(str(ex)))
    OUT = results


# ============================================================
# Final report
# ============================================================

results.append("Line styles reconcile complete")

if updated_system_styles:
    results.append("=== System styles modified in place ===")

    for name in sorted(updated_system_styles):
        if dry_run:
            results.append("DRYRUN: Would modify system style: {}".format(name))
        else:
            results.append("Modified system style: {}".format(name))

if missing_system_styles:
    results.append("=== System styles not found ===")

    for name in sorted(missing_system_styles):
        results.append("Missing system style: {}".format(name))

if not dry_run:
    for name in created_standards:
        results.append("Created standard: {}".format(name))

for name in updated_standards:
    if dry_run:
        results.append("DRYRUN: Would reconcile standard object style: {}".format(name))
    else:
        results.append("Updated standard object style: {}".format(name))

results.append("System defs processed: {}".format(len(system_defs)))
results.append("Custom standard defs processed: {}".format(len(custom_defs)))
results.append("Created custom standard styles: {}".format(len(created_standards)))
results.append("Updated system styles: {}".format(len(updated_system_styles)))
results.append("Updated custom standard styles: {}".format(len(updated_standards)))
results.append("Protected system styles found: {}".format(len(protected_system_styles)))
results.append("Remap candidates unmanaged custom subcats: {}".format(len(remap_plan)))
results.append("Numeric pen-weight mappings: {}".format(len(numeric_weight_mapped)))
results.append("Kept by KEEP patterns: {}".format(len(kept_by_pattern)))
results.append("Forced by CLEANUP patterns: {}".format(len(cleanup_forced)))
results.append("KEEP/CLEANUP conflicts kept: {}".format(len(keep_cleanup_conflicts)))

if numeric_weight_mapped:
    results.append("=== Numeric pen-weight mappings ===")

    for name in sorted(numeric_weight_mapped):
        results.append("Numeric mapped: {}".format(name))

if kept_by_pattern:
    results.append("=== Kept by KEEP patterns ===")

    for name in sorted(kept_by_pattern):
        results.append("Kept: {}".format(name))

if keep_cleanup_conflicts:
    results.append("=== KEEP/CLEANUP conflicts - KEEP won ===")

    for name in sorted(keep_cleanup_conflicts):
        results.append("Conflict kept: {}".format(name))

if cleanup_forced:
    results.append("=== Forced CLEANUP pattern matches ===")

    for name in sorted(cleanup_forced):
        results.append("Forced cleanup/remap: {}".format(name))

if remap_plan:
    results.append("=== Remap plan - custom styles only ===")

    for source_id, plan in sorted(remap_plan.items(), key=lambda x: x[1]["SourceName"]):
        results.append(
            "Map: {} -> {}".format(
                plan["SourceName"],
                plan["TargetName"]
            )
        )

results.append("Remapped CurveElements: {}".format(curve_remapped))
results.append("CurveElements failed: {}".format(curve_failed))

if curve_failure_details:
    results.append("=== CurveElement remap failure examples ===")

    max_failures_to_report = 25

    for detail in curve_failure_details[:max_failures_to_report]:
        results.append("Curve failure: {}".format(detail))

    if len(curve_failure_details) > max_failures_to_report:
        results.append(
            "Curve failure examples truncated. Total failures/details: {}".format(
                len(curve_failure_details)
            )
        )

if delete_blocked:
    results.append("DELETE BLOCKED: CurveElement failures were detected and IN[10] is True.")

if dry_run:
    if delete_blocked:
        results.append("DRYRUN: Delete would be blocked because CurveElement failures were detected.")
    else:
        results.append("DRYRUN: Would delete unmanaged custom subcats: {}".format(dryrun_delete))
else:
    results.append("View Template category override attempts succeeded: {}".format(template_overrides_remapped))
    results.append("View Template category override attempts failed/skipped: {}".format(template_overrides_failed))
    results.append("View category override attempts succeeded: {}".format(view_overrides_remapped))
    results.append("View category override attempts failed/skipped: {}".format(view_overrides_failed))
    results.append("Deleted unmanaged custom subcats best effort: {}".format(deleted))
    results.append("Delete unmanaged custom failed: {}".format(delete_failed))

results.append("=== Important limitation ===")
results.append("System <*> line styles were not remapped.")
results.append("System <*> line styles were not deleted.")
results.append("System <*> line styles were modified in place only when listed in IN[2].")
results.append("View-specific element overrides were intentionally not scanned.")
results.append("View-specific element overrides were intentionally not remapped.")
results.append("View-specific element overrides were intentionally not preserved.")
results.append(
    "Any drafting that depends on manual per-view element overrides should be rebuilt "
    "using family objects, detail components, line-based families, filters, object styles, "
    "or view template controls instead."
)

OUT = results
