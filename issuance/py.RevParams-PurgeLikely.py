# [py.RevParams-PurgeLikely.py]
# V00-04-2026-01-31t0000p
# encoding: utf-8
# Purpose:
#   Purge ONLY what needs purging:
#     - remove bindings + delete ParameterElements when:
#         (A) name matches our rule-set AND
#         (B) GUID mismatches expected OR UserModifiable mismatches expected
#   Pass-through stream for downstream bind/stamp nodes.

import clr
import re
from datetime import datetime

#####################################
## 0000_Revit-Imports-And-Context()
#####################################
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    BuiltInCategory,
    ElementId,
    FilteredElementCollector,
    ParameterElement,
    SharedParameterElement,
    Transaction,
    TransactionGroup,
    ViewSheet,
)

doc = DocumentManager.Instance.CurrentDBDocument

#####################################
## 0001_Read-Inputs()
#####################################
write_out = IN[0] if IN and len(IN) > 0 else None

#####################################
## 0100_Utilities()
#####################################
def safe_str(x):
    try:
        return "" if x is None else str(x)
    except:
        return ""

def _unwrap_singleton_list(obj):
    try:
        if isinstance(obj, (list, tuple)) and len(obj) == 1:
            return obj[0]
    except:
        pass
    return obj

def _as_list(x):
    if x is None:
        return []
    try:
        return list(x)
    except:
        return []

#####################################
## 0110_Stream-Extraction
#####################################
def extract_stream_packet(obj):
    """
    Supports:
      - dict packet
      - writer list packet:
          [0]=sp_path, [1]=ParamNames, [2]=RevIdToParam, [3]=Report, [4]=ParamPacket, [5]=ParamNameToGuid
    """
    obj = _unwrap_singleton_list(obj)

    sp_path = ""
    param_names = []
    rev_id_to_param = {}
    rev_prefix = ""
    group_assignment = "Text"
    sp_group_name = "DynamoProjectLocal"
    make_non_user_mod = None
    param_packet = None
    param_name_to_guid = None

    if isinstance(obj, dict):
        sp_path = safe_str(obj.get("SharedParamFilePath") or obj.get("FilePath") or "")
        sp_group_name = safe_str(obj.get("SharedParamGroupName") or obj.get("GroupNameInFile") or sp_group_name)
        param_names = obj.get("ParamNames") or []
        rev_id_to_param = obj.get("RevIdToParam") or {}
        rev_prefix = safe_str(obj.get("RevPrefix") or obj.get("revPrefix") or "")
        group_assignment = obj.get("ParamGroupAssignment") or obj.get("ParamGroupAssignment_Input") or group_assignment

        # optional new fields
        make_non_user_mod = obj.get("MakeNonUserModifiable")
        param_packet = obj.get("ParamPacket")
        param_name_to_guid = obj.get("ParamNameToGuid")

        # sometimes stored in Report subdict
        rep = obj.get("Report")
        if isinstance(rep, dict):
            make_non_user_mod = rep.get("MakeNonUserModifiable", make_non_user_mod)

    elif isinstance(obj, (list, tuple)):
        if len(obj) >= 1 and isinstance(obj[0], str):
            sp_path = safe_str(obj[0])
        if len(obj) >= 2 and isinstance(obj[1], list):
            param_names = obj[1]
        if len(obj) >= 3 and isinstance(obj[2], dict):
            rev_id_to_param = obj[2]
        if len(obj) >= 4 and isinstance(obj[3], dict):
            rep = obj[3]
            rev_prefix = safe_str(rep.get("RevPrefix") or rep.get("RevPrefix_Stream") or "")
            group_assignment = rep.get("ParamGroupAssignment_Input") or rep.get("ParamGroupAssignment") or group_assignment
            sp_group_name = safe_str(rep.get("GroupNameInFile") or rep.get("SharedParamGroupName") or sp_group_name)
            make_non_user_mod = rep.get("MakeNonUserModifiable", make_non_user_mod)
            sp_path = sp_path or safe_str(rep.get("SharedParamFilePath") or "")

        if len(obj) >= 5 and isinstance(obj[4], list):
            param_packet = obj[4]
        if len(obj) >= 6 and isinstance(obj[5], dict):
            param_name_to_guid = obj[5]

    # normalize param names
    try:
        param_names = [safe_str(x) for x in param_names if x is not None and safe_str(x).strip()]
    except:
        param_names = []

    # normalize RevIdToParam passthrough keys to strings for Dynamo safety
    rev_map_out = {}
    try:
        for k, v in (rev_id_to_param or {}).items():
            try:
                rev_map_out[str(int(k))] = safe_str(v)
            except:
                rev_map_out[safe_str(k)] = safe_str(v)
    except:
        rev_map_out = {}

    return {
        "SharedParamFilePath": sp_path,
        "SharedParamGroupName": sp_group_name,
        "ParamNames": param_names,
        "RevIdToParam": rev_map_out,
        "RevPrefix": (rev_prefix or "REV").strip(),
        "ParamGroupAssignment": group_assignment,
        "MakeNonUserModifiable": bool(make_non_user_mod) if make_non_user_mod is not None else None,
        "ParamPacket": param_packet,
        "ParamNameToGuid": param_name_to_guid,
    }

#####################################
## 0200_Expected GUID map + expected UserModifiable
#####################################
def build_expected_guid_map(packet):
    # Prefer ParamNameToGuid, else ParamPacket, else empty
    name_to_guid = {}

    m = packet.get("ParamNameToGuid")
    if isinstance(m, dict) and m:
        for k, v in m.items():
            ks = safe_str(k).strip()
            vs = safe_str(v).strip().upper()
            if ks and vs:
                name_to_guid[ks] = vs
        return name_to_guid

    pp = packet.get("ParamPacket")
    if isinstance(pp, list):
        for row in pp:
            if not isinstance(row, dict):
                continue
            pname = safe_str(row.get("ParamName")).strip()
            guid = safe_str(row.get("ParamGuid")).strip().upper()
            if pname and guid:
                name_to_guid[pname] = guid

    return name_to_guid

def get_expected_user_modifiable(packet):
    # expected UserModifiable = NOT MakeNonUserModifiable
    mnm = packet.get("MakeNonUserModifiable")
    if mnm is None:
        return None  # unknown
    return (not bool(mnm))

#####################################
## 0300_Model Inspection helpers
#####################################
def get_current_usermod_from_any_sheet(pname):
    """
    Try to read Definition.UserModifiable from a real parameter instance on a sheet.
    Returns: True/False/None (None if not detectable or not present).
    """
    try:
        sh = FilteredElementCollector(doc).OfClass(ViewSheet).FirstElement()
        if sh is None:
            return None
    except:
        return None

    # Better: scan a few sheets until we find this parameter
    try:
        sheets = list(FilteredElementCollector(doc).OfClass(ViewSheet).ToElements())
    except:
        sheets = []

    for sh in sheets[:30]:
        try:
            p = sh.LookupParameter(pname)
        except:
            p = None
        if p is None:
            continue

        try:
            d = p.Definition
            # many versions have this:
            if hasattr(d, "UserModifiable"):
                return bool(d.UserModifiable)
        except:
            return None

    return None

def get_existing_sharedparam_element_by_name(pname):
    """
    Returns SharedParameterElement if found by Name, else None.
    """
    try:
        for pe in FilteredElementCollector(doc).OfClass(ParameterElement).ToElements():
            try:
                if safe_str(pe.Name) == pname:
                    # only shared parameters have GuidValue
                    if isinstance(pe, SharedParameterElement):
                        return pe
            except:
                pass
    except:
        pass
    return None

#####################################
## 0400_Matching rules for candidate names
#####################################
def build_candidate_matcher(rev_prefix, param_names):
    prefix = safe_str(rev_prefix).strip()
    prefix_no_dot = prefix[:-1] if prefix.endswith(".") else prefix
    param_name_set = set([safe_str(x) for x in (param_names or []) if safe_str(x)])
    rx_date8 = re.compile(r"\d{8}")

    rx_revword = None
    try:
        if prefix_no_dot:
            rx_revword = re.compile(r"^%s.*revision" % re.escape(prefix_no_dot), re.IGNORECASE)
    except:
        rx_revword = None

    def is_candidate(n):
        n = safe_str(n).strip()
        if not n:
            return False
        if n in param_name_set:
            return True
        if prefix and n.startswith(prefix) and rx_date8.search(n):
            return True
        if rx_revword is not None and rx_revword.search(n):
            return True
        return False

    return is_candidate

#####################################
## 0500_Purge operations
#####################################
def remove_bindings_for_names(doc_, names_set):
    removed = 0
    matched = []
    try:
        bm = doc_.ParameterBindings
        it = bm.ForwardIterator()
        it.Reset()

        defs_to_remove = []
        while it.MoveNext():
            try:
                d = it.Key
                if d and safe_str(d.Name) in names_set:
                    defs_to_remove.append(d)
                    if len(matched) < 30:
                        matched.append(safe_str(d.Name))
            except:
                pass

        for d in defs_to_remove:
            try:
                if bm.Remove(d):
                    removed += 1
            except:
                pass
    except:
        pass

    return removed, matched

def delete_param_elements_for_names(doc_, names_set):
    deleted = 0
    matched = []
    ids = []
    try:
        for pe in FilteredElementCollector(doc_).OfClass(ParameterElement).ToElements():
            try:
                n = safe_str(pe.Name)
                if n in names_set:
                    ids.append(pe.Id)
                    if len(matched) < 30:
                        matched.append(n)
            except:
                pass
    except:
        pass

    for eid in ids:
        try:
            doc_.Delete(eid)
            deleted += 1
        except:
            pass

    return deleted, matched

#####################################
## 0900_Main
#####################################
runtime_stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
packet = extract_stream_packet(write_out)

param_names = packet["ParamNames"]
rev_prefix = packet["RevPrefix"]

expected_guid_map = build_expected_guid_map(packet)
expected_user_mod = get_expected_user_modifiable(packet)  # True/False/None

# Decide which names MUST be purged
is_candidate = build_candidate_matcher(rev_prefix, param_names)

purge_names = set()
keep_names = set()
reasons = []

for pname in param_names:
    if not is_candidate(pname):
        continue

    exp_guid = safe_str(expected_guid_map.get(pname, "")).upper()
    spe = get_existing_sharedparam_element_by_name(pname)

    if spe is None:
        # doesn't exist -> nothing to purge
        keep_names.add(pname)
        continue

    # GUID check
    cur_guid = ""
    try:
        cur_guid = safe_str(spe.GuidValue).upper()
    except:
        cur_guid = ""

    guid_mismatch = (exp_guid and cur_guid and exp_guid != cur_guid)

    # UserModifiable check (best effort)
    cur_user_mod = get_current_usermod_from_any_sheet(pname)  # True/False/None
    usermod_mismatch = False
    if expected_user_mod is not None and cur_user_mod is not None:
        usermod_mismatch = (bool(expected_user_mod) != bool(cur_user_mod))

    # If we cannot detect current user-mod state, but user requested a state,
    # and the parameter exists, be conservative and purge when flipping matters:
    # We treat "expected_user_mod is not None and cur_user_mod is None" as "unknown".
    # If you want "always purge when unknown", keep this True:
    unknown_usermod_needs_recreate = (expected_user_mod is not None and cur_user_mod is None)

    if guid_mismatch or usermod_mismatch or unknown_usermod_needs_recreate:
        purge_names.add(pname)
        reasons.append({
            "Param": pname,
            "GuidExpected": exp_guid,
            "GuidCurrent": cur_guid,
            "GuidMismatch": guid_mismatch,
            "UserModExpected": expected_user_mod,
            "UserModCurrent": cur_user_mod,
            "UserModMismatch": usermod_mismatch,
            "UserModUnknownForced": unknown_usermod_needs_recreate,
        })
    else:
        keep_names.add(pname)

removed_bindings = 0
deleted_param_elements = 0
matched_binding_names = []
matched_param_element_names = []

tg = TransactionGroup(doc, "RevParams Purge (GUID/UserMod aware)")
try:
    tg.Start()

    t1 = Transaction(doc, "Purge Bindings (mismatched only)")
    t1.Start()
    removed_bindings, matched_binding_names = remove_bindings_for_names(doc, purge_names)
    t1.Commit()

    t2 = Transaction(doc, "Delete ParameterElements (mismatched only)")
    t2.Start()
    deleted_param_elements, matched_param_element_names = delete_param_elements_for_names(doc, purge_names)
    t2.Commit()

    tg.Assimilate()

    OUT = {
        # passthrough
        "SharedParamFilePath": packet["SharedParamFilePath"],
        "SharedParamGroupName": packet["SharedParamGroupName"],
        "ParamNames": param_names,
        "RevIdToParam": packet["RevIdToParam"],
        "RevPrefix": rev_prefix,
        "ParamGroupAssignment": packet["ParamGroupAssignment"],
        "MakeNonUserModifiable": packet["MakeNonUserModifiable"],
        "ParamNameToGuid": expected_guid_map,

        # purge report
        "RuntimeStamp": runtime_stamp,
        "PurgedParamNames": sorted(list(purge_names)),
        "KeptParamNames": sorted(list(keep_names)),
        "RemovedBindings": removed_bindings,
        "DeletedParameterElements": deleted_param_elements,
        "MatchedBindingNamesSample": matched_binding_names,
        "MatchedParamElementNamesSample": matched_param_element_names,
        "MismatchReasonsSample": reasons[:25],
        "Report": {
            "RuntimeStamp": runtime_stamp,
            "ExpectedUserModifiable": expected_user_mod,
            "ParamNamesCount": len(param_names),
            "PurgeCount": len(purge_names),
            "KeepCount": len(keep_names),
            "RemovedBindings": removed_bindings,
            "DeletedParameterElements": deleted_param_elements,
        },
        "Notes": [],
    }

except Exception as ex:
    try:
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()
    except:
        pass

    OUT = {
        "SharedParamFilePath": packet["SharedParamFilePath"],
        "SharedParamGroupName": packet["SharedParamGroupName"],
        "ParamNames": param_names,
        "RevIdToParam": packet["RevIdToParam"],
        "RevPrefix": rev_prefix,
        "ParamGroupAssignment": packet["ParamGroupAssignment"],
        "MakeNonUserModifiable": packet["MakeNonUserModifiable"],
        "ParamNameToGuid": expected_guid_map,
        "RuntimeStamp": runtime_stamp,
        "error": safe_str(ex),
    }
