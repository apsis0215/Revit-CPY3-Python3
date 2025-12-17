# ----------------------------------------------------------------------
# Py.Assign.Facade.Direction.v02
# Revit 2025+, Dynamo Python 3
#
# Implements:
# - Horizontal ray (walls only)
# - Vertical ray UP from half distance
# - Includes Massing elements
# - No bounding-box sky tests
# - Group-safe
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
    FindReferenceTarget,
    View3D
)

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument
app = doc.Application

# ----------------------------------------------------------------------
# INPUTS
# ----------------------------------------------------------------------
includeCourtyards = bool(IN[0]) if IN[0] is not None else False
planNorthOffsetDeg = float(IN[1]) if IN[1] not in [None, ""] else 0.0
maxSearchDist = float(IN[2]) if IN[2] not in [None, ""] else 400.0
verticalLimit = float(IN[3]) if IN[3] not in [None, ""] else 300.0

PARAM_NAME = "__.Code.Ref.Direction"
EPS = 1e-6

# ----------------------------------------------------------------------
# UTILITIES
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
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    dx, dy = p1.X - p0.X, p1.Y - p0.Y
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

# ----------------------------------------------------------------------
# GET A 3D VIEW (REQUIRED FOR RAYS)
# ----------------------------------------------------------------------
view3d = None
for v in FilteredElementCollector(doc).OfClass(View3D):
    if not v.IsTemplate:
        view3d = v
        break

if not view3d:
    OUT = {"Error": "No 3D view available for ray intersection."}
    raise Exception("3D view required")

# ----------------------------------------------------------------------
# INTERSECTORS
# ----------------------------------------------------------------------
wall_filter = ElementClassFilter(DB.Wall)
wall_intersector = ReferenceIntersector(
    wall_filter,
    FindReferenceTarget.Element,
    view3d
)

# Vertical blockers: Floors, Roofs, Ceilings, Mass
blocker_categories = [
    BuiltInCategory.OST_Floors,
    BuiltInCategory.OST_Roofs,
    BuiltInCategory.OST_Ceilings,
    BuiltInCategory.OST_Mass
]

blocker_filters = []
for bic in blocker_categories:
    blocker_filters.append(DB.ElementCategoryFilter(bic))

blocker_filter = DB.LogicalOrFilter(blocker_filters)

blocker_intersector = ReferenceIntersector(
    blocker_filter,
    FindReferenceTarget.Element,
    view3d
)

# ----------------------------------------------------------------------
# TRANSACTION
# ----------------------------------------------------------------------
TransactionManager.Instance.EnsureInTransaction(doc)

# Reset all
for e in walls + windows:
    if is_in_group(e):
        continue
    p = e.LookupParameter(PARAM_NAME)
    if p:
        p.Set(-1)

exterior_walls = []
exterior_windows = []
courtyard_included = []
courtyard_excluded = []

# ----------------------------------------------------------------------
# PROCESS WALLS
# ----------------------------------------------------------------------
for w in walls:
    if is_in_group(w):
        continue

    n = wall_normal_xy(w)
    if not n:
        continue

    mid = wall_midpoint(w)

    # 1ï¸âƒ£ Horizontal ray
    hit = wall_intersector.FindNearest(mid, n)
    if hit and hit.Proximity < maxSearchDist:
        lateral_dist = hit.Proximity
        is_courtyard = True
    else:
        lateral_dist = maxSearchDist
        is_courtyard = False

    # 2ï¸âƒ£ Vertical test origin (half distance)
    offset = lateral_dist * 0.5
    test_pt = XYZ(
        mid.X + n.X * offset,
        mid.Y + n.Y * offset,
        mid.Z + n.Z * offset
    )

    # 3ï¸âƒ£ Vertical ray up
    up_hit = blocker_intersector.FindNearest(test_pt, XYZ.BasisZ)

    covered = False
    if up_hit and up_hit.Proximity <= verticalLimit:
        covered = True

    if covered:
        continue

    if is_courtyard and not includeCourtyards:
        courtyard_excluded.append(w)
        continue

    # 4ï¸âƒ£ Compute azimuth
    n_rot = rotate_xy(n, planNorthOffsetDeg)
    ang = math.degrees(math.atan2(n_rot.X, n_rot.Y))
    if ang < 0:
        ang += 360
    ang = int(round(ang)) % 360

    p = w.LookupParameter(PARAM_NAME)
    if p:
        p.Set(ang)

    exterior_walls.append(w)
    if is_courtyard:
        courtyard_included.append(w)

# ----------------------------------------------------------------------
# WINDOWS INHERIT HOST
# ----------------------------------------------------------------------
for win in windows:
    if is_in_group(win):
        continue

    host = win.Host
    if not host:
        continue

    hp = host.LookupParameter(PARAM_NAME)
    wp = win.LookupParameter(PARAM_NAME)

    if hp and wp:
        val = hp.AsInteger()
        wp.Set(val)
        if val != -1:
            exterior_windows.append(win)

TransactionManager.Instance.TransactionTaskDone()

# ----------------------------------------------------------------------
# OUTPUT
# ----------------------------------------------------------------------
OUT = {
    "Status": "Completed",
    "ExteriorWalls": exterior_walls,
    "ExteriorWindows": exterior_windows,
    "CourtyardWallsIncluded": courtyard_included,
    "CourtyardWallsExcluded": courtyard_excluded
}
