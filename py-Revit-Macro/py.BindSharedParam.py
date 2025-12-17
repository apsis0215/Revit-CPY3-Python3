# ----------------------------------------------------------------------
# Py.Bind.Params.py  v01.20
# Revit 2025+ (ForgeTypeId / GroupTypeId), Dynamo CPython3
#
# IN[0] = param_name (string, deterministic shared param name)
# IN[1] = category_keys (list of simple keys: "Walls", "Floors", ...)
# IN[2] = bind_as_type (bool; False = instance, True = type)
# IN[3] = group_name (Revit "Group parameter under" label, e.g. "Other")
#
# Behavior:
#   - If not bound: bind with given categories, instance/type, and group.
#   - If already bound: rebind with given categories, instance/type,
#     and update "Group parameter under" to IN[3] (or default "Other").
#   - Reads all definitions from the current shared parameter file.
#   - Uses ForgeTypeId-based group ids (Revit 2024+ API).
#
# OUT: dict with Status / Error / details. Never throws.
# ----------------------------------------------------------------------

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")

import Autodesk.Revit.DB as DB
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument
app = doc.Application

OUT = None
stop = False

# ----------------------------------------------------------------------
# INPUTS
# ----------------------------------------------------------------------
param_name = IN[0]
category_keys = IN[1]
bind_as_type = IN[2] if len(IN) > 2 else False
group_name_in = IN[3] if len(IN) > 3 else None

# basic validation
if not param_name or not isinstance(param_name, str):
    OUT = {"Error": "ParamName is missing or invalid."}
    stop = True

if not stop and (not category_keys or not isinstance(category_keys, list)):
    OUT = {"Error": "Category list is empty or invalid."}
    stop = True

# ----------------------------------------------------------------------
# CATEGORY MAPS (expandable)
# ----------------------------------------------------------------------
CATEGORY_MAP = {
    "Walls":        DB.BuiltInCategory.OST_Walls,
    "Windows":      DB.BuiltInCategory.OST_Windows,
    "Doors":        DB.BuiltInCategory.OST_Doors,
    "Floors":       DB.BuiltInCategory.OST_Floors,
    "Roofs":        DB.BuiltInCategory.OST_Roofs,
    "Ceilings":     DB.BuiltInCategory.OST_Ceilings,
    "CurtainPanels":DB.BuiltInCategory.OST_CurtainWallPanels,
    "CurtainMulls": DB.BuiltInCategory.OST_CurtainWallMullions,
    "GenericModels":DB.BuiltInCategory.OST_GenericModel
}

EXPANSION = {
    "CurtainWalls": ["CurtainPanels", "CurtainMulls"]
}

# ----------------------------------------------------------------------
# RESOLVE CATEGORIES FROM KEYS
# ----------------------------------------------------------------------
resolved_cats = []
unknown_keys = []

if not stop:
    cats = doc.Settings.Categories
    for key in category_keys:
        if key in EXPANSION:
            for sub in EXPANSION[key]:
                bic = CATEGORY_MAP.get(sub)
                if bic:
                    resolved_cats.append(cats.get_Item(bic))
                else:
                    unknown_keys.append(sub)
            continue

        bic = CATEGORY_MAP.get(key)
        if bic:
            resolved_cats.append(cats.get_Item(bic))
        else:
            unknown_keys.append(key)

    if unknown_keys:
        OUT = {
            "Error": "Unknown category key(s).",
            "Unknown": unknown_keys
        }
        stop = True

    if not resolved_cats and not stop:
        OUT = {"Error": "No valid categories resolved from input keys."}
        stop = True

# ----------------------------------------------------------------------
# FIND SHARED PARAMETER DEFINITION (scan all groups)
# ----------------------------------------------------------------------
sp_file = None
definition_from_sp = None

if not stop:
    sp_file = app.OpenSharedParameterFile()
    if not sp_file:
        OUT = {"Error": "No shared parameter file assigned in Revit."}
        stop = True

if not stop:
    all_defs = []
    for g in sp_file.Groups:
        for d in g.Definitions:
            all_defs.append((g, d))

    for g, d in all_defs:
        try:
            if d.Name.strip() == param_name.strip():
                definition_from_sp = d
                break
        except:
            pass

    if not definition_from_sp:
        OUT = {
            "Error": "Parameter not found in shared parameter file.",
            "ParamName": param_name,
            "AvailableDefinitions": [d.Name for _, d in all_defs]
        }
        stop = True

# ----------------------------------------------------------------------
# BUILD GROUP MAP (Group parameter under -> ForgeTypeId)
#   Uses ParameterUtils.GetAllBuiltInGroups + LabelUtils.GetLabelForGroup
#   Works in Revit 2024+ with GroupTypeId/ForgeTypeId.
# ----------------------------------------------------------------------
group_ids = None
GROUP_MAP = {}
desired_group_id = None

if not stop:
    try:
        group_ids = list(DB.ParameterUtils.GetAllBuiltInGroups())
    except Exception as e:
        OUT = {"Error": "Failed to get built-in parameter groups.",
               "Exception": str(e)}
        stop = True

if not stop:
    for gid in group_ids:
        try:
            label = DB.LabelUtils.GetLabelForGroup(gid)
        except:
            label = None

        if label and label not in GROUP_MAP:
            GROUP_MAP[label] = gid

    # default group name when IN[3] is None or empty
    DEFAULT_GROUP_NAME = "Other"
    if group_name_in and isinstance(group_name_in, str) and group_name_in.strip():
        requested_name = group_name_in.strip()
    else:
        requested_name = DEFAULT_GROUP_NAME

    # try exact match, else fall back to default, else first id
    if requested_name in GROUP_MAP:
        desired_group_id = GROUP_MAP[requested_name]
    elif DEFAULT_GROUP_NAME in GROUP_MAP:
        desired_group_id = GROUP_MAP[DEFAULT_GROUP_NAME]
    else:
        # last-resort fallback
        desired_group_id = group_ids[0] if group_ids else DB.ForgeTypeId()

# ----------------------------------------------------------------------
# CHECK EXISTING BINDING (by parameter name)
#   Note: in Revit 2025+ BindingMap keys are Definitions in doc.
# ----------------------------------------------------------------------
bindings = None
existing_def = None
existing_binding = None

if not stop:
    bindings = doc.ParameterBindings
    it = bindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        try:
            def_in_doc = it.Key
            if def_in_doc and def_in_doc.Name == param_name:
                existing_def = def_in_doc
                existing_binding = it.Value  # ElementBinding
                break
        except:
            pass

# ----------------------------------------------------------------------
# PREPARE CATEGORY SET AND BINDING (Instance vs Type)
# ----------------------------------------------------------------------
catset = None
binding_to_use = None

if not stop:
    catset = app.Create.NewCategorySet()
    for c in resolved_cats:
        catset.Insert(c)

    if bind_as_type:
        binding_to_use = app.Create.NewTypeBinding(catset)
        binding_kind = "Type"
    else:
        binding_to_use = app.Create.NewInstanceBinding(catset)
        binding_kind = "Instance"

# ----------------------------------------------------------------------
# TRANSACTION: INSERT / REINSERT WITH GROUP (ForgeTypeId)
#   - If not bound -> Insert(def_from_sp, binding, desired_group_id)
#   - If already bound -> ReInsert(existing_def, binding, desired_group_id)
#   This enforces:
#       - categories from IN[1]
#       - instance/type from IN[2]
#       - group parameter under from IN[3] (or default "Other")
# ----------------------------------------------------------------------
if not stop:
    TransactionManager.Instance.EnsureInTransaction(doc)

    try:
        if existing_def is None:
            # brand new binding from shared parameter file definition
            ok = bindings.Insert(definition_from_sp, binding_to_use, desired_group_id)
            status = "Inserted" if ok else "InsertFailed"
            moved_group = False
            previous_group_label = None
        else:
            # existing definition in document: overwrite binding and group
            # This will move group, update categories, and toggle instance/type.
            ok = bindings.ReInsert(existing_def, binding_to_use, desired_group_id)
            status = "ReInserted" if ok else "ReInsertFailed"

            # Try to get previous group label from the SP definition
            # (purely informational; may not match original doc state)
            prev_label = None
            try:
                prev_gid = definition_from_sp.GetGroupTypeId()
                prev_label = DB.LabelUtils.GetLabelForGroup(prev_gid)
            except:
                prev_label = None

            moved_group = True
            previous_group_label = prev_label

    except Exception as e:
        TransactionManager.Instance.TransactionTaskDone()
        OUT = {
            "Error": "Exception during Insert/ReInsert binding.",
            "Exception": str(e)
        }
        stop = True
    else:
        TransactionManager.Instance.TransactionTaskDone()

# ----------------------------------------------------------------------
# OUTPUT
# ----------------------------------------------------------------------
if not stop:
    # label for the group we actually requested
    try:
        group_label = DB.LabelUtils.GetLabelForGroup(desired_group_id)
    except:
        group_label = str(desired_group_id)

    OUT = {
        "Status": status,
        "ParamName": param_name,
        "BindingKind": binding_kind,
        "Categories": category_keys,
        "GroupParameterUnder": group_label,
        "GroupChangedThisRun": bool(existing_def is not None),
        "PreviousGroupLabel_HINT": previous_group_label
    }
    
    
##for gid in ParameterUtils.GetAllBuiltInGroups():
##   print(DB.LabelUtils.GetLabelForGroup(gid))
