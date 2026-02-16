# Leader extraction (Revit 2023-2026, Dynamo IronPython)
# Returns:
#   "" if no leaders
#   "(end=(x,y,z),elbow=(x,y,z),anchor=(x,y,z)),(...)" for multi-leaders
#
# Why this exists:
# - In IronPython, Revit API members may appear as properties OR get_* methods OR callables.
# - Some annotation types expose leader collections (GetLeaders / Leaders),
#   others only expose element-level leader points (LeaderEnd / LeaderElbow).
#
# Usage:
#   leaders_str = get_leader_triplets_csv(element)

def _get_member_xyz(obj, name):
    # Try: obj.Name, obj.Name(), obj.get_Name()
    if obj is None:
        return None

    # 1) Property or callable
    try:
        if hasattr(obj, name):
            v = getattr(obj, name)
            if callable(v):
                try:
                    v = v()
                except:
                    v = None
            if v is not None:
                try:
                    _ = v.X; __ = v.Y; ___ = v.Z
                    return v
                except:
                    pass
    except:
        pass

    # 2) Revit getter: get_Name()
    try:
        g = "get_" + name
        if hasattr(obj, g):
            m = getattr(obj, g)
            if callable(m):
                try:
                    v = m()
                    if v is not None:
                        _ = v.X; __ = v.Y; ___ = v.Z
                        return v
                except:
                    pass
    except:
        pass

    return None


def get_leader_triplets_csv(el):
    # "" if no leaders, else "(end=(x,y,z),elbow=(x,y,z),anchor=(x,y,z)),(...)" for multi

    def fmt_xyz(p):
        if p is None:
            return ""
        try:
            return "({},{},{})".format(str(p.X), str(p.Y), str(p.Z))
        except:
            return ""

    def leader_triplet_from_leader_obj(ld):
        end_pt   = _get_member_xyz(ld, "End")   or _get_member_xyz(ld, "EndPoint")
        elbow_pt = _get_member_xyz(ld, "Elbow") or _get_member_xyz(ld, "ElbowPoint")
        anch_pt  = _get_member_xyz(ld, "Anchor") or _get_member_xyz(ld, "AnchorPoint")
        return "end={0},elbow={1},anchor={2}".format(fmt_xyz(end_pt), fmt_xyz(elbow_pt), fmt_xyz(anch_pt))

    # Tier 1: GetLeaders() (AnnotationSymbol often)
    leaders = []
    try:
        if hasattr(el, "GetLeaders"):
            gl = getattr(el, "GetLeaders")
            if callable(gl):
                try:
                    ls = gl()
                    if ls:
                        for ld in ls:
                            leaders.append(ld)
                except:
                    pass
    except:
        pass

    # Tier 2: Leaders collection (some types)
    if not leaders:
        try:
            if hasattr(el, "Leaders"):
                ls = getattr(el, "Leaders")
                if ls:
                    for ld in ls:
                        leaders.append(ld)
        except:
            pass

    # If we got leader objects, format them (skip all-empty triplets)
    if leaders:
        parts = []
        for ld in leaders:
            try:
                s = leader_triplet_from_leader_obj(ld)
                if "end=()" in s and "elbow=()" in s and "anchor=()" in s:
                    continue
                parts.append("({})".format(s))
            except:
                continue
        if parts:
            return ",".join(parts)
        # leaders exist but points unreadable -> fall through

    # Tier 3: element-level leader points (common fallback in IronPython)
    end_pt = _get_member_xyz(el, "LeaderEnd") or _get_member_xyz(el, "LeaderEndPoint")
    elbow_pt = _get_member_xyz(el, "LeaderElbow") or _get_member_xyz(el, "LeaderElbowPoint")
    anch_pt = _get_member_xyz(el, "LeaderAnchor") or _get_member_xyz(el, "LeaderAnchorPoint") \
              or _get_member_xyz(el, "Anchor") or _get_member_xyz(el, "AnchorPoint")

    if end_pt or elbow_pt or anch_pt:
        return "(end={0},elbow={1},anchor={2})".format(fmt_xyz(end_pt), fmt_xyz(elbow_pt), fmt_xyz(anch_pt))

    return ""
