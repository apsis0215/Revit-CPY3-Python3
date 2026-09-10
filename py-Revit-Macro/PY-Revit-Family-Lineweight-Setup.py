# PY-Revit-Family-Lineweight-Setup.py
# Revit 2025 Family Editor - Dynamo CPython3
#
# PURPOSE
# Create or update canonical family Object Styles / subcategories.
# Optionally remap existing custom Object Styles to canonical styles.
# Optionally purge ALL unused custom Object Styles after remapping.
#
# INPUTS
# IN[0] : CreateDefaults bool
#         True creates missing canonical styles and resets their weights.
#
# IN[1] : RemapExisting bool
#         True remaps eligible existing styles to canonical styles.
#
# IN[2] : PurgeUnused bool
#         True deletes unused custom Object Styles after remapping.
#         Canonical styles are also purged when unused.
#
# IN[3] : KeepPatterns CSV string or Dynamo list
#         Wildcards supported: * and ?
#
#         Example:
#         *ADA*, *Clash*, *Overhead*, *Beyond*
#
# REMAP PRIORITY
# 1. Existing projection line weight
# 2. Fuzzy name matching when no canonical weight matches
#
# PURGE PROTECTION
# Built-in Revit styles are always kept.
# IN[3] matching styles are always kept.
# Styles still used by family geometry are kept.
#
# IMPORTANT
# Purge uses a snapshot of subcategory names before deleting anything.
# After deletion, styles are retrieved directly by name rather than
# re-enumerating Category.SubCategories. This avoids stale Revit
# Category proxy objects after deletion.


import clr
import csv
import fnmatch
import re

from difflib import SequenceMatcher


# ======================================================================
# REVIT API REFERENCES
# ======================================================================

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    CurveByPoints,
    CurveElement,
    FilteredElementCollector,
    GenericForm,
    GraphicsStyle,
    GraphicsStyleType,
    ModelCurve,
    ModelText,
    SubTransaction,
    SymbolicCurve,
    Transaction
)


# ======================================================================
# DYNAMO REVIT DOCUMENT
# ======================================================================

clr.AddReference("RevitServices")

from RevitServices.Persistence import DocumentManager

# Get the currently open Revit document.
doc = DocumentManager.Instance.CurrentDBDocument


# ======================================================================
# INPUTS
# ======================================================================

# IN[0] controls creation and normalization of canonical Object Styles.
create_defaults = (
    bool(IN[0])
    if len(IN) > 0 and IN[0] is not None
    else False
)

# IN[1] controls remapping of existing custom Object Styles.
remap_existing = (
    bool(IN[1])
    if len(IN) > 1 and IN[1] is not None
    else False
)

# IN[2] controls removal of unused custom Object Styles.
purge_unused = (
    bool(IN[2])
    if len(IN) > 2 and IN[2] is not None
    else False
)

# IN[3] contains wildcard style names that must always be retained.
keep_input = (
    IN[3]
    if len(IN) > 3
    else None
)


# ======================================================================
# CANONICAL OBJECT STYLES
# ======================================================================
#
# Each tuple contains:
# Canonical Object Style name
# Revit line weight number
#

CANONICAL_STYLES = [
    ("FINE-XX", 1),
    ("FINE-X", 2),
    ("FINE", 3),
    ("THIN", 4),
    ("MEDIUM", 5),
    ("WIDE", 6),
    ("WIDE-X", 7),
    ("WIDE-XX", 8),
    ("WIDE-XXX", 9),
    ("WIDE-XXXX", 10),
    ("THIN+", 15),
    ("WIDE+", 16)
]


# Default protected patterns when IN[3] is empty or disconnected.
DEFAULT_KEEP_PATTERNS = [
    "*ADA*",
    "*Clash*",
    "*Overhead*",
    "*Beyond*"
]


# ======================================================================
# OUTPUT
# ======================================================================

result = {
    "Status": "",
    "FamilyName": "",
    "FamilyCategory": "",
    "CreateDefaults": create_defaults,
    "RemapExisting": remap_existing,
    "PurgeUnused": purge_unused,
    "KeepPatterns": [],
    "Created": [],
    "Updated": [],
    "Protected": [],
    "RemapPlan": [],
    "Remapped": [],
    "RemapSkipped": [],
    "PurgeProtected": [],
    "Purged": [],
    "PurgeSkipped": [],
    "Errors": []
}


# ======================================================================
# FUNCTION
# id_value
#
# PURPOSE
# Convert a Revit ElementId into a normal Python integer.
#
# Revit 2025 uses ElementId.Value.
# IntegerValue is retained only as a compatibility fallback.
# ======================================================================

def id_value(element_id):

    # Return nothing when no ElementId was supplied.
    if element_id is None:
        return None

    # Use the Revit 2025 ElementId.Value property first.
    try:
        return int(element_id.Value)

    # Fall back to the older IntegerValue property.
    except:
        try:
            return int(element_id.IntegerValue)

        except:
            return None


# ======================================================================
# FUNCTION
# nullable_int_value
#
# PURPOSE
# Convert values returned by Category.GetLineWeight into Python integers.
# ======================================================================

def nullable_int_value(value):

    # Return nothing when Revit returned no line weight.
    if value is None:
        return None

    # Handle a .NET Nullable integer.
    try:

        if value.HasValue:
            return int(value.Value)

        return None

    except:
        pass

    # Dynamo CPython may already have converted the value to an integer.
    try:
        return int(value)

    except:
        return None


# ======================================================================
# FUNCTION
# collect_family_elements
#
# PURPOSE
# Collect actual non-type elements from the family document.
#
# FilteredElementCollector requires at least one filter before calling
# ToElements in Revit 2025.
# ======================================================================

def collect_family_elements():

    # Exclude element types because style assignments occur on geometry
    # and annotation instances.
    return list(
        FilteredElementCollector(doc)
        .WhereElementIsNotElementType()
        .ToElements()
    )


# ======================================================================
# FUNCTION
# get_subcategory_snapshot
#
# PURPOSE
# Safely create a snapshot of current family subcategory names.
#
# This function is called BEFORE purge deletion begins.
#
# Invalid Category wrappers are skipped instead of causing the entire
# Dynamo operation to fail.
# ======================================================================

def get_subcategory_snapshot(parent_category):

    snapshot = []

    # Return an empty snapshot when no parent category exists.
    if parent_category is None:
        return snapshot

    try:
        subcategories = parent_category.SubCategories

    except:
        return snapshot

    # Return an empty snapshot when there are no subcategories.
    if subcategories is None:
        return snapshot

    # Enumerate the CategoryNameMap only while it is stable.
    for subcategory in subcategories:

        try:

            # Reading Name verifies that the Category wrapper is valid.
            name = str(subcategory.Name)

            snapshot.append(
                (
                    name,
                    subcategory
                )
            )

        # Skip invalid Revit Category proxy objects.
        except:
            continue

    return snapshot


# ======================================================================
# FUNCTION
# get_subcategory_exact
#
# PURPOSE
# Retrieve a subcategory directly from CategoryNameMap using its name.
#
# IMPORTANT
# This avoids enumerating SubCategories after deletion.
# ======================================================================

def get_subcategory_exact(
    parent_category,
    subcategory_name
):

    # A valid parent category is required.
    if parent_category is None:
        return None

    try:
        subcategories = parent_category.SubCategories

    except:
        return None

    # Return nothing when the CategoryNameMap is unavailable.
    if subcategories is None:
        return None

    # Verify that the exact name currently exists.
    try:

        if not subcategories.Contains(
            subcategory_name
        ):
            return None

    except:
        pass

    # Use the .NET indexed property directly.
    try:

        return subcategories.get_Item(
            subcategory_name
        )

    except:
        pass

    # Fall back to Python.NET indexer syntax.
    try:

        return subcategories[
            subcategory_name
        ]

    except:
        return None


# ======================================================================
# FUNCTION
# get_subcategory_by_name
#
# PURPOSE
# Find a subcategory case-insensitively.
#
# Direct exact lookup is attempted first.
# Enumeration is only used before purge deletion begins.
# ======================================================================

def get_subcategory_by_name(
    parent_category,
    subcategory_name
):

    # Try the fastest exact CategoryNameMap lookup first.
    exact_match = get_subcategory_exact(
        parent_category,
        subcategory_name
    )

    if exact_match is not None:
        return exact_match

    target_name = str(
        subcategory_name
    ).strip().upper()

    # Fall back to a safe snapshot for case-insensitive comparison.
    for (
        current_name,
        subcategory
    ) in get_subcategory_snapshot(
        parent_category
    ):

        # Compare names without case sensitivity.
        if (
            current_name.strip().upper()
            == target_name
        ):

            return subcategory

    return None


# ======================================================================
# FUNCTION
# set_line_weights
#
# PURPOSE
# Apply canonical projection and cut line weights.
# ======================================================================

def set_line_weights(
    subcategory,
    weight_id
):

    # Set projection weight.
    subcategory.SetLineWeight(
        int(weight_id),
        GraphicsStyleType.Projection
    )

    # Some family categories do not support cut Object Style settings.
    try:

        subcategory.SetLineWeight(
            int(weight_id),
            GraphicsStyleType.Cut
        )

    except:
        pass


# ======================================================================
# FUNCTION
# flatten_input
#
# PURPOSE
# Flatten Dynamo or .NET list input used by IN[3].
# ======================================================================

def flatten_input(value):

    output = []

    # Ignore null values.
    if value is None:
        return output

    # Treat a string as one object instead of iterating characters.
    if isinstance(value, str):

        output.append(value)

        return output

    # Recursively flatten lists or .NET collections.
    try:

        for item in value:

            output.extend(
                flatten_input(item)
            )

        return output

    # Treat non-list objects as one value.
    except:

        output.append(value)

        return output


# ======================================================================
# FUNCTION
# parse_keep_patterns
#
# PURPOSE
# Parse CSV, semicolon-separated, newline-separated, or Dynamo lists.
#
# Examples:
# *ADA*, *Clash*, *Overhead*, *Beyond*
#
# \*ADA\* is also accepted and converted to *ADA*.
# ======================================================================

def parse_keep_patterns(value):

    patterns = []

    # Use the default protection list when IN[3] is disconnected.
    if value is None:

        return list(
            DEFAULT_KEEP_PATTERNS
        )

    # Process each flattened input item.
    for item in flatten_input(value):

        text = str(item).strip()

        # Ignore empty input values.
        if not text:
            continue

        # Normalize supported separators to commas.
        text = text.replace(
            ";",
            ","
        )

        text = text.replace(
            "\r",
            ","
        )

        text = text.replace(
            "\n",
            ","
        )

        # Parse the resulting value as CSV.
        for row in csv.reader([text]):

            for token in row:

                pattern = str(
                    token
                ).strip()

                # Ignore empty CSV fields.
                if not pattern:
                    continue

                # Convert escaped wildcard characters.
                pattern = pattern.replace(
                    "\\*",
                    "*"
                )

                pattern = pattern.replace(
                    "\\?",
                    "?"
                )

                patterns.append(
                    pattern
                )

    # Use defaults when a connected input resolves to an empty list.
    if not patterns:

        return list(
            DEFAULT_KEEP_PATTERNS
        )

    return patterns


# ======================================================================
# FUNCTION
# matches_keep_pattern
#
# PURPOSE
# Test an Object Style name against IN[3].
#
# Matching is case-insensitive.
# ======================================================================

def matches_keep_pattern(
    style_name,
    patterns
):

    source_name = str(
        style_name
    ).upper()

    # Test all protected wildcard patterns.
    for pattern in patterns:

        if fnmatch.fnmatchcase(
            source_name,
            str(pattern).upper()
        ):

            return (
                True,
                pattern
            )

    return (
        False,
        None
    )


# ======================================================================
# FUNCTION
# is_built_in_category
#
# PURPOSE
# Identify native Revit subcategories such as <Hidden Lines>.
#
# Built-in categories must never be remapped or purged.
# ======================================================================

def is_built_in_category(category):

    # A null Category cannot be built-in.
    if category is None:
        return False

    # Use the Revit BuiltInCategory property when available.
    try:

        return (
            category.BuiltInCategory
            != BuiltInCategory.INVALID
        )

    except:
        pass

    # Built-in Revit category ids are normally negative.
    try:

        category_id = id_value(
            category.Id
        )

        return (
            category_id is not None
            and category_id < 0
        )

    except:
        return False


# ======================================================================
# FUNCTION
# normalize_match_name
#
# PURPOSE
# Normalize old Object Style names for fuzzy matching.
# ======================================================================

def normalize_match_name(name):

    text = str(
        name
    ).upper().strip()

    # Preserve the canonical plus designation as meaningful text.
    text = text.replace(
        "+",
        " PLUS "
    )

    # Remove descriptive words that do not describe line weight.
    for remove_word in [
        "OBJECT",
        "STYLES",
        "STYLE",
        "LINES",
        "LINE",
        "SUBCATEGORY",
        "SOLID"
    ]:

        text = re.sub(
            r"\b"
            + remove_word
            + r"\b",
            " ",
            text
        )

    # Remove punctuation and spaces.
    text = re.sub(
        r"[^A-Z0-9]+",
        "",
        text
    )

    return text


# ======================================================================
# FUNCTION
# get_canonical_target
#
# PURPOSE
# Find the closest canonical Object Style.
#
# PRIORITY
# 1. Existing projection line weight.
# 2. Fuzzy name comparison.
#
# Example:
# 4_solid with projection weight 4 maps directly to THIN.
# ======================================================================

def get_canonical_target(
    source_subcategory
):

    source_name = str(
        source_subcategory.Name
    )

    existing_weight = None

    # Read the current projection line weight.
    try:

        existing_weight = nullable_int_value(
            source_subcategory.GetLineWeight(
                GraphicsStyleType.Projection
            )
        )

    except:
        existing_weight = None

    # Match directly by Revit line weight first.
    if existing_weight is not None:

        for (
            canonical_name,
            canonical_weight
        ) in CANONICAL_STYLES:

            if (
                int(existing_weight)
                == int(canonical_weight)
            ):

                return (
                    canonical_name,
                    1.0,
                    "LineWeight "
                    + str(existing_weight)
                )

    # Normalize the old name when line weight did not resolve it.
    source_normalized = normalize_match_name(
        source_name
    )

    best_name = None
    best_score = -1.0

    # Compare the old name against every canonical name.
    for (
        canonical_name,
        canonical_weight
    ) in CANONICAL_STYLES:

        target_normalized = normalize_match_name(
            canonical_name
        )

        # A blank normalized name has no useful match score.
        if not source_normalized:

            score = 0.0

        else:

            score = SequenceMatcher(
                None,
                source_normalized,
                target_normalized
            ).ratio()

        # Keep the highest scoring canonical style.
        if score > best_score:

            best_name = canonical_name
            best_score = score

    return (
        best_name,
        best_score,
        "Name"
    )


# ======================================================================
# FUNCTION
# graphics_style_category_id
#
# PURPOSE
# Return the family subcategory id represented by a GraphicsStyle.
# ======================================================================

def graphics_style_category_id(
    graphics_style
):

    # A null GraphicsStyle has no associated Category.
    if graphics_style is None:
        return None

    try:

        graphics_category = (
            graphics_style.GraphicsStyleCategory
        )

        if graphics_category is None:
            return None

        return id_value(
            graphics_category.Id
        )

    except:
        return None


# ======================================================================
# FUNCTION
# get_element_subcategory_id
#
# PURPOSE
# Determine the Object Style used by supported family geometry.
#
# SUPPORTED
# GenericForm
# ModelText
# ModelCurve
# SymbolicCurve
# CurveByPoints
# Other CurveElement classes through LineStyle
# ======================================================================

def get_element_subcategory_id(
    element
):

    # Ignore null database elements.
    if element is None:
        return None

    # GenericForm includes extrusions, blends, sweeps and similar forms.
    try:

        if isinstance(
            element,
            GenericForm
        ):

            subcategory = (
                element.Subcategory
            )

            if subcategory is not None:

                return id_value(
                    subcategory.Id
                )

            return None

    except:
        pass

    # ModelText supports a direct subcategory.
    try:

        if isinstance(
            element,
            ModelText
        ):

            subcategory = (
                element.Subcategory
            )

            if subcategory is not None:

                return id_value(
                    subcategory.Id
                )

            return None

    except:
        pass

    # ModelCurve uses an associated GraphicsStyle.
    try:

        if isinstance(
            element,
            ModelCurve
        ):

            return graphics_style_category_id(
                element.Subcategory
            )

    except:
        pass

    # SymbolicCurve uses an associated GraphicsStyle.
    try:

        if isinstance(
            element,
            SymbolicCurve
        ):

            return graphics_style_category_id(
                element.Subcategory
            )

    except:
        pass

    # CurveByPoints uses an associated GraphicsStyle.
    try:

        if isinstance(
            element,
            CurveByPoints
        ):

            return graphics_style_category_id(
                element.Subcategory
            )

    except:
        pass

    # Other CurveElement classes may expose the style through LineStyle.
    try:

        if isinstance(
            element,
            CurveElement
        ):

            return graphics_style_category_id(
                element.LineStyle
            )

    except:
        pass

    return None


# ======================================================================
# FUNCTION
# element_label
#
# PURPOSE
# Create a compact debug description for a Revit element.
# ======================================================================

def element_label(element):

    # Read the Revit class name.
    try:

        class_name = (
            element.GetType().Name
        )

    except:

        class_name = (
            type(element).__name__
        )

    # Read the Revit ElementId.
    try:

        element_id = id_value(
            element.Id
        )

    except:

        element_id = None

    return (
        str(class_name)
        + " Id "
        + str(element_id)
    )


# ======================================================================
# FUNCTION
# find_subcategory_users
#
# PURPOSE
# Find supported family elements that currently use a subcategory.
# ======================================================================

def find_subcategory_users(
    elements,
    subcategory_id
):

    users = []

    # Check every collected family element.
    for element in elements:

        try:

            current_id = (
                get_element_subcategory_id(
                    element
                )
            )

            if current_id == subcategory_id:

                users.append(
                    element
                )

        except:
            pass

    return users


# ======================================================================
# FUNCTION
# set_element_subcategory
#
# PURPOSE
# Reassign supported family geometry to a canonical Object Style.
# ======================================================================

def set_element_subcategory(
    element,
    source_subcategory_id,
    target_subcategory
):

    # Verify the element is still assigned to the source Object Style.
    current_id = get_element_subcategory_id(
        element
    )

    if current_id != source_subcategory_id:

        return (
            False,
            "Source style not detected"
        )

    # GenericForm expects a Category.
    try:

        if isinstance(
            element,
            GenericForm
        ):

            element.Subcategory = (
                target_subcategory
            )

            return (
                True,
                "GenericForm.Subcategory"
            )

    except Exception as ex:

        return (
            False,
            "GenericForm.Subcategory: "
            + str(ex)
        )

    # ModelText expects a Category.
    try:

        if isinstance(
            element,
            ModelText
        ):

            element.Subcategory = (
                target_subcategory
            )

            return (
                True,
                "ModelText.Subcategory"
            )

    except Exception as ex:

        return (
            False,
            "ModelText.Subcategory: "
            + str(ex)
        )

    # Curve-based elements require the target projection GraphicsStyle.
    try:

        target_graphics_style = (
            target_subcategory.GetGraphicsStyle(
                GraphicsStyleType.Projection
            )
        )

    except:

        target_graphics_style = None

    # Stop when the canonical projection GraphicsStyle was unavailable.
    if target_graphics_style is None:

        return (
            False,
            "Target GraphicsStyle unavailable"
        )

    # Remap a ModelCurve.
    try:

        if isinstance(
            element,
            ModelCurve
        ):

            element.Subcategory = (
                target_graphics_style
            )

            return (
                True,
                "ModelCurve.Subcategory"
            )

    except Exception as ex:

        return (
            False,
            "ModelCurve.Subcategory: "
            + str(ex)
        )

    # Remap a SymbolicCurve.
    try:

        if isinstance(
            element,
            SymbolicCurve
        ):

            element.Subcategory = (
                target_graphics_style
            )

            return (
                True,
                "SymbolicCurve.Subcategory"
            )

    except Exception as ex:

        return (
            False,
            "SymbolicCurve.Subcategory: "
            + str(ex)
        )

    # Remap CurveByPoints.
    try:

        if isinstance(
            element,
            CurveByPoints
        ):

            element.Subcategory = (
                target_graphics_style
            )

            return (
                True,
                "CurveByPoints.Subcategory"
            )

    except Exception as ex:

        return (
            False,
            "CurveByPoints.Subcategory: "
            + str(ex)
        )

    # Fall back to CurveElement.LineStyle for other curve classes.
    try:

        if isinstance(
            element,
            CurveElement
        ):

            element.LineStyle = (
                target_graphics_style
            )

            return (
                True,
                "CurveElement.LineStyle"
            )

    except Exception as ex:

        return (
            False,
            "CurveElement.LineStyle: "
            + str(ex)
        )

    return (
        False,
        "Unsupported family element type"
    )


# ======================================================================
# FUNCTION
# get_expected_delete_ids
#
# PURPOSE
# Identify database elements that normally belong to a subcategory.
#
# Deleting a Revit subcategory also deletes its associated GraphicsStyle
# elements. Those are expected dependencies and are safe to remove.
# ======================================================================

def get_expected_delete_ids(
    subcategory
):

    expected_ids = set()

    source_id = id_value(
        subcategory.Id
    )

    # Include the source category id.
    expected_ids.add(
        source_id
    )

    # Collect GraphicsStyle Elements using a valid collector filter.
    try:

        graphics_styles = (
            FilteredElementCollector(doc)
            .OfClass(GraphicsStyle)
            .ToElements()
        )

        # Find GraphicsStyles belonging to this subcategory.
        for graphics_style in graphics_styles:

            try:

                graphics_category = (
                    graphics_style
                    .GraphicsStyleCategory
                )

                if graphics_category is None:
                    continue

                if (
                    id_value(
                        graphics_category.Id
                    )
                    == source_id
                ):

                    expected_ids.add(
                        id_value(
                            graphics_style.Id
                        )
                    )

            except:
                continue

    except:
        pass

    # Explicitly include projection and cut GraphicsStyles.
    for graphics_type in [
        GraphicsStyleType.Projection,
        GraphicsStyleType.Cut
    ]:

        try:

            graphics_style = (
                subcategory.GetGraphicsStyle(
                    graphics_type
                )
            )

            if graphics_style is not None:

                expected_ids.add(
                    id_value(
                        graphics_style.Id
                    )
                )

        except:
            pass

    return expected_ids


# ======================================================================
# FUNCTION
# safe_purge_subcategory
#
# PURPOSE
# Delete one unused family Object Style safely.
#
# PROCESS
# 1. Verify supported geometry does not use the style.
# 2. Determine expected Category / GraphicsStyle dependencies.
# 3. Delete inside a SubTransaction.
# 4. Record every ElementId Revit would remove.
# 5. Roll the deletion back.
# 6. Regenerate the document.
# 7. Reacquire the Category directly by name.
# 8. Permanently delete only when no unexpected dependencies exist.
#
# IMPORTANT
# The source Category object becomes unsafe after the rollback probe.
# It is never reused after rollback.
# ======================================================================

def safe_purge_subcategory(
    parent_category,
    source_name,
    family_elements
):

    # Retrieve the current Category directly by its exact name.
    source_subcategory = (
        get_subcategory_exact(
            parent_category,
            source_name
        )
    )

    # The style may already have been deleted.
    if source_subcategory is None:

        return (
            True,
            "Already removed"
        )

    # Read the source id before any transaction changes.
    try:

        source_id = id_value(
            source_subcategory.Id
        )

    except Exception as ex:

        return (
            False,
            "Could not read source Category: "
            + str(ex)
        )

    # --------------------------------------------------------------
    # CHECK CURRENT GEOMETRY USE
    # --------------------------------------------------------------

    users = find_subcategory_users(
        family_elements,
        source_id
    )

    # Keep the style when supported family geometry still uses it.
    if users:

        sample = ", ".join(
            [
                element_label(item)
                for item in users[:5]
            ]
        )

        return (
            False,
            "Still used by "
            + str(len(users))
            + " element(s): "
            + sample
        )

    # --------------------------------------------------------------
    # RECORD EXPECTED DELETE DEPENDENCIES
    # --------------------------------------------------------------

    expected_ids = get_expected_delete_ids(
        source_subcategory
    )

    # --------------------------------------------------------------
    # DELETE PROBE
    # --------------------------------------------------------------

    probe = SubTransaction(doc)

    try:

        probe.Start()

        # Ask Revit what would be deleted with this subcategory.
        deleted_ids = list(
            doc.Delete(
                source_subcategory.Id
            )
        )

        deleted_values = set()

        # Convert returned ElementIds to normal integers.
        for deleted_id in deleted_ids:

            value = id_value(
                deleted_id
            )

            if value is not None:

                deleted_values.add(
                    value
                )

        # Restore the subcategory.
        probe.RollBack()

    except Exception as ex:

        # Roll back the probe when Revit raised an exception.
        try:
            probe.RollBack()

        except:
            pass

        return (
            False,
            "Delete probe failed: "
            + str(ex)
        )

    # --------------------------------------------------------------
    # REFRESH AFTER ROLLBACK
    #
    # The original Category wrapper is intentionally discarded.
    # --------------------------------------------------------------

    source_subcategory = None

    try:
        doc.Regenerate()

    except:
        pass

    # --------------------------------------------------------------
    # CHECK FOR UNSAFE DEPENDENCIES
    # --------------------------------------------------------------

    unexpected_ids = (
        deleted_values
        - expected_ids
    )

    # Do not purge when Revit would delete additional family elements.
    if unexpected_ids:

        return (
            False,
            "Delete would also remove element id(s): "
            + ", ".join(
                [
                    str(item)
                    for item in sorted(
                        unexpected_ids
                    )
                ]
            )
        )

    # --------------------------------------------------------------
    # REACQUIRE THE CATEGORY DIRECTLY BY NAME
    #
    # Do NOT enumerate parent_category.SubCategories here.
    # --------------------------------------------------------------

    current_subcategory = (
        get_subcategory_exact(
            parent_category,
            source_name
        )
    )

    # Stop when Revit did not recreate the Category after rollback.
    if current_subcategory is None:

        return (
            False,
            "Could not reacquire style after delete probe"
        )

    # --------------------------------------------------------------
    # PERMANENT DELETE
    # --------------------------------------------------------------

    purge_transaction = (
        SubTransaction(doc)
    )

    try:

        purge_transaction.Start()

        doc.Delete(
            current_subcategory.Id
        )

        purge_transaction.Commit()

    except Exception as ex:

        # Restore the family when permanent deletion failed.
        try:
            purge_transaction.RollBack()

        except:
            pass

        return (
            False,
            "Delete failed: "
            + str(ex)
        )

    # --------------------------------------------------------------
    # REFRESH AFTER ACTUAL DELETE
    #
    # This helps prevent CategoryNameMap from retaining stale wrappers.
    # --------------------------------------------------------------

    current_subcategory = None

    try:
        doc.Regenerate()

    except:
        pass

    return (
        True,
        "Purged"
    )


# ======================================================================
# MAIN PROCESS
# ======================================================================


# Parse the protected-style wildcard patterns.
keep_patterns = parse_keep_patterns(
    keep_input
)

result["KeepPatterns"] = (
    keep_patterns
)


# ======================================================================
# VALIDATION
# ======================================================================

# Stop when none of the three operations were selected.
if (
    not create_defaults
    and not remap_existing
    and not purge_unused
):

    result["Status"] = (
        "No action selected."
    )

    OUT = result


# Stop when Dynamo is not running inside the Revit Family Editor.
elif not doc.IsFamilyDocument:

    result["Status"] = "Error"

    result["Errors"].append(
        "Current document is not a Revit family document."
    )

    OUT = result


else:

    # Get the current Revit family.
    family = doc.OwnerFamily

    # Get the family's parent Object Style category.
    parent_category = (
        family.FamilyCategory
    )

    # Record the current family name.
    try:

        result["FamilyName"] = (
            family.Name
        )

    except:

        result["FamilyName"] = ""


    # Record the current family category.
    try:

        result["FamilyCategory"] = (
            parent_category.Name
        )

    except:

        result["FamilyCategory"] = ""


    # Stop when Revit did not provide a family category.
    if parent_category is None:

        result["Status"] = "Error"

        result["Errors"].append(
            "Family category could not be found."
        )

        OUT = result


    else:

        # Create a case-insensitive canonical-name set.
        canonical_names_upper = set(
            [
                name.upper()
                for (
                    name,
                    weight
                ) in CANONICAL_STYLES
            ]
        )

        # Store valid canonical Category objects used during remapping.
        canonical_categories = {}

        # Create one parent Revit transaction.
        transaction = Transaction(
            doc,
            "Family Canonical Object Style Setup"
        )

        try:

            transaction.Start()


            # ==========================================================
            # STEP 1
            # CREATE OR UPDATE CANONICAL OBJECT STYLES
            # ==========================================================

            for (
                canonical_name,
                weight_id
            ) in CANONICAL_STYLES:

                # Find an existing canonical Object Style.
                canonical_subcategory = (
                    get_subcategory_by_name(
                        parent_category,
                        canonical_name
                    )
                )

                # Create a missing canonical Object Style when IN[0] is true.
                if canonical_subcategory is None:

                    if create_defaults:

                        try:

                            canonical_subcategory = (
                                doc.Settings
                                .Categories
                                .NewSubcategory(
                                    parent_category,
                                    canonical_name
                                )
                            )

                            set_line_weights(
                                canonical_subcategory,
                                weight_id
                            )

                            result["Created"].append(
                                canonical_name
                                + " = "
                                + str(weight_id)
                            )

                        except Exception as ex:

                            result["Errors"].append(
                                canonical_name
                                + " create -> "
                                + str(ex)
                            )

                    # No canonical target exists when creation is disabled.
                    else:
                        continue

                # Normalize the line weight of an existing canonical style.
                elif create_defaults:

                    try:

                        set_line_weights(
                            canonical_subcategory,
                            weight_id
                        )

                        result["Updated"].append(
                            canonical_name
                            + " = "
                            + str(weight_id)
                        )

                    except Exception as ex:

                        result["Errors"].append(
                            canonical_name
                            + " update -> "
                            + str(ex)
                        )

                # Keep the valid Category as a remap target.
                if canonical_subcategory is not None:

                    canonical_categories[
                        canonical_name
                    ] = canonical_subcategory


            # Make newly created GraphicsStyle Elements available.
            doc.Regenerate()


            # ==========================================================
            # STEP 2
            # IDENTIFY STYLES ELIGIBLE FOR REMAPPING
            # ==========================================================

            remap_candidate_names = []

            # Take one stable snapshot before deletion occurs.
            initial_snapshot = (
                get_subcategory_snapshot(
                    parent_category
                )
            )

            # Evaluate each current Object Style.
            for (
                source_name,
                subcategory
            ) in initial_snapshot:

                source_upper = (
                    source_name
                    .strip()
                    .upper()
                )

                # Canonical styles are never remapped.
                if (
                    source_upper
                    in canonical_names_upper
                ):

                    result["Protected"].append(
                        source_name
                        + " -> canonical"
                    )

                    continue

                # Native Revit styles are never remapped.
                if is_built_in_category(
                    subcategory
                ):

                    result["Protected"].append(
                        source_name
                        + " -> built-in"
                    )

                    continue

                # User-defined IN[3] styles are never remapped.
                (
                    keep_style,
                    matched_pattern
                ) = matches_keep_pattern(
                    source_name,
                    keep_patterns
                )

                if keep_style:

                    result["Protected"].append(
                        source_name
                        + " -> keep "
                        + str(matched_pattern)
                    )

                    continue

                # Remaining custom styles are eligible for remapping.
                remap_candidate_names.append(
                    source_name
                )


            # Collect family elements once before remapping.
            family_elements = (
                collect_family_elements()
            )


            # ==========================================================
            # STEP 3
            # REMAP EXISTING OBJECT STYLES
            # ==========================================================

            if remap_existing:

                # Process each non-canonical custom Object Style.
                for source_name in remap_candidate_names:

                    # Retrieve the source directly by exact name.
                    source_subcategory = (
                        get_subcategory_exact(
                            parent_category,
                            source_name
                        )
                    )

                    # Skip a style that is no longer available.
                    if source_subcategory is None:

                        result[
                            "RemapSkipped"
                        ].append(
                            source_name
                            + " -> source not found"
                        )

                        continue

                    # Read the source Category id.
                    source_id = id_value(
                        source_subcategory.Id
                    )

                    # Determine the canonical target.
                    (
                        target_name,
                        match_score,
                        match_method
                    ) = get_canonical_target(
                        source_subcategory
                    )

                    # Report the proposed canonical mapping.
                    result["RemapPlan"].append(
                        source_name
                        + " -> "
                        + str(target_name)
                        + " by "
                        + str(match_method)
                        + " score="
                        + str(
                            round(
                                match_score,
                                3
                            )
                        )
                    )

                    # Get the canonical target Category.
                    target_subcategory = (
                        canonical_categories.get(
                            target_name
                        )
                    )

                    # The target must exist before geometry can be remapped.
                    if target_subcategory is None:

                        result[
                            "RemapSkipped"
                        ].append(
                            source_name
                            + " -> "
                            + str(target_name)
                            + " target missing; enable IN[0]"
                        )

                        continue

                    # Find family elements currently using the old style.
                    source_users = (
                        find_subcategory_users(
                            family_elements,
                            source_id
                        )
                    )

                    remapped_count = 0
                    failed_count = 0

                    # Reassign every supported family element.
                    for element in source_users:

                        (
                            success,
                            method
                        ) = set_element_subcategory(
                            element,
                            source_id,
                            target_subcategory
                        )

                        # Count successful assignments.
                        if success:

                            remapped_count += 1

                        # Report elements that could not be reassigned.
                        else:

                            failed_count += 1

                            result[
                                "RemapSkipped"
                            ].append(
                                source_name
                                + " -> "
                                + element_label(
                                    element
                                )
                                + " -> "
                                + str(method)
                            )

                    # Report the result for this source Object Style.
                    result["Remapped"].append(
                        source_name
                        + " -> "
                        + str(target_name)
                        + " elements="
                        + str(remapped_count)
                        + " failed="
                        + str(failed_count)
                    )

                # Update Revit after geometry assignments.
                doc.Regenerate()


            # ==========================================================
            # STEP 4
            # BUILD ONE STABLE PURGE SNAPSHOT
            #
            # IMPORTANT
            # Canonical styles ARE included here.
            #
            # This snapshot is created before the first deletion.
            # Category.SubCategories will NOT be enumerated again during
            # the purge loop.
            # ==========================================================

            purge_candidate_names = []

            # Only build the purge list when IN[2] is enabled.
            if purge_unused:

                purge_snapshot = (
                    get_subcategory_snapshot(
                        parent_category
                    )
                )

                # Evaluate every current custom Object Style.
                for (
                    source_name,
                    subcategory
                ) in purge_snapshot:

                    # Native Revit Object Styles are always retained.
                    if is_built_in_category(
                        subcategory
                    ):

                        result[
                            "PurgeProtected"
                        ].append(
                            source_name
                            + " -> built-in"
                        )

                        continue

                    # Check the user-defined protection patterns.
                    (
                        keep_style,
                        matched_pattern
                    ) = matches_keep_pattern(
                        source_name,
                        keep_patterns
                    )

                    # Protected patterns are retained even when unused.
                    if keep_style:

                        result[
                            "PurgeProtected"
                        ].append(
                            source_name
                            + " -> keep "
                            + str(matched_pattern)
                        )

                        continue

                    # Every other custom Object Style is tested for purge.
                    #
                    # This intentionally includes unused canonical styles.
                    purge_candidate_names.append(
                        source_name
                    )


            # Drop the snapshot's Category wrappers before deleting.
            initial_snapshot = None

            try:
                purge_snapshot = None

            except:
                pass


            # ==========================================================
            # STEP 5
            # PURGE ALL UNUSED CUSTOM OBJECT STYLES
            # ==========================================================

            if purge_unused:

                # Refresh family elements after remapping.
                family_elements = (
                    collect_family_elements()
                )

                # Process the stable name list.
                for source_name in purge_candidate_names:

                    # Safely test and delete this Object Style.
                    (
                        purged,
                        message
                    ) = safe_purge_subcategory(
                        parent_category,
                        source_name,
                        family_elements
                    )

                    # Report successful deletion.
                    if purged:

                        result["Purged"].append(
                            source_name
                        )

                    # Report styles that remain in use or have dependencies.
                    else:

                        result[
                            "PurgeSkipped"
                        ].append(
                            source_name
                            + " -> "
                            + str(message)
                        )


            # ==========================================================
            # COMPLETE
            # ==========================================================

            transaction.Commit()

            result["Status"] = (
                "Completed"
            )


        except Exception as ex:

            # Roll back the complete operation after an unexpected error.
            try:

                transaction.RollBack()

            except:
                pass

            result["Status"] = "Error"

            result["Errors"].append(
                str(ex)
            )


        OUT = result
