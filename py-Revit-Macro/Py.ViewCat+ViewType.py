# purpose and IO:
# IN[0] = View or list of Views (Revit DB View objects)
# IN[1] = (optional) bool includeElementCounts (default False)
# OUT   = list of dictionaries, one per view:
#         {
#           "ViewName": str,
#           "ViewId": int,
#           "ViewType": str,
#           "ViewFamilyTypeId": int or None,
#           "IsDraftingView": bool,
#           "Categories": [ {"Name": str, "Id": int, "Count": int(optional)} ... ]
#         }

import clr

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager  # get doc

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    View,
    ViewType,
    FilteredElementCollector,
    ElementId
)

doc = DocumentManager.Instance.CurrentDBDocument


def _as_list(x):
    if x is None:
        return []
    # Dynamo sometimes passes IList; treat non-string iterables as list
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _safe_int_eid(eid):
    try:
        if isinstance(eid, ElementId):
            return eid.IntegerValue
    except:
        pass
    return None


def _view_family_type_id(view):
    # Some views have a ViewFamilyType; Drafting Views do.
    try:
        vft_id = view.GetTypeId()
        return _safe_int_eid(vft_id)
    except:
        return None


def export_view_type_and_categories(view, include_counts=False):
    """
    Returns a dict containing view type info + a sorted list of categories
    that appear in that view (based on elements owned by that view).
    """
    if view is None or not isinstance(view, View):
        return {"Error": "Input is not a Revit DB View.", "Input": str(view)}

    # View type
    vt_str = str(view.ViewType)  # enum to string
    is_drafting = (view.ViewType == ViewType.DraftingView)

    # Collect elements *in the view* (view-specific + some model items visible in view)
    cats = {}  # catIdInt -> {"Name":..., "Id":..., "Count":...}

    try:
        collector = FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
        for e in collector:
            cat = e.Category
            if cat is None:
                continue
            cat_id = _safe_int_eid(cat.Id)
            if cat_id is None:
                continue

            if cat_id not in cats:
                cats[cat_id] = {"Name": cat.Name, "Id": cat_id, "Count": 0}

            if include_counts:
                cats[cat_id]["Count"] += 1
    except Exception as ex:
        return {
            "ViewName": view.Name,
            "ViewId": _safe_int_eid(view.Id),
            "ViewType": vt_str,
            "ViewFamilyTypeId": _view_family_type_id(view),
            "IsDraftingView": is_drafting,
            "Error": "Failed collecting elements in view.",
            "Exception": str(ex)
        }

    # Build sorted output categories
    cat_list = list(cats.values())
    cat_list.sort(key=lambda d: (d.get("Name") or "").lower())

    # If not including counts, remove Count to keep clean payload
    if not include_counts:
        for d in cat_list:
            d.pop("Count", None)

    return {
        "ViewName": view.Name,
        "ViewId": _safe_int_eid(view.Id),
        "ViewType": vt_str,
        "ViewFamilyTypeId": _view_family_type_id(view),
        "IsDraftingView": is_drafting,
        "Categories": cat_list
    }


# Inputs
views_in = IN[0] if len(IN) > 0 else None
include_counts = IN[1] if len(IN) > 1 and IN[1] is not None else False

views = _as_list(views_in)

results = []
for v in views:
    results.append(export_view_type_and_categories(v, include_counts))

OUT = results
