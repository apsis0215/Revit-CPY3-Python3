# Family label/text styles canonicalizer + instance retype (Revit 2025+, CPython)
# Size policy:
# - ALWAYS snap to nearest 1/32" increment (lowest if .5 or lower).
# - If IN[4] specified: ONLY those sizes are allowed (normalized to 1/32"), snap to nearest allowed (tie -> lower).
# - If IN[4] blank: use defaults (normalized).
#
# IN[0]=ArialNarrowOnly(bool),
# IN[1]=TransparentOnly(bool),
# IN[2]=TabTo3_2(bool),
# IN[3]=AllowColorRGB(bool),
# IN[4]=SizesInput(str, optional) e.g. "1/16, 3/32, 1/8"
# OUT=list[str]

import clr, math, re

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInParameter, Parameter,
    TextElementType, TextElement, ElementId, Transaction
)

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

# ---------- inputs ----------
def _b(i, default=False):
    try:
        return bool(IN[i])
    except:
        return default

def _s(i, default=""):
    try:
        v = IN[i]
        if v is None:
            return default
        s = str(v).strip()
        return s if s else default
    except:
        return default

ArialNarrowOnly = _b(0, False)
TransparentOnly = _b(1, False)
TabTo3_2        = _b(2, False)
AllowColorRGB   = _b(3, False)
SizesInput      = _s(4, "")

# ---------- basic helpers ----------
def tname(t):
    try:
        p = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p:
            s = p.AsString()
            if s:
                return s
    except:
        pass
    try:
        return t.Name
    except:
        return "<unnamed>"

def set_tname(t, new):
    try:
        p = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and not p.IsReadOnly:
            p.Set(new)
            return True
    except:
        pass
    try:
        t.Name = new
        return True
    except:
        return False

# ---------- sizes (IN[4] optional) ----------
# Defaults (inches). These match your prior family script set.
_DEFAULT_SIZES_IN = [
    1/32.0, 1/16.0, 3/32.0, 1/8.0, 3/16.0, 1/4.0,
    3/8.0, 1/2.0, 3/4.0, 1.0, 1.5, 2.0, 2.5, 3.0
]

# Token finder: mixed, fraction, decimal, int
_SIZE_TOKEN_RE = re.compile(
    r'(\d+\s*-\s*\d+\s*/\s*\d+)|'   # 1-1/2
    r'(\d+\s+\d+\s*/\s*\d+)|'       # 1 1/2
    r'(\d+\s*/\s*\d+)|'             # 1/8
    r'(\d*\.\d+)|'                  # 0.09375
    r'(\d+)'                        # 2
)

def _parse_size_token_in(token):
    if token is None:
        return None
    t = str(token).strip().replace('"', "").lower()
    if not t:
        return None
    t = re.sub(r'\s+', ' ', t)

    # 1-1/2
    if "-" in t and "/" in t:
        parts = [p.strip() for p in t.split("-", 1)]
        if len(parts) != 2:
            return None
        whole_str, frac_str = parts
        try:
            whole = float(whole_str)
        except:
            return None
        frac_str = frac_str.replace(" ", "")
        try:
            num_str, den_str = frac_str.split("/", 1)
            num = float(num_str)
            den = float(den_str)
            if den == 0:
                return None
            return whole + (num / den)
        except:
            return None

    # 1 1/2
    if " " in t and "/" in t:
        try:
            whole_str, frac_str = t.split(" ", 1)
            whole = float(whole_str)
            frac_str = frac_str.replace(" ", "")
            num_str, den_str = frac_str.split("/", 1)
            num = float(num_str)
            den = float(den_str)
            if den == 0:
                return None
            return whole + (num / den)
        except:
            pass

    # 1/8
    if "/" in t:
        try:
            frac_str = t.replace(" ", "")
            num_str, den_str = frac_str.split("/", 1)
            num = float(num_str)
            den = float(den_str)
            if den == 0:
                return None
            return num / den
        except:
            return None

    # decimal/int
    try:
        return float(t)
    except:
        return None

def snap_in_to_1_32(sz_in):
    # Snap to nearest 1/32", lowest wins when .5 or lower
    if sz_in is None:
        return 1.0/32.0

    n = float(sz_in) * 32.0
    lo = math.floor(n)
    frac = n - lo

    if frac > 0.5:
        snapped = (lo + 1.0) / 32.0
    else:
        snapped = lo / 32.0

    # Floor: never allow < 1/32" (prevents 0" text)
    return max(1.0/32.0, snapped)


def _normalize_list(vals):
    out = []
    for v in vals:
        try:
            vv = float(v)
            if vv > 0.0:
                out.append(snap_in_to_1_32(vv))
        except:
            pass
    if not out:
        return []
    out_sorted = sorted(out)
    dedup = []
    for v in out_sorted:
        if not dedup or abs(v - dedup[-1]) > 1e-9:
            dedup.append(v)
    return dedup

def _build_sizes_from_string(s):
    # Return list in inches, normalized to 1/32"
    if not s or not str(s).strip():
        return _normalize_list(_DEFAULT_SIZES_IN)

    raw = str(s).replace('"', ' ').strip()
    matches = _SIZE_TOKEN_RE.findall(raw)

    vals = []
    for tup in matches:
        tok = next((x for x in tup if x), None)
        v = _parse_size_token_in(tok)
        if v is not None and v > 0.0:
            vals.append(v)

    norm = _normalize_list(vals)
    return norm if norm else _normalize_list(_DEFAULT_SIZES_IN)

ACCEPTABLE_SIZES = _build_sizes_from_string(SizesInput)

def snap_in_to_allowed(sz_in):
    # First snap to 1/32 grid, then snap to allowed list (tie -> lower)
    base = snap_in_to_1_32(sz_in)
    if not ACCEPTABLE_SIZES:
        return base
    return min(ACCEPTABLE_SIZES, key=lambda s: (abs(s - base), s))

def target_size_in_from_ft(size_ft):
    # Revit internal feet -> inches -> policy
    try:
        sz_in = float(size_ft) * 12.0
    except:
        sz_in = 0.0
    return snap_in_to_allowed(sz_in)

def set_text_size_to_target(ttype, tol_ft=1e-10):
    """
    Force TEXT_SIZE parameter to target size.
    Returns (wrote_bool, before_in, after_in)
    """
    try:
        p = ttype.get_Parameter(BuiltInParameter.TEXT_SIZE)
        if p is None or p.IsReadOnly:
            return (False, None, None)
        cur_ft = p.AsDouble()
        if cur_ft is None or cur_ft <= 0:
            return (False, None, None)

        before_in = cur_ft * 12.0
        target_in = target_size_in_from_ft(cur_ft)
        target_ft = target_in / 12.0

        if abs(target_ft - cur_ft) <= tol_ft:
            return (False, before_in, target_in)

        p.Set(target_ft)
        return (True, before_in, target_in)
    except:
        return (False, None, None)

def font_token(s):
    if not s:
        return "Unknown"
    return "".join(w.capitalize() for w in s.split())

def frac32(sz_in):
    n = int(round(float(sz_in) * 32.0))
    if n <= 0:
        return '0"'
    d = 32
    g = math.gcd(n, d)
    n //= g
    d //= g
    w, r = divmod(n, d)
    if w == 0:
        return '0"' if r == 0 else '{}/{}"'.format(r, d)
    return '{}"'.format(w) if r == 0 else '{}-{}/{}"'.format(w, r, d)

# ---------- color read (LINE_COLOR drives text colour) ----------
def _rgb_from_packed(v):
    v = int(v)
    return (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)

_DIGITS_RE = re.compile(r'(\d{1,3})[\s,;]+(\d{1,3})[\s,;]+(\d{1,3})')
_RGB_TOKEN_RE = re.compile(r'(\d{3})-(\d{3})-(\d{3})')

def _parse_vs(vs):
    if not vs:
        return None
    m = _DIGITS_RE.search(vs)
    if not m:
        return None
    r = max(0, min(255, int(m.group(1))))
    g = max(0, min(255, int(m.group(2))))
    b = max(0, min(255, int(m.group(3))))
    return (r, g, b)

def _read_color_param(p):
    if not isinstance(p, Parameter):
        return (None, None, None)
    try:
        raw = p.AsInteger()
        return (int(raw), _rgb_from_packed(int(raw)), "AsInteger")
    except:
        pass
    try:
        vs = p.AsValueString()
        rgb = _parse_vs(vs)
        if rgb:
            return (None, rgb, "AsValueString")
    except:
        pass
    return (None, None, None)

def resolve_style_rgb(ttype, current_name):
    p_line = ttype.get_Parameter(BuiltInParameter.LINE_COLOR)
    p_text = ttype.get_Parameter(BuiltInParameter.TEXT_COLOR)

    raw_l, rgb_l, via_l = _read_color_param(p_line)
    raw_t, rgb_t, via_t = _read_color_param(p_text)

    if rgb_l and max(rgb_l) > 0:
        return rgb_l, "LINE_COLOR." + str(via_l)
    if rgb_t and max(rgb_t) > 0:
        return rgb_t, "TEXT_COLOR." + str(via_t)
    if rgb_l is not None:
        return rgb_l, "LINE_COLOR." + str(via_l)
    if rgb_t is not None:
        return rgb_t, "TEXT_COLOR." + str(via_t)

    m = _RGB_TOKEN_RE.search(current_name or "")
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if max(r, g, b) > 0:
            return (r, g, b), "NameToken"

    return (0, 0, 0), "<none>"

def rgb_token(rgb):
    if not rgb:
        return None
    r, g, b = rgb
    return None if max(r, g, b) == 0 else "{:03d}-{:03d}-{:03d}".format(r, g, b)

def set_black(ttype):
    wrote = False
    for bip in (BuiltInParameter.TEXT_COLOR, BuiltInParameter.LINE_COLOR):
        try:
            p = ttype.get_Parameter(bip)
            if p and not p.IsReadOnly:
                p.Set(0)
                wrote = True
        except:
            pass
    return wrote

# ---------- type props + office tweaks ----------
def read_style_props(ttype):
    size_ft = 0.0
    font = None
    bold = False
    italic = False
    try:
        p = ttype.get_Parameter(BuiltInParameter.TEXT_SIZE)
        size_ft = p.AsDouble() if p else 0.0
    except:
        pass
    try:
        p = ttype.get_Parameter(BuiltInParameter.TEXT_FONT)
        font = p.AsString() if p else None
    except:
        pass
    try:
        p = ttype.get_Parameter(BuiltInParameter.TEXT_STYLE_BOLD)
        bold = (p.AsInteger() == 1) if p else False
    except:
        pass
    try:
        p = ttype.get_Parameter(BuiltInParameter.TEXT_STYLE_ITALIC)
        italic = (p.AsInteger() == 1) if p else False
    except:
        pass
    return size_ft, font, bold, italic

def apply_post_settings(ttype, size_ft):
    if ArialNarrowOnly:
        try:
            p = ttype.get_Parameter(BuiltInParameter.TEXT_FONT)
            if p and (not p.IsReadOnly):
                p.Set("Arial Narrow")
        except:
            pass
    if TransparentOnly:
        try:
            p = ttype.get_Parameter(BuiltInParameter.TEXT_BACKGROUND)
            if p and (not p.IsReadOnly):
                p.Set(1)
        except:
            pass
    if TabTo3_2 and size_ft > 0.0:
        try:
            p = ttype.get_Parameter(BuiltInParameter.TEXT_TAB_SIZE)
            if p and (not p.IsReadOnly):
                p.Set(size_ft * 1.5)
        except:
            pass

# ---------- canonical name (color token LAST) ----------
def canonical_name_for(ttype, allow_color):
    cur = tname(ttype)
    size_ft, font, bold, italic = read_style_props(ttype)

    # Canonical size uses TARGET policy (snapped/allowed), not raw
    sz_in  = target_size_in_from_ft(size_ft)
    size32 = int(round(sz_in * 32.0))

    f2     = "Arial Narrow" if ArialNarrowOnly else (font or "Unknown")
    rgb, src = resolve_style_rgb(ttype, cur)
    tok = rgb_token(rgb) if allow_color else None

    parts = ["{:02d}.{}".format(size32, font_token(f2))]
    if bold:
        parts.append("BOLD")
    if italic:
        parts.append("ITALIC")
    parts.append(frac32(sz_in))
    if tok:
        parts.append(tok)
    return ".".join(parts), sz_in, src

# ---------- family-specific blockers (groups, pinned) ----------
def is_in_group(e):
    try:
        gid = e.GroupId
        return gid and gid.IntegerValue > 0
    except:
        return False

def group_info(e):
    try:
        gid = e.GroupId
        if gid and gid.IntegerValue > 0:
            g = doc.GetElement(gid)
            return (gid.IntegerValue, getattr(g, "Name", "<group>"))
    except:
        pass
    return (None, None)

def elem_view_name(e):
    try:
        v = doc.GetElement(e.OwnerViewId)
        return v.Name if v else "<no view>"
    except:
        return "<no view>"

# ================= MAIN =================
log = []
sizes_mode = "IN[4] specified" if (SizesInput and SizesInput.strip()) else "Defaults"

log += [
    "Family label/text style conversion",
    "----------------------------------",
    "Document: {}".format(getattr(doc, "Title", "<doc>")),
    "Family document: {}".format(doc.IsFamilyDocument),
    "AllowColorRGB: {}".format(AllowColorRGB),
    "Size policy: snap to nearest 1/32\" increment (lowest if .5 or lower)",
    "Allowed sizes mode: {}".format(sizes_mode),
    "Allowed sizes: {}".format(", ".join([frac32(s) for s in ACCEPTABLE_SIZES]) if ACCEPTABLE_SIZES else "<none>"),
    ""
]

if not doc.IsFamilyDocument:
    OUT = log + ["Open a FAMILY (.rfa) and run this node."]
else:
    types = list(
        FilteredElementCollector(doc)
        .OfClass(TextElementType)
        .WhereElementIsElementType()
    )
    elems = list(FilteredElementCollector(doc).OfClass(TextElement))

    if not types:
        OUT = log + ["No TextElementType styles found."]
    else:
        id2type  = {}
        id2canon = {}
        preview  = []

        for tt in types:
            tid = tt.Id.IntegerValue
            id2type[tid] = tt
            can, target_in, src = canonical_name_for(tt, AllowColorRGB)
            id2canon[tid] = can
            preview.append("  '{}' → '{}' (target size {}, color via {})".format(
                tname(tt), can, frac32(target_in), src
            ))

        log.append("Preview (style → canonical):")
        log.extend(preview)
        log.append("")

        # Group by canonical
        canon2ids = {}
        for tid, can in id2canon.items():
            canon2ids.setdefault(can, []).append(tid)

        # Build duplicate -> target mapping
        dup_to_target = {}
        for can, ids in canon2ids.items():
            if len(ids) <= 1:
                continue
            keep_id = None
            for tid in ids:
                if tname(id2type[tid]) == can:
                    keep_id = tid
                    break
            if keep_id is None:
                keep_id = ids[0]
            for tid in ids:
                if tid != keep_id:
                    dup_to_target[tid] = ElementId(keep_id)

        t = Transaction(doc, "Label text style conversion")
        t.Start()
        try:
            # 0) If disallowing color: force BLACK
            if not AllowColorRGB:
                forced = 0
                for tt in id2type.values():
                    if set_black(tt):
                        forced += 1
                log.append("Forced BLACK on styles: {}".format(forced))

            # 1) Enforce TEXT_SIZE to match the target size policy
            snapped = 0
            samples = []
            for tt in id2type.values():
                wrote, before_in, after_in = set_text_size_to_target(tt)
                if wrote:
                    snapped += 1
                    samples.append("  {}: {} → {}".format(tname(tt), frac32(before_in), frac32(after_in)))
            log.append("Snapped TEXT_SIZE on styles: {}".format(snapped))
            for s in samples[:8]:
                log.append(s)
            if len(samples) > 8:
                log.append("  ... {} more".format(len(samples) - 8))

            # 2) Rename keeper of each canonical group to the canonical name
            renamed = 0
            for can, ids in canon2ids.items():
                keep_id = None
                for tid in ids:
                    if tname(id2type[tid]) == can:
                        keep_id = tid
                        break
                if keep_id is None:
                    keep_id = ids[0]
                tt_keep = id2type[keep_id]
                if tname(tt_keep) != can and set_tname(tt_keep, can):
                    renamed += 1
            if renamed:
                log.append("Renamed styles to canonical: {}".format(renamed))

            # 3) Office tweaks (after size enforcement; tab uses final size)
            for tt in id2type.values():
                size_ft, _, _, _ = read_style_props(tt)
                apply_post_settings(tt, size_ft)

            # 4) Retype ALL TextElement instances that still reference a duplicate
            retyped = 0
            skipped_group = []
            skipped_err = []

            if dup_to_target and elems:
                for e in elems:
                    try:
                        cur_tid = e.GetTypeId().IntegerValue
                        if cur_tid not in dup_to_target:
                            continue

                        if is_in_group(e):
                            gid, gname = group_info(e)
                            skipped_group.append(
                                "In group '{}' (Id {}), View '{}', TextElement Id {}".format(
                                    gname or "<group>", gid or -1, elem_view_name(e), e.Id.IntegerValue
                                )
                            )
                            continue

                        was_pinned = False
                        try:
                            was_pinned = bool(e.Pinned)
                        except:
                            pass

                        try:
                            if was_pinned:
                                try:
                                    e.Pinned = False
                                except:
                                    pass

                            target_id = dup_to_target[cur_tid]
                            try:
                                e.ChangeTypeId(target_id)
                            except TypeError:
                                p = e.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM)
                                if p is None or p.IsReadOnly:
                                    raise
                                p.Set(target_id)

                            retyped += 1

                            if was_pinned:
                                try:
                                    e.Pinned = True
                                except:
                                    pass
                        except Exception as ex_inner:
                            skipped_err.append("Id {}: {}".format(e.Id.IntegerValue, str(ex_inner)))
                    except Exception as ex:
                        skipped_err.append("Id {}: {}".format(e.Id.IntegerValue, str(ex)))

            # 5) Delete duplicate styles only if unused now
            used = set()
            for e in elems:
                try:
                    used.add(e.GetTypeId().IntegerValue)
                except:
                    pass

            deleted = 0
            kept = 0
            for tid, target in dup_to_target.items():
                if tid in used:
                    kept += 1
                else:
                    try:
                        doc.Delete(ElementId(tid))
                        deleted += 1
                    except:
                        kept += 1

            # summary
            log.append("Retyped label/text instances: {}".format(retyped))
            if deleted:
                log.append("Deleted duplicate styles: {}".format(deleted))
            if kept:
                log.append("Kept styles still referenced: {}".format(kept))
            if skipped_group:
                log.append("Skipped (in groups): {}".format(len(skipped_group)))
                for s in skipped_group[:6]:
                    log.append("  " + s)
                if len(skipped_group) > 6:
                    log.append("  ... {} more".format(len(skipped_group) - 6))
            if skipped_err:
                log.append("Skipped (errors) on instances: {}".format(len(skipped_err)))
                for s in skipped_err[:6]:
                    log.append("  " + s)
                if len(skipped_err) > 6:
                    log.append("  ... {} more".format(len(skipped_err) - 6))

            t.Commit()
        except Exception as ex:
            t.RollBack()
            log += ["An error occurred:", str(ex), repr(type(ex))]

        OUT = log
