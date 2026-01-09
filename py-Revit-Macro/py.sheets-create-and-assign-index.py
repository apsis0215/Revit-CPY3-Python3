# py.sheets-create-and-assign-index.py
# PURPOSE:
# 1) Ensure shared parameters exist, are bound to Sheets, and appear under requested group.
# 2) Assign sheet sort values from fuzzy match results.

import clr
import System

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    BuiltInCategory, CategorySet, ExternalDefinition, LabelUtils,
    GroupTypeId, StorageType
)

doc = DocumentManager.Instance.CurrentDBDocument
uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

# -----------------------------
# WRAPPER NAME (for reporting)
# -----------------------------
WRAPPER_NAME = "Sheet Index Create and assign"

# -----------------------------
# HARD CODED PARAM NAMES (write targets)
# -----------------------------
PARAM_FIRST  = "__.SHT.Sort.Seq.First"
PARAM_HEADER = "__.SHT.Sort.Seq.HEADER"
PARAM_SECOND = "__.SHT.Sort.Seq.Second"

# Inputs
fuzzy_data = IN[0] or []
pairs = IN[1] or []
create_missing = bool(IN[2]) if len(IN) > 2 and IN[2] is not None else False
sp_path = IN[3] if len(IN) > 3 else None

fuzzy_data = fuzzy_data if isinstance(fuzzy_data, list) else [fuzzy_data]
pairs = pairs if isinstance(pairs, list) else [pairs]

def unwrap(x):
    try:
        return UnwrapElement(x)
    except:
        return x

def iter_bindings(binding_map):
    it = binding_map.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        yield it.Key, it.Current

def get_def_and_binding_by_name(name):
    for d, b in iter_bindings(doc.ParameterBindings):
        if d and d.Name == name:
            return d, b
    return None, None

def get_group_type_id(definition):
    if not definition:
        return None
    try:
        return definition.GetGroupTypeId()
    except:
        return None

def label_for_group_type_id(gid):
    if gid is None:
        return None
    try:
        return LabelUtils.GetLabelForGroup(gid)
    except:
        try:
            return str(gid)
        except:
            return None

def is_bound_to_sheets(binding):
    if not binding:
        return False
    try:
        for c in binding.Categories:
            if c.Id.IntegerValue == int(BuiltInCategory.OST_Sheets):
                return True
    except:
        pass
    return False

def ensure_sheets_categories(existing_binding):
    cats = CategorySet()
    try:
        for c in existing_binding.Categories:
            cats.Insert(c)
    except:
        pass
    sheets_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Sheets)
    cats.Insert(sheets_cat)
    return cats

def _pg_token_to_grouptypeid_prop(token):
    t = (token or "").strip().upper()
    if not t.startswith("PG_"):
        return None
    core = t[3:]
    parts = [p for p in core.split("_") if p]
    if not parts:
        return None
    return "".join([p[:1] + p[1:].lower() for p in parts])

def normalize_group_token(token):
    if token is None or str(token).strip() == "":
        return GroupTypeId.IdentityData

    raw = str(token).strip()
    candidates = []

    prop = _pg_token_to_grouptypeid_prop(raw)
    if prop:
        candidates.append(prop)

    candidates.append(raw)

    if raw.upper() == "PG_IDENTITY_DATA":
        candidates.insert(0, "IdentityData")

    for name in candidates:
        try:
            v = getattr(GroupTypeId, name)
            if v is not None:
                return v
        except:
            pass

    return GroupTypeId.IdentityData

def open_shared_param_file(path):
    if not path:
        return None
    try:
        app.SharedParametersFilename = path
        return app.OpenSharedParameterFile()
    except:
        return None

def find_sp_def_any_group(sp_file, def_name):
    if not sp_file:
        return None
    try:
        for g in sp_file.Groups:
            d = g.Definitions.get_Item(def_name)
            if d:
                return d
    except:
        pass
    return None

def reinsert_to_sheets(definition, existing_binding, desired_group_type_id):
    cats = ensure_sheets_categories(existing_binding)
    new_binding = app.Create.NewInstanceBinding(cats)
    ok = doc.ParameterBindings.ReInsert(definition, new_binding, desired_group_type_id)
    if not ok:
        ok = doc.ParameterBindings.Insert(definition, new_binding, desired_group_type_id)
    return bool(ok)

def insert_new_to_sheets(external_def, desired_group_type_id):
    cats = CategorySet()
    sheets_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Sheets)
    cats.Insert(sheets_cat)
    binding = app.Create.NewInstanceBinding(cats)
    ok = doc.ParameterBindings.Insert(external_def, binding, desired_group_type_id)
    if not ok:
        ok = doc.ParameterBindings.ReInsert(external_def, binding, desired_group_type_id)
    return bool(ok)

def set_param_value(elem, param_name, value):
    if elem is None:
        return False, "Element is None"

    p = elem.LookupParameter(param_name)
    if p is None:
        return False, "Parameter not found"

    if p.IsReadOnly:
        return False, "Parameter is read-only"

    try:
        if value is None:
            value = ""

        st = p.StorageType
        if st == StorageType.String:
            p.Set(str(value))
        elif st == StorageType.Integer:
            v = 0 if (value == "" or value is None) else int(value)
            p.Set(v)
        elif st == StorageType.Double:
            v = 0.0 if (value == "" or value is None) else float(value)
            p.Set(v)
        elif st == StorageType.ElementId:
            return False, "ElementId storage not supported"
        else:
            return False, "Unknown storage type"

        return True, "Set"
    except Exception as ex:
        return False, str(ex)

param_report = {}
sheet_report = {"updated": 0, "items": [], "transaction": WRAPPER_NAME}

try:
    sp_file = open_shared_param_file(sp_path) if create_missing else None

    # One Dynamo transaction wrapper
    TransactionManager.Instance.EnsureInTransaction(doc)

    # (A) Ensure/bind/group shared params
    for pair in pairs:
        try:
            pname = pair[0]
            gtok = pair[1] if len(pair) > 1 else "PG_IDENTITY_DATA"
        except:
            continue

        desired_gid = normalize_group_token(gtok)

        d, b = get_def_and_binding_by_name(pname)
        exists = d is not None
        bound = is_bound_to_sheets(b) if b else False
        curr_gid = get_group_type_id(d) if d else None

        created = False
        moved = False
        rebound = False
        msg = ""

        if not exists:
            if create_missing and sp_file:
                sp_def = find_sp_def_any_group(sp_file, pname)
                if sp_def:
                    ok = insert_new_to_sheets(sp_def, desired_gid)
                    created = ok
                    msg = "Created+bound" if ok else "Failed create/bind"
                    d, b = get_def_and_binding_by_name(pname)
                    exists = d is not None
                    bound = is_bound_to_sheets(b) if b else False
                    curr_gid = get_group_type_id(d) if d else None
                else:
                    msg = "Not found in shared parameter file"
            else:
                msg = "Missing in project"
        else:
            need_bind = not bound
            need_move = (curr_gid is None) or (str(curr_gid) != str(desired_gid))

            if need_bind or need_move:
                ok = reinsert_to_sheets(d, b, desired_gid)
                rebound = ok and need_bind
                moved = ok and need_move
                msg = "Rebound/moved" if ok else "Failed rebound/move"
                d, b = get_def_and_binding_by_name(pname)
                bound = is_bound_to_sheets(b) if b else False
                curr_gid = get_group_type_id(d) if d else None
            else:
                msg = "OK"

        guid = None
        try:
            if isinstance(d, ExternalDefinition):
                guid = str(d.GUID)
        except:
            pass

        param_report[pname] = {
            "exists_in_project": bool(d),
            "bound_to_sheets": bool(bound),
            "current_group": str(curr_gid) if curr_gid is not None else None,
            "current_group_label": label_for_group_type_id(curr_gid),
            "desired_group": str(desired_gid),
            "desired_group_label": label_for_group_type_id(desired_gid),
            "created": created,
            "rebound": rebound,
            "moved_group": moved,
            "guid": guid,
            "message": msg
        }

    # (B) Apply values to sheets
    for i, row in enumerate(fuzzy_data):
        if not isinstance(row, dict):
            sheet_report["items"].append({"index": i, "ok": False, "message": "Row is not a dictionary"})
            continue

        sheet_db = unwrap(row.get("sheet"))
        n_id = row.get("n_id", "")
        header = row.get("header", "")
        second = ""

        item = {
            "index": i,
            "sheet_number": None,
            "sheet_name": None,
            "set_first": None,
            "set_header": None,
            "set_second": None,
            "ok": False
        }

        try:
            item["sheet_number"] = getattr(sheet_db, "SheetNumber", None)
            item["sheet_name"] = getattr(sheet_db, "Name", None)
        except:
            pass

        ok1, msg1 = set_param_value(sheet_db, PARAM_FIRST, n_id)
        ok2, msg2 = set_param_value(sheet_db, PARAM_HEADER, header)
        ok3, msg3 = set_param_value(sheet_db, PARAM_SECOND, second)

        item["set_first"] = msg1
        item["set_header"] = msg2
        item["set_second"] = msg3
        item["ok"] = bool(ok1 and ok2 and ok3)

        if item["ok"]:
            sheet_report["updated"] += 1

        sheet_report["items"].append(item)

except Exception as ex:
    sheet_report["error"] = str(ex)

finally:
    try:
        TransactionManager.Instance.TransactionTaskDone()
    except:
        pass

OUT = {"param_report": param_report, "sheet_report": sheet_report}
