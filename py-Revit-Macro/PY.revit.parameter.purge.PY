import clr
import fnmatch

# ------------------------------------------------------------
# Revit / Dynamo
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
# Input helpers
# ------------------------------------------------------------
def parse_patterns(value):
    if not value:
        return []
    out = []
    for v in str(value).split(","):
        v = v.strip().lower()
        if not v:
            continue
        if not any(ch in v for ch in ["*", "?", "[", "]"]):
            v += "*"  # implicit prefix match
        out.append(v)
    return out

def matches_any(name_l, patterns):
    for p in patterns:
        if fnmatch.fnmatch(name_l, p):
            return p
    return None

# ------------------------------------------------------------
# Inputs
# ------------------------------------------------------------
PrefixTarget = parse_patterns(IN[0])
ForcePatterns = parse_patterns(IN[1])
KeepPatterns  = parse_patterns(IN[2])

PurgeProjectParams = bool(IN[3]) if len(IN) > 3 else False
ListOnly = bool(IN[4]) if len(IN) > 4 else False

# ------------------------------------------------------------
# Defaults
# ------------------------------------------------------------
if not PrefixTarget:
    PrefixTarget = ["*"]

if not KeepPatterns:
    KeepPatterns = ["ae*", "__*"]

ForceActive = bool(ForcePatterns)

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def binding_info(defn):
    if not bindings.Contains(defn):
        return "Unbound"

    b = bindings.get_Item(defn)
    scope = "Instance" if isinstance(b, InstanceBinding) else "Type"
    try:
        cats = sorted([c.Name for c in b.Categories])
        cat_str = ", ".join(cats)
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

# ------------------------------------------------------------
# Execution
# ------------------------------------------------------------
results = []

tg = TransactionGroup(doc, "Parameter purge")
tg.Start()

# ============================================================
# SHARED PARAMETERS
# ============================================================
t1 = Transaction(doc, "Shared Parameters")
t1.Start()

shared_params = FilteredElementCollector(doc).OfClass(SharedParameterElement).ToElements()

for sp in shared_params:
    defn = sp.GetDefinition()
    name = sp.Name
    name_l = name.lower()

    # Phase 1: Prefix candidate
    target_hit = matches_any(name_l, PrefixTarget)
    if not target_hit:
        continue

    # Phase 2: Keep exclusion (absolute)
    keep_hit = matches_any(name_l, KeepPatterns)
    if keep_hit:
        if ListOnly:
            results.append(f"[LIST] [Shared] {name} | KEPT")
        else:
            results.append(f"+++Kept [Shared] {name}")
        continue

    bind = binding_info(defn)
    sched = used_in_schedules(defn)
    in_use = bool(sched)

    # Phase 3: Force logic
    force_hit = matches_any(name_l, ForcePatterns)

    if ListOnly:
        status = "MATCH"
        if in_use and not (ForceActive and force_hit):
            status = "PROTECTED"
        extra = ""
        if sched:
            extra = " | Schedules: " + ", ".join(sched[:5])
        results.append(f"[LIST] [Shared] {name} | {bind} | {status}{extra}")
        continue

    if in_use and not (ForceActive and force_hit):
        extra = " | Schedules: " + ", ".join(sched[:5])
        results.append(f"!!!PROTECTED [Shared] {name} | {bind}{extra}")
        continue

    try:
        doc.Delete(sp.Id)
        tag = "-DelForce" if force_hit else "--Deleted"
        results.append(f"{tag} [Shared] {name} | {bind}")
    except Exception as e:
        results.append(f"[SYSTEM] [Shared] {name} | {e}")

t1.Commit()

# ============================================================
# PROJECT PARAMETERS
# ============================================================
if PurgeProjectParams:
    t2 = Transaction(doc, "Project Parameters")
    t2.Start()

    params = FilteredElementCollector(doc).OfClass(ParameterElement).ToElements()

    for pe in params:
        if isinstance(pe, SharedParameterElement):
            continue

        name = pe.Name
        name_l = name.lower()

        # Phase 1: Prefix candidate
        if not matches_any(name_l, PrefixTarget):
            continue

        # Phase 2: Keep exclusion
        if matches_any(name_l, KeepPatterns):
            if ListOnly:
                results.append(f"[LIST] [Project] {name} | KEPT")
            else:
                results.append(f"+++Kept [Project] {name}")
            continue

        # Phase 3: Force permission only
        force_hit = matches_any(name_l, ForcePatterns)

        if ListOnly:
            status = "MATCH"
            if not ForceActive:
                status = "MATCH (blind)"
            results.append(f"[LIST] [Project] {name} | {status}")
            continue

        if not ForceActive and not force_hit:
            results.append(f"!!!SKIPPED [Project] {name} | No usage detection")
            continue

        try:
            doc.Delete(pe.Id)
            results.append(f"-DelForce [Project] {name}")
        except Exception as e:
            results.append(f"[SYSTEM] [Project] {name} | {e}")

    t2.Commit()

tg.Assimilate()

OUT = results
