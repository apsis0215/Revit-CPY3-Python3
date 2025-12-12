import clr

# ------------------------------------------------------------
# Revit / Dynamo references
# ------------------------------------------------------------
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    SharedParameterElement,
    ParameterElement,
    FilteredElementCollector,
    Transaction,
    TransactionGroup,
    ViewSchedule,
    InstanceBinding,
    TypeBinding
)

doc = DocumentManager.Instance.CurrentDBDocument
bindings = doc.ParameterBindings

# ------------------------------------------------------------
# Player input parsing
# ------------------------------------------------------------
def parse_prefixes(value, allow_star):
    if not value:
        return []
    value = str(value).strip()
    if allow_star and value == "*":
        return [""]
    return [p.strip() for p in value.split(",") if p.strip() and p.strip() != "*"]

# ------------------------------------------------------------
# Inputs
# ------------------------------------------------------------
FilterPrefix = parse_prefixes(IN[0], True)
ForcePrefix = parse_prefixes(IN[1], True)
FilterKeep = parse_prefixes(IN[2], False)

PurgeProjectParams = bool(IN[3]) if len(IN) > 3 and IN[3] is not None else False
ListOnly = bool(IN[4]) if len(IN) > 4 and IN[4] is not None else False

FilterPrefix = [p.lower() for p in FilterPrefix]
ForcePrefix = [p.lower() for p in ForcePrefix]
FilterKeep = [p.lower() for p in FilterKeep]

ForceActive = bool(ForcePrefix)

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def starts_with_any(name_l, prefixes):
    for p in prefixes:
        if name_l.startswith(p):
            return p
    return None

def binding_info(defn):
    if not bindings.Contains(defn):
        return "Unbound"

    b = bindings.get_Item(defn)

    if isinstance(b, InstanceBinding):
        scope = "Instance"
    elif isinstance(b, TypeBinding):
        scope = "Type"
    else:
        scope = "Unknown"

    try:
        cats = sorted([c.Name for c in b.Categories])
        cat_str = ", ".join(cats) if cats else "No Categories"
    except:
        cat_str = "No Categories"

    return "{} | {}".format(scope, cat_str)

def used_in_schedules(defn):
    hits = []
    for vs in FilteredElementCollector(doc).OfClass(ViewSchedule):
        sd = vs.Definition
        for fid in sd.GetFieldOrder():
            f = sd.GetField(fid)
            if f.GetName() == defn.Name:
                hits.append(vs.Name)
    return hits

results = []

# ------------------------------------------------------------
# Transaction group
# ------------------------------------------------------------
tg = TransactionGroup(doc, "Dynamo: Parameter Audit / Purge")
tg.Start()

# ============================================================
# SHARED PARAMETERS
# ============================================================
t1 = Transaction(doc, "Shared Parameters")
t1.Start()

shared_params = (
    FilteredElementCollector(doc)
    .OfClass(SharedParameterElement)
    .ToElements()
)

for sp in shared_params:
    defn = sp.GetDefinition()
    name = sp.Name
    name_l = name.lower()

    keep_hit = starts_with_any(name_l, FilterKeep)
    norm_hit = starts_with_any(name_l, FilterPrefix)
    force_hit = starts_with_any(name_l, ForcePrefix)

    bind = binding_info(defn)
    sched = used_in_schedules(defn)

    protected = bool(sched) and not ForceActive
    in_scope = bool(norm_hit or force_hit)

    # LIST ONLY: full inventory
    if ListOnly:
        status = []
        if keep_hit:
            status.append("KEPT")
        if in_scope:
            status.append("MATCH")
        if protected:
            status.append("PROTECTED")
        if not status:
            status.append("NONE")

        extra = ""
        if sched:
            extra = " | Schedules: " + ", ".join(sched[:5]) + ("..." if len(sched) > 5 else "")

        results.append(f"[LIST] [Shared] {name} | {bind} | {', '.join(status)}{extra}")
        continue

    # Normal execution
    if keep_hit:
        results.append(f"+++Kept [Shared] {name} | {bind}")
        continue

    if not in_scope:
        continue

    if protected:
        extra = " | Schedules: " + ", ".join(sched[:5]) + ("..." if len(sched) > 5 else "")
        results.append(f"!!!PROTECTED [Shared] {name} | {bind}{extra}")
        continue

    try:
        doc.Delete(sp.Id)
        tag = "-DelForce" if force_hit else "--Deleted"
        hit = force_hit if force_hit else norm_hit
        results.append(f"{tag} [Shared:{hit}] {name} | {bind}")
    except Exception as e:
        results.append(f"[SYSTEM] [Shared] {name} | {bind} | {e}")

t1.Commit()

# ============================================================
# PROJECT PARAMETERS
# ============================================================
if PurgeProjectParams:
    t2 = Transaction(doc, "Project Parameters")
    t2.Start()

    params = (
        FilteredElementCollector(doc)
        .OfClass(ParameterElement)
        .ToElements()
    )

    for pe in params:
        if isinstance(pe, SharedParameterElement):
            continue

        name = pe.Name
        name_l = name.lower()

        keep_hit = starts_with_any(name_l, FilterKeep)
        norm_hit = starts_with_any(name_l, FilterPrefix)
        force_hit = starts_with_any(name_l, ForcePrefix)

        in_scope = bool(norm_hit or force_hit)

        if ListOnly:
            status = []
            if keep_hit:
                status.append("KEPT")
            if in_scope:
                status.append("MATCH")
            if not status:
                status.append("NONE")
            results.append(f"[LIST] [Project] {name} | {', '.join(status)}")
            continue

        if keep_hit:
            results.append(f"+++Kept [Project] {name}")
            continue

        if not in_scope:
            continue

        try:
            doc.Delete(pe.Id)
            tag = "-DelForce" if force_hit else "--Deleted"
            hit = force_hit if force_hit else norm_hit
            results.append(f"{tag} [Project:{hit}] {name}")
        except Exception as e:
            results.append(f"[SYSTEM] [Project] {name} | {e}")

    t2.Commit()

tg.Assimilate()

OUT = results
