# ----------------------------------------------------------------------
# Shared Parameter Binding (RA + GPT + Dynamo Python 3, Revit 2025)
# Inputs:
#   IN[0] = param_name
#   IN[1] = category list
# Output:
#   OUT = result dictionary (never throws)
# ----------------------------------------------------------------------

import clr
import Autodesk.Revit.DB as DB

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System import Enum

doc = DocumentManager.Instance.CurrentDBDocument
app = doc.Application

OUT = None
stop = False    # global guard flag

# ----------------------------------------------------------------------
# INPUT VALIDATION
# ----------------------------------------------------------------------
param_name = IN[0]
category_keys = IN[1]

if not param_name:
    OUT = {"Error": "ParamName is missing."}
    stop = True

if not stop and (not category_keys or len(category_keys) == 0):
    OUT = {"Error": "Category list is empty."}
    stop = True

# ----------------------------------------------------------------------
# CATEGORY MAPS
# ----------------------------------------------------------------------
CATEGORY_MAP = {
    "Walls": DB.BuiltInCategory.OST_Walls,
    "Windows": DB.BuiltInCategory.OST_Windows,
    "Doors": DB.BuiltInCategory.OST_Doors,
    "Floors": DB.BuiltInCategory.OST_Floors,
    "Roofs": DB.BuiltInCategory.OST_Roofs,
    "Ceilings": DB.BuiltInCategory.OST_Ceilings,
    "CurtainPanels": DB.BuiltInCategory.OST_CurtainWallPanels,
    "CurtainMulls": DB.BuiltInCategory.OST_CurtainWallMullions,
    "GenericModels": DB.BuiltInCategory.OST_GenericModel
}

EXPANSION = {
    "CurtainWalls": ["CurtainPanels", "CurtainMulls"]
}

# ----------------------------------------------------------------------
# RESOLVE CATEGORIES
# ----------------------------------------------------------------------
if not stop:
    resolved_cats = []
    unknown = []

    for key in category_keys:
        if key in EXPANSION:
            for sub in EXPANSION[key]:
                bic = CATEGORY_MAP.get(sub)
                if bic:
                    resolved_cats.append(doc.Settings.Categories.get_Item(bic))
                else:
                    unknown.append(sub)
            continue

        bic = CATEGORY_MAP.get(key)
        if not bic:
            unknown.append(key)
        else:
            resolved_cats.append(doc.Settings.Categories.get_Item(bic))

    if unknown:
        OUT = {"Error": "Unknown category key(s).", "Unknown": unknown}
        stop = True

# ----------------------------------------------------------------------
# FIND SHARED PARAMETER DEFINITION (Bulletproof â€“ all groups, all params)
# ----------------------------------------------------------------------
if not stop:
    sp_file = app.OpenSharedParameterFile()
    if not sp_file:
        OUT = {"Error": "No shared parameter file assigned in Revit."}
        stop = True

if not stop:
    # Flatten all definitions from all groups
    all_defs = []
    for g in sp_file.Groups:
        for d in g.Definitions:
            all_defs.append((g, d))

    # Try to find by Name (exact match)
    definition = None
    for g, d in all_defs:
        if d.Name.strip() == param_name.strip():
            definition = d
            break

# ----------------------------------------------------------------------
# CHECK EXISTING BINDING (correct for CPython + Revit 2025+)
# ----------------------------------------------------------------------
if not stop:
    bindings = doc.ParameterBindings

    # search using forward iterator (CPython safe)
    existing = None
    it = bindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        if it.Key == definition:
            existing = it.Value
            break

    if existing:
        OUT = {
            "Status": "AlreadyBound",
            "Message": "Parameter already bound.",
            "Categories": category_keys
        }
        stop = True


# ----------------------------------------------------------------------
# BIND PARAMETER (CPython-safe; no explicit group)
# ----------------------------------------------------------------------
if not stop:
    catset = app.Create.NewCategorySet()
    for c in resolved_cats:
        catset.Insert(c)

    binding = app.Create.NewInstanceBinding(catset)

    TransactionManager.Instance.EnsureInTransaction(doc)
    ok = bindings.Insert(definition, binding)  # NO parameter group passed
    TransactionManager.Instance.TransactionTaskDone()

    if not ok:
        OUT = {"Error": "Revit API failed to bind parameter."}
        stop = True

# ----------------------------------------------------------------------
# SUCCESS
# ----------------------------------------------------------------------
if not stop:
    OUT = {
        "Status": "Success",
        "BoundParameter": param_name,
        "BoundCategories": category_keys
    }
