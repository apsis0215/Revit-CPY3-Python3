# [py.RevParams-BindToSheets.py]
# V00-03-2026-01-31t1205p
# encoding: utf-8
# Purpose and IO:
#   Binds a provided list of Shared Parameter DEFINITIONS (by name) to OST_Sheets as INSTANCE parameters.
#   Accepts packet from EITHER:
#     - py.RevParams-WriteSharedParamFile.py (LIST-style)
#     - py.RevParams-PurgeLikely.py (DICT-style passthrough)
#
#   IMPORTANT:
#     - This node DOES NOT stamp values.
#     - This node PASSES THROUGH ParamNames + RevIdToParam + SharedParamFilePath so the next node can stamp.
#
#   RELIABILITY UPDATE:
#     - After freeze/thaw, Revit can "no-op" Insert/ReInsert if an existing bound Definition (same Name)
#       is stale or mismatched. We now fallback to:
#         (1) find bound Definition by NAME
#         (2) bm.Remove(oldDef)
#         (3) Insert/ReInsert using ext_def from shared param file
#
# Inputs:
#   IN[0]=UpstreamOut (dict/list)
#   IN[1]=ParamGroupAssignmentOverride (string or bool) OPTIONAL
#
# Outputs:
#   OUT=dict packet:
#     SharedParamFilePath, SharedParamGroupName, ParamGroupAssignment, RevPrefix,
#     ParamNames, RevIdToParam,
#     Report, Debug, Notes

import clr
import os
from datetime import datetime

#####################################
## 0000_Revit-Imports-And-Context()
#####################################
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    BuiltInCategory,
    Category,
    ElementId,
)

try:
    from Autodesk.Revit.DB import GroupTypeId
except:
    GroupTypeId = None

try:
    from Autodesk.Revit.DB import BuiltInParameterGroup
except:
    BuiltInParameterGroup = None

doc = DocumentManager.Instance.CurrentDBDocument
app = doc.Application

#####################################
## 0001_Read-Inputs()
#####################################
upstream_out = IN[0] if IN and len(IN) > 0 else None
group_override = IN[1] if IN and len(IN) > 1 and IN[1] is not None else None

#####################################
## 0100_Utilities()
#####################################
def safe_str(x):
    """Comment: defensive string conversion for Dynamo/Revit mixed types."""
    try:
        return "" if x is None else str(x)
    except:
        return ""

def _unwrap_singleton_list(obj):
    """Comment: unwrap one level if Dynamo wraps as [ [packet] ]."""
    try:
        if isinstance(obj, (list, tuple)) and len(obj) == 1:
            return obj[0]
    except:
        pass
    return obj

def _norm_group_name(name):
    """Comment: normalize group name input for mapping."""
    n = safe_str(name).strip().lower()
    n = n.replace("_", " ").replace("-", " ")
    return " ".join(n.split())

def resolve_param_group_token(group_input_value):
    """
    Comment: map friendly group string (or legacy bool) to a group token.
    Returns (token, resolved_label, normalized_name).
    """
    if isinstance(group_input_value, bool):
        norm = "identity data" if bool(group_input_value) else "other"
    else:
        norm = _norm_group_name(group_input_value) or "text"

    friendly_to_group_typeid = {
        "identity data": "IdentityData",
        "identity": "IdentityData",
        "text": "Text",
        "data": "Data",
        "other": "Other",
        "constraints": "Constraints",
        "graphics": "Graphics",
        "phasing": "Phasing",
        "materials": "Materials",
        "general": "General",
    }

    friendly_to_bipg = {
        "identity data": "PG_IDENTITY_DATA",
        "identity": "PG_IDENTITY_DATA",
        "text": "PG_TEXT",
        "data": "PG_DATA",
        "other": "PG_OTHER",
        "constraints": "PG_CONSTRAINTS",
        "graphics": "PG_GRAPHICS",
        "phasing": "PG_PHASING",
        "materials": "PG_MATERIALS",
        "general": "PG_GENERAL",
    }

    if GroupTypeId is not None:
        member = friendly_to_group_typeid.get(norm)
        if member and hasattr(GroupTypeId, member):
            return getattr(GroupTypeId, member), member, norm

    if BuiltInParameterGroup is not None:
        member = friendly_to_bipg.get(norm)
        if member and hasattr(BuiltInParameterGroup, member):
            return getattr(BuiltInParameterGroup, member), member, norm

    return None, "UNRESOLVED", norm

def extract_bind_packet(obj):
    """
    Comment:
      Supports BOTH:
        (A) dict packet with SharedParamFilePath + ParamNames + ParamGroupAssignment
        (B) writer list packet:
            [0]=SharedParamFilePath (string)
            [1]=ParamNames (list)
            [2]=RevIdToParam (dict)
            [3]=Report (dict)
    Returns:
      sp_path, param_names, rev_id_to_param, group_assignment, sp_group_name, rev_prefix
    """
    obj = _unwrap_singleton_list(obj)

    sp_path = ""
    param_names = []
    rev_id_to_param = {}
    group_assignment = "Text"
    sp_group_name = "DynamoProjectLocal"
    rev_prefix = ""

    if isinstance(obj, dict):
        sp_path = safe_str(obj.get("SharedParamFilePath") or obj.get("sharedParamFile") or obj.get("FilePath"))
        param_names = obj.get("ParamNames") or []
        rev_id_to_param = obj.get("RevIdToParam") or {}
        group_assignment = (
            obj.get("ParamGroupAssignment")
            or obj.get("ParamGroupAssignment_Input")
            or obj.get("ParamGroupName")
            or group_assignment
        )
        sp_group_name = safe_str(obj.get("SharedParamGroupName") or obj.get("GroupNameInFile") or obj.get("SharedParamGroup") or sp_group_name)
        rev_prefix = safe_str(obj.get("RevPrefix") or obj.get("revPrefix") or "")

    elif isinstance(obj, (list, tuple)):
        if len(obj) >= 1 and isinstance(obj[0], str) and obj[0].lower().endswith(".txt"):
            sp_path = safe_str(obj[0])

        if len(obj) >= 2 and isinstance(obj[1], list):
            param_names = obj[1]

        if len(obj) >= 3 and isinstance(obj[2], dict):
            rev_id_to_param = obj[2]

        if len(obj) >= 4 and isinstance(obj[3], dict):
            rep = obj[3]
            sp_path = sp_path or safe_str(rep.get("SharedParamFilePath") or "")
            rev_prefix = safe_str(rep.get("RevPrefix") or rep.get("RevPrefix_Stream") or rev_prefix)
            group_assignment = (
                rep.get("ParamGroupAssignment_Input")
                or rep.get("ParamGroupAssignment")
                or rep.get("ParamGroupName")
                or group_assignment
            )
            sp_group_name = safe_str(rep.get("GroupNameInFile") or rep.get("SharedParamGroupName") or sp_group_name)

    # normalize
    try:
        param_names = [safe_str(x) for x in param_names if x is not None and safe_str(x).strip()]
    except:
        param_names = []

    # normalize rev map keys to strings for Dynamo safety
    rev_map_out = {}
    try:
        for k, v in (rev_id_to_param or {}).items():
            try:
                rev_map_out[str(int(k))] = safe_str(v)
            except:
                rev_map_out[safe_str(k)] = safe_str(v)
    except:
        rev_map_out = {}

    return safe_str(sp_path), param_names, rev_map_out, group_assignment, (safe_str(sp_group_name) or "DynamoProjectLocal"), safe_str(rev_prefix)

#####################################
## 0200_Bind-Helpers()
#####################################
def open_shared_param_file_force(app_, sp_path, notes_list):
    """
    Comment:
      Force-open the shared parameter file even after freeze/thaw.
      Clearing SharedParametersFilename first helps flush stale file handles.
    """
    old_sp = app_.SharedParametersFilename
    sp_file = None
    try:
        try:
            app_.SharedParametersFilename = ""
        except:
            pass
        app_.SharedParametersFilename = sp_path
        sp_file = app_.OpenSharedParameterFile()
    finally:
        try:
            app_.SharedParametersFilename = old_sp
        except:
            notes_list.append("Warning: failed to restore SharedParametersFilename.")
    return sp_file

def find_bound_definition_by_name(doc_, target_name):
    """
    Comment:
      Search BindingMap for a Definition whose Name == target_name.
      Returns the Definition object or None.
    """
    try:
        bm = doc_.ParameterBindings
        it = bm.ForwardIterator()
        it.Reset()
        while it.MoveNext():
            try:
                d = it.Key
                if d and safe_str(d.Name) == target_name:
                    return d
            except:
                pass
    except:
        pass
    return None

def bind_param_to_sheets_robust(doc_, app_, ext_def, group_token, pname, debug_counts, fail_list):
    """
    Comment:
      Robust binder:
        1) Insert
        2) ReInsert
        3) Remove old def by name, then Insert
        4) Remove old def by name, then ReInsert
    """
    cats = app_.Create.NewCategorySet()
    sheets_cat = Category.GetCategory(doc_, BuiltInCategory.OST_Sheets)
    cats.Insert(sheets_cat)
    binding = app_.Create.NewInstanceBinding(cats)
    bm = doc_.ParameterBindings

    # 1) Insert
    try:
        if bm.Insert(ext_def, binding, group_token):
            debug_counts["InsertOK"] += 1
            return True
    except:
        pass

    # 2) ReInsert
    try:
        if bm.ReInsert(ext_def, binding, group_token):
            debug_counts["ReInsertOK"] += 1
            return True
    except:
        pass

    # 3/4) Remove old by name and retry
    old_def = find_bound_definition_by_name(doc_, pname)
    if old_def is not None:
        try:
            bm.Remove(old_def)
            debug_counts["RemovedOldByName"] += 1
        except:
            pass

        try:
            if bm.Insert(ext_def, binding, group_token):
                debug_counts["RemoveThenInsertOK"] += 1
                return True
        except:
            pass

        try:
            if bm.ReInsert(ext_def, binding, group_token):
                debug_counts["RemoveThenReInsertOK"] += 1
                return True
        except:
            pass

    fail_list.append({"Param": pname, "Reason": "Insert/ReInsert failed (even after RemoveByName fallback)."})
    return False

#####################################
## 0900_Main()
#####################################
notes = []
debug = {}
runtime_stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

sp_path, param_names, rev_id_to_param_out, group_assignment_stream, sp_group_name, rev_prefix = extract_bind_packet(upstream_out)
group_assignment = group_override if group_override is not None else group_assignment_stream
group_token, group_label, group_norm = resolve_param_group_token(group_assignment)

debug["Extracted"] = {
    "SharedParamFilePath": sp_path,
    "SharedParamGroupName": sp_group_name,
    "ParamNamesCount": len(param_names),
    "RevIdToParamCount": len(rev_id_to_param_out),
    "RevPrefix": rev_prefix,
    "ParamGroupAssignment_Stream": safe_str(group_assignment_stream),
    "ParamGroupAssignment_Final": safe_str(group_assignment),
}

# basic guards
if not sp_path or not os.path.exists(sp_path):
    OUT = {
        "SharedParamFilePath": sp_path,
        "SharedParamGroupName": sp_group_name,
        "ParamGroupAssignment": safe_str(group_assignment),
        "RevPrefix": rev_prefix,
        "ParamNames": param_names,
        "RevIdToParam": rev_id_to_param_out,
        "RuntimeStamp": runtime_stamp,
        "Report": {"error": "SharedParamFilePath missing or file does not exist.", "Path": safe_str(sp_path)},
        "Debug": debug,
        "Notes": notes,
    }

elif not param_names:
    OUT = {
        "SharedParamFilePath": sp_path,
        "SharedParamGroupName": sp_group_name,
        "ParamGroupAssignment": safe_str(group_assignment),
        "RevPrefix": rev_prefix,
        "ParamNames": param_names,
        "RevIdToParam": rev_id_to_param_out,
        "RuntimeStamp": runtime_stamp,
        "Report": {"error": "ParamNames missing/empty from stream."},
        "Debug": debug,
        "Notes": notes,
    }

elif group_token is None:
    OUT = {
        "SharedParamFilePath": sp_path,
        "SharedParamGroupName": sp_group_name,
        "ParamGroupAssignment": safe_str(group_assignment),
        "RevPrefix": rev_prefix,
        "ParamNames": param_names,
        "RevIdToParam": rev_id_to_param_out,
        "RuntimeStamp": runtime_stamp,
        "Report": {
            "error": "Could not resolve a valid parameter group token.",
            "ParamGroupResolved": group_label,
            "ParamGroupNormalized": group_norm,
        },
        "Debug": debug,
        "Notes": notes,
    }

else:
    failed = []
    bound_count = 0
    counts = {"InsertOK": 0, "ReInsertOK": 0, "RemovedOldByName": 0, "RemoveThenInsertOK": 0, "RemoveThenReInsertOK": 0}

    try:
        TransactionManager.Instance.EnsureInTransaction(doc)

        # Force open shared parameter file (flush stale handles after freeze/thaw)
        sp_file = open_shared_param_file_force(app, sp_path, notes)

        if sp_file is None:
            failed.append({"error": "Could not open shared parameter file.", "path": sp_path})
        else:
            try:
                sp_group = sp_file.Groups.get_Item(sp_group_name)
            except:
                sp_group = None

            if sp_group is None:
                failed.append({"error": "Shared parameter GROUP not found in file.", "group": sp_group_name})
            else:
                for pname in param_names:
                    pname_s = safe_str(pname)
                    try:
                        ext_def = sp_group.Definitions.get_Item(pname_s)
                    except:
                        ext_def = None

                    if ext_def is None:
                        failed.append({"Param": pname_s, "Reason": "Definition not found in shared parameter file group."})
                        continue

                    if bind_param_to_sheets_robust(doc, app, ext_def, group_token, pname_s, counts, failed):
                        bound_count += 1

        # Helps after freeze/thaw when bindings “exist” but UI/schedules don’t refresh
        try:
            doc.Regenerate()
        except:
            pass

        TransactionManager.Instance.TransactionTaskDone()

        debug["BindStrategyCounts"] = counts

        OUT = {
            "SharedParamFilePath": sp_path,
            "SharedParamGroupName": sp_group_name,
            "ParamGroupAssignment": safe_str(group_assignment),
            "RevPrefix": rev_prefix,
            "ParamNames": param_names,
            "RevIdToParam": rev_id_to_param_out,
            "RuntimeStamp": runtime_stamp,
            "Report": {
                "ParamGroupResolved": group_label,
                "ParamGroupNormalized": group_norm,
                "ParamNamesCount": len(param_names),
                "BoundCount": bound_count,
                "FailedCount": len(failed),
                "FailedSample": failed[:25],
            },
            "Debug": debug,
            "Notes": notes,
        }

    except Exception as ex:
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except:
            pass

        OUT = {
            "SharedParamFilePath": sp_path,
            "SharedParamGroupName": sp_group_name,
            "ParamGroupAssignment": safe_str(group_assignment),
            "RevPrefix": rev_prefix,
            "ParamNames": param_names,
            "RevIdToParam": rev_id_to_param_out,
            "RuntimeStamp": runtime_stamp,
            "Report": {"error": safe_str(ex)},
            "Debug": debug,
            "Notes": notes,
        }
