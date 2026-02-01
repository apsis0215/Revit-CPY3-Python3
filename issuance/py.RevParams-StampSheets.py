# [py.RevParams-StampSheets.py]
# V00-02-2026-01-31t1525p
# encoding: utf-8

import clr
import re
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
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    Revision,
    ViewSheet,
)

doc = DocumentManager.Instance.CurrentDBDocument

#####################################
## 0001_Read-Inputs()
#####################################
packet_in = IN[0] if IN and len(IN) > 0 else None

true_symbol_raw = IN[1] if IN and len(IN) > 1 else None
only_add_sheets_with_revs = IN[2] if IN and len(IN) > 2 and IN[2] is not None else True
only_show_issued = IN[3] if IN and len(IN) > 3 and IN[3] is not None else True
clear_not_included = IN[4] if IN and len(IN) > 4 and IN[4] is not None else False

MRK = u"\u25CF"  # ●
try:
    TRUE_SYMBOL = MRK if true_symbol_raw is None else (str(true_symbol_raw) if str(true_symbol_raw).strip() else MRK)
except:
    TRUE_SYMBOL = MRK

#####################################
## 0100_Utilities()
#####################################
def safe_str(x):
    try:
        return "" if x is None else str(x)
    except:
        return ""

def _as_list(x):
    if x is None:
        return []
    try:
        return list(x)
    except:
        return []

def _unwrap_singleton_list(obj):
    try:
        if isinstance(obj, (list, tuple)) and len(obj) == 1:
            return obj[0]
    except:
        pass
    return obj

def _fail_loud(reason, hint=None, extract=None, errors=None):
    msg = "StampSheets input/operation validation failed\n"
    msg += "Reason={}\n".format(safe_str(reason))
    if hint:
        msg += "Hint={}\n".format(safe_str(hint))
    if extract:
        msg += "Extract={}\n".format(safe_str(extract))
    if errors:
        msg += "ErrorCount={}\n".format(len(errors))
        for e in errors[:20]:
            msg += "- {}\n".format(safe_str(e))
        if len(errors) > 20:
            msg += "- ... ({} more)\n".format(len(errors) - 20)
    raise Exception(msg)

#####################################
## 0120_Canonical-Name-Rebuild
#####################################
MAX_LEN_6BIT = int(128 / 6)  # 21

def to_yyyymmdd(date_str):
    s = safe_str(date_str).strip()
    if not s:
        return "00000000"

    m = re.match(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s*$", s)
    if m:
        y = m.group(1)
        mo = "{:02d}".format(int(m.group(2)))
        d = "{:02d}".format(int(m.group(3)))
        return "{}{}{}".format(y, mo, d)

    m = re.match(r"^\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$", s)
    if m:
        mo = "{:02d}".format(int(m.group(1)))
        d = "{:02d}".format(int(m.group(2)))
        y = m.group(3)
        return "{}{}{}".format(y, mo, d)

    digits = re.sub(r"\D+", "", s)
    if len(digits) >= 8:
        digits = digits[:8]
        if digits.startswith("19") or digits.startswith("20"):
            return digits
        mm = digits[0:2]
        dd = digits[2:4]
        yy = digits[4:8]
        if yy.startswith("19") or yy.startswith("20"):
            return "{}{}{}".format(yy, mm, dd)

    return "00000000"

def compress_desc_to_snippet(desc):
    s = safe_str(desc).upper()
    s = re.sub(r"[^A-Z0-9]+", "", s)
    return s or "X"

def build_canonical_param_name(prefix, yyyymmdd, desc, max_len=MAX_LEN_6BIT, desired_snip=10):
    pfx = safe_str(prefix)
    base = "{}{}".format(pfx, yyyymmdd)
    remaining = max_len - len(base)
    if remaining <= 0:
        return base[:max_len]
    snippet = compress_desc_to_snippet(desc)
    snip_len = min(desired_snip, remaining)
    return (base + snippet[:snip_len])[:max_len]

#####################################
## 0150_Packet-Extraction()
#####################################
def extract_stamp_packet(obj):
    obj = _unwrap_singleton_list(obj)

    sp_path = ""
    sp_group_name = ""
    group_assignment = ""
    rev_prefix = ""

    param_names = []
    rev_map_raw = {}

    if isinstance(obj, dict):
        sp_path = safe_str(obj.get("SharedParamFilePath") or obj.get("FilePath") or "")
        sp_group_name = safe_str(obj.get("SharedParamGroupName") or obj.get("GroupNameInFile") or "")
        group_assignment = safe_str(obj.get("ParamGroupAssignment") or obj.get("ParamGroupAssignment_Input") or "")
        rev_prefix = safe_str(obj.get("RevPrefix") or obj.get("revPrefix") or "")
        param_names = obj.get("ParamNames") or []
        rev_map_raw = obj.get("RevIdToParam") or {}

    elif isinstance(obj, (list, tuple)):
        if len(obj) >= 1 and isinstance(obj[0], str):
            sp_path = safe_str(obj[0])
        if len(obj) >= 2 and isinstance(obj[1], list):
            param_names = obj[1]
        if len(obj) >= 3 and isinstance(obj[2], dict):
            rev_map_raw = obj[2]
        if len(obj) >= 4 and isinstance(obj[3], dict):
            rep = obj[3]
            sp_path = sp_path or safe_str(rep.get("SharedParamFilePath") or "")
            sp_group_name = safe_str(rep.get("GroupNameInFile") or rep.get("SharedParamGroupName") or "")
            group_assignment = safe_str(rep.get("ParamGroupAssignment_Input") or rep.get("ParamGroupAssignment") or "")
            rev_prefix = safe_str(rep.get("RevPrefix") or rep.get("revPrefix") or "")

    try:
        param_names = [safe_str(x) for x in param_names if x is not None and safe_str(x).strip()]
    except:
        param_names = []

    rev_id_to_param = {}
    try:
        for k, v in (rev_map_raw or {}).items():
            try:
                rev_id_to_param[int(k)] = safe_str(v)
            except:
                pass
    except:
        rev_id_to_param = {}

    return sp_path, sp_group_name, group_assignment, rev_prefix, param_names, rev_id_to_param

def rebuild_rev_id_to_param_from_model(rev_prefix, param_names_set):
    rebuilt = {}
    revs = list(FilteredElementCollector(doc).OfClass(Revision).ToElements())
    for r in revs:
        try:
            rid = r.Id.IntegerValue
        except:
            continue
        try:
            rdate = safe_str(getattr(r, "RevisionDate", ""))
        except:
            rdate = ""
        try:
            rdesc = safe_str(getattr(r, "Description", ""))
        except:
            rdesc = ""
        yyyymmdd = to_yyyymmdd(rdate)
        pname = build_canonical_param_name(rev_prefix, yyyymmdd, rdesc)
        if pname in param_names_set:
            rebuilt[int(rid)] = pname
    return rebuilt

#####################################
## 0200_Revision-Inclusion-Detection()
#####################################
def get_revision_ids_from_clouds_in_view(doc_, view_id):
    ids = set()
    try:
        clouds = list(
            FilteredElementCollector(doc_, view_id)
            .OfCategory(BuiltInCategory.OST_RevisionClouds)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        for c in clouds:
            rid = getattr(c, "RevisionId", None)
            if rid and isinstance(rid, ElementId):
                ids.add(rid.IntegerValue)
    except:
        pass
    return ids

def get_additional_revision_ids(sheet):
    ids = set()
    try:
        for rid in _as_list(sheet.GetAdditionalRevisionIds()):
            try:
                ids.add(rid.IntegerValue)
            except:
                pass
    except:
        pass
    return ids

def get_all_revision_ids(sheet):
    ids = set()
    try:
        fn = getattr(sheet, "GetAllRevisionIds", None)
        if fn is not None:
            for rid in _as_list(sheet.GetAllRevisionIds()):
                try:
                    ids.add(rid.IntegerValue)
                except:
                    pass
    except:
        pass
    return ids

def revision_is_issued(rev_elem):
    try:
        p = rev_elem.get_Parameter(BuiltInParameter.REVISION_ISSUED)
        if p:
            return int(p.AsInteger()) == 1
    except:
        pass
    try:
        return bool(getattr(rev_elem, "Issued", False))
    except:
        return False

def get_included_revision_ids(doc_, sheet, only_issued):
    addl = get_additional_revision_ids(sheet)
    all_ids = get_all_revision_ids(sheet)
    clouds_sheet = get_revision_ids_from_clouds_in_view(doc_, sheet.Id)

    clouds_views = set()
    try:
        for vid in _as_list(sheet.GetAllPlacedViews()):
            clouds_views.update(get_revision_ids_from_clouds_in_view(doc_, vid))
    except:
        pass

    included = set()
    included.update(addl)
    included.update(all_ids)
    included.update(clouds_sheet)
    included.update(clouds_views)

    if not only_issued:
        return included, addl, clouds_sheet, clouds_views, all_ids

    issued_only = set()
    for rid_int in included:
        try:
            rev_elem = doc_.GetElement(ElementId(int(rid_int)))
        except:
            rev_elem = None
        if rev_elem is None:
            continue
        if revision_is_issued(rev_elem):
            issued_only.add(int(rid_int))

    return issued_only, addl, clouds_sheet, clouds_views, all_ids

#####################################
## 0300_Param-Write()
#####################################
def get_sheet_param_by_name(sheet, pname):
    try:
        return sheet.LookupParameter(pname)
    except:
        return None

def set_string_param(p, target):
    try:
        if getattr(p, "IsReadOnly", False):
            return False, True, "Parameter IsReadOnly=True"
    except:
        pass

    try:
        cur = p.AsString()
        cur = "" if cur is None else str(cur)
    except:
        cur = ""

    if cur == target:
        return False, False, None

    try:
        p.Set(target)
        return True, False, None
    except Exception as ex1:
        try:
            p.SetValueString(target)
            return True, False, None
        except Exception as ex2:
            return False, True, "Set failed: {}; SetValueString failed: {}".format(ex1, ex2)

#####################################
## 0900_Main()
#####################################
notes = []
debug = {}
report = {}

runtime_stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

sp_path, sp_group_name, group_assignment, rev_prefix, param_names, rev_id_to_param = extract_stamp_packet(packet_in)

extract_dbg = {
    "RuntimeStamp": runtime_stamp,
    "TopType": type(_unwrap_singleton_list(packet_in)).__name__,
    "SharedParamFilePath": sp_path,
    "SharedParamGroupName": sp_group_name,
    "ParamGroupAssignment": group_assignment,
    "RevPrefix": rev_prefix,
    "ParamNamesCount": len(param_names),
    "RevIdToParamCount": len(rev_id_to_param),
}

rev_prefix_used = (rev_prefix or "REV").strip()
param_names_set = set(param_names)

rebuilt = False
if len(rev_id_to_param) == 0 and param_names:
    rev_id_to_param = rebuild_rev_id_to_param_from_model(rev_prefix_used, param_names_set)
    rebuilt = True
    extract_dbg["RevIdToParamRebuiltCount"] = len(rev_id_to_param)

report.update({
    "RuntimeStamp": runtime_stamp,
    "SharedParamFilePath": sp_path,
    "SharedParamGroupName": sp_group_name,
    "ParamGroupAssignment": group_assignment,
    "RevPrefix": rev_prefix_used,
    "ParamNamesCount": len(param_names),
    "RevIdToParamCount": len(rev_id_to_param),
    "RevIdToParamRebuilt": bool(rebuilt),
    "TrueSymbol": TRUE_SYMBOL,
    "OnlyAddSheetsWithRevisions": bool(only_add_sheets_with_revs),
    "OnlyShowIssuedRevisions": bool(only_show_issued),
    "ClearNotIncluded": bool(clear_not_included),
})

errs = []
if not param_names:
    errs.append("ParamNames missing/empty from upstream packet.")
if not rev_id_to_param:
    errs.append("RevIdToParam missing/empty from upstream packet (and rebuild failed).")
if errs:
    _fail_loud(
        reason="; ".join(errs),
        hint="Upstream must provide ParamNames; RevIdToParam can rebuild only if model Revisions match canonical naming.",
        extract=extract_dbg,
        errors=errs
    )

# collect sheets
sheets = list(
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_Sheets)
    .WhereElementIsNotElementType()
    .ToElements()
)
sheets = [s for s in sheets if isinstance(s, ViewSheet)]

set_cells = 0
cleared_cells = 0
sheets_processed = 0
sheets_skipped = 0

missing_param_errors = []
write_fail_errors = []
missing_map_errors = []
sheet_debug = []

# Dynamo-safe transaction
try:
    TransactionManager.Instance.EnsureInTransaction(doc)

    for sh in sheets:
        included_ids, addl, clouds_sheet, clouds_views, all_ids = get_included_revision_ids(doc, sh, only_show_issued)

        try:
            sh_num = safe_str(sh.SheetNumber)
        except:
            sh_num = "<unknown>"

        included_param_names = set()
        unmapped_ids = []

        for rid_int in included_ids:
            pname = rev_id_to_param.get(int(rid_int), None)
            if pname:
                included_param_names.add(pname)
            else:
                unmapped_ids.append(int(rid_int))

        sheet_debug.append({
            "SheetNumber": sh_num,
            "IncludedRevisionIds": len(included_ids),
            "UnmappedIncludedRevisionIds": len(unmapped_ids),
            "IncludedParamNames": len(included_param_names),
            "CheckedOnSheetCount": len(addl),
            "CloudsOnSheetCount": len(clouds_sheet),
            "CloudsInViewsCount": len(clouds_views),
            "GetAllRevisionIdsCount": len(all_ids),
        })

        if unmapped_ids:
            if len(missing_map_errors) < 50:
                missing_map_errors.append({
                    "Sheet": sh_num,
                    "UnmappedRevisionIds": unmapped_ids[:20],
                    "RevPrefixUsed": rev_prefix_used,
                })

        if only_add_sheets_with_revs and len(included_param_names) == 0:
            sheets_skipped += 1
            continue

        sheets_processed += 1

        for pname in included_param_names:
            p = get_sheet_param_by_name(sh, pname)
            if p is None:
                if len(missing_param_errors) < 50:
                    missing_param_errors.append({"Sheet": sh_num, "Param": safe_str(pname), "Reason": "LookupParameter returned None"})
                continue

            changed, failed, reason = set_string_param(p, TRUE_SYMBOL)
            if failed:
                if len(write_fail_errors) < 50:
                    write_fail_errors.append({
                        "Sheet": sh_num,
                        "Param": safe_str(pname),
                        "IsReadOnly": bool(getattr(p, "IsReadOnly", False)),
                        "Reason": safe_str(reason),
                    })
                continue
            if changed:
                set_cells += 1

        if (not only_add_sheets_with_revs) and clear_not_included:
            for pname in param_names:
                if pname in included_param_names:
                    continue
                p = get_sheet_param_by_name(sh, pname)
                if p is None:
                    continue
                changed, failed, reason = set_string_param(p, "")
                if failed:
                    if len(write_fail_errors) < 50:
                        write_fail_errors.append({
                            "Sheet": sh_num,
                            "Param": safe_str(pname),
                            "IsReadOnly": bool(getattr(p, "IsReadOnly", False)),
                            "Reason": safe_str(reason),
                        })
                    continue
                if changed:
                    cleared_cells += 1

    try:
        doc.Regenerate()
    except:
        pass

finally:
    try:
        TransactionManager.Instance.TransactionTaskDone()
    except:
        pass

# fail-loud if any operational errors occurred
op_errors = []
if missing_map_errors:
    op_errors.append("Included revisions could not be mapped to parameters (RevIdToParam mismatch).")
if missing_param_errors:
    op_errors.append("Some sheet parameters were missing (LookupParameter returned None).")
if write_fail_errors:
    op_errors.append("Some parameters could not be written (read-only or Set failures).")

if op_errors:
    _fail_loud(
        reason="; ".join(op_errors),
        hint="Binding must exist on sheets; name rule must match; read-only failures must be resolved by re-binding correctly.",
        extract={
            **extract_dbg,
            "SheetsTotal": len(sheets),
            "SheetsProcessed": sheets_processed,
            "SheetsSkipped": sheets_skipped,
            "SetCells": set_cells,
            "ClearedCells": cleared_cells,
        },
        errors=[
            "MissingMapSample={}".format(missing_map_errors[:10]),
            "MissingParamSample={}".format(missing_param_errors[:10]),
            "WriteFailSample={}".format(write_fail_errors[:10]),
        ]
    )

report.update({
    "SheetsTotal": len(sheets),
    "SheetsProcessed": sheets_processed,
    "SheetsSkippedNoRevs": sheets_skipped,
    "SetCells": set_cells,
    "ClearedCells": cleared_cells,
    "MissingMapCount": len(missing_map_errors),
    "MissingParamCount": len(missing_param_errors),
    "WriteFailCount": len(write_fail_errors),
})

debug.update({
    "Extract": extract_dbg,
    "SheetDebugSample": sheet_debug[:50],
})

OUT = {
    "SharedParamFilePath": sp_path,
    "SharedParamGroupName": sp_group_name,
    "ParamGroupAssignment": group_assignment,
    "RevPrefix": rev_prefix_used,
    "ParamNames": [safe_str(x) for x in param_names],
    "RevIdToParam": {safe_str(k): safe_str(v) for k, v in rev_id_to_param.items()},
    "Report": report,
    "Debug": debug,
    "Notes": notes,
}
