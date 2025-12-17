# ----------------------------------------------------------------------
# Py.Element.Classification.v04
#
# Walls:
#   - Dual-side ray test (both normals)
#   - Exterior if either side is exterior
#   - Azimuth from exterior-facing side
#   - Confidence score per wall
#
# Windows & Doors:
#   - Inherit direction + confidence from host wall
#
# OUT:
#   ExteriorWalls
#   ExteriorWindows
#   ExteriorDoors
#   WallExteriorConfidence   {wallId:int : confidence:int}
#   WindowExteriorConfidence {windowId:int : confidence:int}
#   DoorExteriorConfidence   {doorId:int : confidence:int}
# ----------------------------------------------------------------------

import clr
import math
import Autodesk.Revit.DB as DB

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")

from Autodesk.Revit.DB import (
    XYZ, BuiltInCategory,
    FilteredElementCollector,
    ReferenceIntersector,
    ElementClassFilter,
    ElementCategoryFilter,
    LogicalOrFilter,
    FindReferenceTarget,
    View3D
)

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# ----------------------------------------------------------------------
# DOCUMENT
# ----------------------------------------------------------------------
doc = DocumentManager.Instance.CurrentDBDocument

# ----------------------------------------------------------------------
# INPUTS
# ----------------------------------------------------------------------
INCLUDE_COURTYARDS = bool(IN[0]) if IN[0] is not None else False
PLAN_NORTH_OFFSET = float(IN[1]) if IN[1] not in [None, ""] else 0.0
MAX_DIST = float(IN[2]) if IN[2] not in [None, ""] else 400.0
VERT_LIMIT = float(IN[3]) if IN[3] not in [None, ""] else 300.0

PARAM_NAME = "__.Code.Ref.Direction"
EPS = 1e-6

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def is_in_group(e):
    return e.GroupId and e.GroupId != DB.ElementId.InvalidElementId

def wall_midpoint(w):
    c = w.Location.Curve
    p0 = c.GetEndPoint(0)
    p1 = c.GetEndPoint(1)
    return XYZ(
        (p0.X + p1.X) * 0.5,
        (p0.Y + p1.Y) * 0.5,
        (p0.Z + p1.Z) * 0.5
    )

def wall_normal_xy(w):
    c = w.Location.Curve
    p0 = c.GetEndPoint(0)
    p1 = c.GetEndPoint(1)
    dx = p1.X - p0.X
    dy = p1.Y - p0.Y
    L = math.hypot(dx, dy)
    if L < EPS:
        return None
    return XYZ(dy / L, -dx / L, 0)

def rotate_xy(v, deg):
    r = math.radians(deg)
    return XYZ(
        v.X * math.cos(r) - v.Y * math.sin(r),
        v.X * math.sin(r) + v.Y * math.cos(r),
        0
    )

def offset_point(p, v, d):
    return XYZ(
        p.X + v.X * d,
        p.Y + v.Y * d,
        p.Z + v.Z * d
    )

# ----------------------------------------------------------------------
# COLLECT ELEMENTS
# ----------------------------------------------------------------------
walls = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Walls)\
    .WhereElementIsNotElementType()\
    .ToElements()

windows = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Windows)\
    .WhereElementIsNotElementType()\
    .ToElements()

doors = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Doors)\
    .WhereElementIsNotElementType()\
    .ToElements()

# ----------------------------------------------------------------------
# 3D VIEW (required for ReferenceIntersector)
# ----------------------------------------------------------------------
view3d = None
for v in FilteredElementCollector(doc).OfClass(View3D):
    if not v.IsTemplate:
        view3d = v
        break

if not view3d:
    OUT = {"Error": "No non-template 3D view found."}
else:

    # ------------------------------------------------------------------
    # INTERSECTORS
    # ------------------------------------------------------------------
    wall_intersector = ReferenceIntersector(
        ElementClassFilter(DB.Wall),
        FindReferenceTarget.Element,
        view3d
    )

    blocker_filter = LogicalOrFilter([
        ElementCategoryFilter(BuiltInCategory.OST_Floors),
        ElementCategoryFilter(BuiltInCategory.OST_Roofs),
        ElementCategoryFilter(BuiltInCategory.OST_Ceilings),
        ElementCategoryFilter(BuiltInCategory.OST_Mass)
    ])

    blocker_intersector = ReferenceIntersector(
        blocker_filter,
        FindReferenceTarget.Element,
        view3d
    )

    # ------------------------------------------------------------------
    # PROCESS WALLS
    # ------------------------------------------------------------------
    exterior_walls = []
    exterior_windows = []
    exterior_doors = []

    wall_conf = {}
    window_conf = {}
    door_conf = {}

    TransactionManager.Instance.EnsureInTransaction(doc)

    for w in walls:
        if is_in_group(w):
            continue

        p = w.LookupParameter(PARAM_NAME)
        if p:
            p.Set(-1)

        mid = wall_midpoint(w)
        n = wall_normal_xy(w)
        if not n:
            wall_conf[w.Id.IntegerValue] = 0
            continue

        sides = [n, XYZ(-n.X, -n.Y, 0)]
        results = []

        for side in sides:
            hit = wall_intersector.FindNearest(mid, side)
            if hit and hit.Proximity < MAX_DIST:
                lateral_dist = hit.Proximity
                courtyard = True
            else:
                lateral_dist = MAX_DIST
                courtyard = False

            test_pt = offset_point(mid, side, lateral_dist * 0.5)
            up_hit = blocker_intersector.FindNearest(test_pt, XYZ.BasisZ)
            covered = bool(up_hit and up_hit.Proximity <= VERT_LIMIT)

            results.append({
                "side": side,
                "exterior": not covered,
                "courtyard": courtyard
            })

        exterior_sides = [r for r in results if r["exterior"]]

        if not exterior_sides:
            wall_conf[w.Id.IntegerValue] = 0
            continue

        if all(r["courtyard"] for r in exterior_sides) and not INCLUDE_COURTYARDS:
            wall_conf[w.Id.IntegerValue] = 25
            continue

        best = next((r for r in exterior_sides if not r["courtyard"]), exterior_sides[0])

        n_rot = rotate_xy(best["side"], PLAN_NORTH_OFFSET)
        ang = math.degrees(math.atan2(n_rot.X, n_rot.Y))
        if ang < 0:
            ang += 360
        ang = int(round(ang)) % 360

        if p:
            p.Set(ang)

        exterior_walls.append(w)

        if len(exterior_sides) == 2:
            conf = 100
        elif best["courtyard"]:
            conf = 60
        else:
            conf = 85

        wall_conf[w.Id.IntegerValue] = conf

    # ------------------------------------------------------------------
    # WINDOWS & DOORS INHERIT FROM HOST WALL
    # ------------------------------------------------------------------
    for e, conf_map, out_list in [
        (windows, window_conf, exterior_windows),
        (doors, door_conf, exterior_doors)
    ]:
        for inst in e:
            if is_in_group(inst):
                continue

            host = inst.Host
            if not host:
                continue

            hp = host.LookupParameter(PARAM_NAME)
            ip = inst.LookupParameter(PARAM_NAME)

            if not hp or not ip:
                continue

            val = hp.AsInteger()
            ip.Set(val)

            hid = host.Id.IntegerValue
            iid = inst.Id.IntegerValue
            conf = wall_conf.get(hid, 0)

            conf_map[iid] = conf
            if val != -1:
                out_list.append(inst)

    TransactionManager.Instance.TransactionTaskDone()

    # ------------------------------------------------------------------
    # OUTPUT
    # ------------------------------------------------------------------
    OUT = {
        "ExteriorWalls": exterior_walls,
        "ExteriorWindows": exterior_windows,
        "ExteriorDoors": exterior_doors,
        "WallExteriorConfidence": wall_conf,
        "WindowExteriorConfidence": window_conf,
        "DoorExteriorConfidence": door_conf
    }
