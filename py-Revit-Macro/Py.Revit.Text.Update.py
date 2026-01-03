# Text style conversion â€“ color policy aware (PROJECT TextNoteTypes) 
# - AllowColorRGB=True  â†’ keep colors (token at end)
# - AllowColorRGB=False â†’ force all types to BLACK, strip color tokens, merge
#
# Size policy:
# - ALWAYS snap to nearest 1/32" (lowest if .5 or lower), with a HARD FLOOR of 1/32".
# - If IN[4] specified: that list becomes the ONLY allowed sizes (normalized to 1/32"),
#   and we snap to nearest allowed (tie -> lower).
# - If IN[4] blank: defaults apply.
#
# Revit 2025+, Dynamo Revit 3.3, Python 3 (CPython)
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
    FilteredElementCollector, TextNoteType, TextNote,
    BuiltInParameter, Parameter,
    Transaction, ElementId, WorksharingUtils
)

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

# ------------ inputs ------------
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

# ------------ basics ------------
def safe_title(d):
    try:
        return d.Title
    except:
        return "<unknown>"

def get_types(d):
    return list(FilteredElementCollector(d).OfClass(TextNoteType).ToElements())

def get_notes(d):
    return list(FilteredElementCollector(d).OfClass(TextNote).ToElements())

def type_name(t):
    try:
        p = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p:
            n = p.AsString()
            if n:
                return n
    except:
        pass
    try:
        return t.Name
    except:
        return "<unnamed>"

def set_type_name(t, new_name):
    try:
        p = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and (not p.IsReadOnly):
            p.Set(new_name)
            return True
    except:
        pass
    try:
        t.Name = new_name
        return True
    except:
        return False

# ------------ size parsing + snapping ------------
_DEFAULT_SIZES_IN = [1.0/16.0, 3.0/32.0]

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
    # HARD FLOOR: never below 1/32" to prevent 0" text
    if sz_in is None:
        return 1.0/32.0

    n = float(sz_in) * 32.0
    lo = math.floor(n)
    frac = n - lo

    if frac > 0.5:
        snapped = (lo + 1.0) / 32.0
    else:
        snapped = lo / 32.0

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
        if (not dedup) or abs(v - dedup[-1]) > 1e-9:
            dedup.append(v)
    return dedup

def _build_sizes_from_string(s):
    # Return list in inches, normalized to 1/32" (and floored at 1/32")
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
    # 1) snap to 1/32 grid (floored), then 2) snap to allowed list (tie -> lower)
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

def frac32(sz_in):
    # display token only; floor also applied for safety
    sz_in = max(1.0/32.0, float(sz_in or 0.0))
    num = int(round(sz_in * 32.0))
    if num <= 0:
        return '1/32"'  # should never hit due to floor
    den = 32
    g = math.gcd(num, den)
    n, d = num // g, den // g
    whole, rem = n // d, n % d
    if whole == 0:
        return '{}/{}"'.format(rem, d) if rem else '0"'
    return '{}"'.format(whole) if rem == 0 else '{}-{}/{}"'.format(whole, rem, d)

def font_token(s):
    if not s:
        return "Unknown"
    return "".join(w.capitalize() for w in s.split())

def set_text_size_to_target(ttype, tol_ft=1e-10):
    # Force TEXT_SIZE so style property matches canonical size token
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

# ------------ color helpers ------------
# Packed: val = R + (G<<8) + (B<<16)
def rgb_from_packed(val):
    v = int(val)
    return (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)

_DIGITS_RE = re.compile(r'(\d{1,3})[\s,;]+(\d{1,3})[\s,;]+(\d{1,3})')
_RGB_TOKEN_RE = re.compile(r'(\d{3})-(\d{3})-(\d{3})')

def parse_vs_rgb(vs):
    if not vs:
        return None
    m = _DIGITS_RE.search(vs)
    if not m:
        return None
    r = max(0, min(255, int(m.group(1))))
    g = max(0, min(255, int(m.group(2))))
    b = max(0, min(255, int(m.group(3))))
    return (r, g, b)

def parse_rgb_token_from_name(name):
    m = _RGB_TOKEN_RE.search(name or "")
    if not m:
        return None
    r = int(m.group(1))
    g = int(m.group(2))
    b = int(m.group(3))
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))

def read_color_param(p):
    if not isinstance(p, Parameter):
        return (None, None, None)
    try:
        raw = p.AsInteger()
        if raw is not None:
            return (int(raw), rgb_from_packed(int(raw)), "AsInteger")
    except:
        pass
    try:
        vs = p.AsValueString()
        rgb = parse_vs_rgb(vs)
        if rgb:
            return (None, rgb, "AsValueString")
    except:
        pass
    return (None, None, None)

def resolve_style_rgb(ttype, current_name):
    # Prefer LINE_COLOR then TEXT_COLOR, then name token, else black
    p_line = ttype.get_Parameter(BuiltInParameter.LINE_COLOR)
    p_text = ttype.get_Parameter(BuiltInParameter.TEXT_COLOR)

    raw_l, rgb_l, via_l = read_color_param(p_line)
    raw_t, rgb_t, via_t = read_color_param(p_text)

    if rgb_l and max(rgb_l) > 0:
        return (rgb_l, raw_t, raw_l, "LINE_COLOR." + str(via_l))
    if rgb_t and max(rgb_t) > 0:
        return (rgb_t, raw_t, raw_l, "TEXT_COLOR." + str(via_t))
    if rgb_l is not None:
        return (rgb_l, raw_t, raw_l, "LINE_COLOR." + str(via_l))
    if rgb_t is not None:
        return (rgb_t, raw_t, raw_l, "TEXT_COLOR." + str(via_t))

    tok = parse_rgb_token_from_name(current_name)
    if tok and max(tok) > 0:
        return (tok, raw_t, raw_l, "NameToken")

    return ((0, 0, 0), raw_t, raw_l, "<none>")

def rgb_token_str(rgb):
    if not rgb:
        return None
    r, g, b = rgb
    if max(r, g, b) == 0:
        return None
    return "{:03d}-{:03d}-{:03d}".format(r, g, b)

def set_black(ttype):
    wrote = False
    for bip in (BuiltInParameter.TEXT_COLOR, BuiltInParameter.LINE_COLOR):
        try:
            p = ttype.get_Parameter(bip)
            if p and (not p.IsReadOnly):
                p.Set(0)
                wrote = True
        except:
            pass
    return wrote

# ------------ style props + office tweaks ------------
def read_style_props(ttype):
    size_ft, font, bold, italic = 0.0, None, False, False
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

# ------------ canonical name ------------
def canonical_name_for(ttype, allow_color):
    cur = type_name(ttype)

    size_ft, font, bold, italic = read_style_props(ttype)

    # IMPORTANT: canonical size is based on TARGET size policy
    sz_in  = target_size_in_from_ft(size_ft)
    size32 = int(round(sz_in * 32.0))

    f2 = "Arial Narrow" if ArialNarrowOnly else (font or "Unknown")

    rgb, raw_t, raw_l, src = resolve_style_rgb(ttype, cur)
    token = rgb_token_str(rgb) if allow_color else None

    parts = ["{:02d}.{}".format(size32, font_token(f2))]
    if bold:
        parts.append("BOLD")
    if italic:
        parts.append("ITALIC")
    parts.append(frac32(sz_in))   # size token
    if token:
        parts.append(token)       # color LAST
    return ".".join(parts), (sz_in, rgb, raw_t, raw_l, src)

# ------------ blockers for notes ------------
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

def note_view_name(n):
    try:
        v = doc.GetElement(n.OwnerViewId)
        return v.Name if v else "<no view>"
    except:
        return "<no view>"

def checkout_status(eid):
    try:
        return str(WorksharingUtils.GetCheckoutStatus(doc, eid))
    except:
        return "Unknown"

def ws_tooltip(eid):
    try:
        info = WorksharingUtils.GetWorksharingTooltipInfo(doc, eid)
        return (info.Owner, info.Borrower, info.WorksetName)
    except:
        return (None, None, None)

# ================= MAIN =================
log = []
types = get_types(doc)
notes = get_notes(doc)

sizes_mode = "IN[4] specified" if (SizesInput and SizesInput.strip()) else "Defaults"

log += [
    "Text style conversion (PROJECT)",
    "-------------------------------",
    "Document: {}".format(safe_title(doc)),
    "Types: {}".format(len(types)),
    "Notes: {}".format(len(notes)),
    "AllowColorRGB: {}".format(AllowColorRGB),
    "Size policy: snap to nearest 1/32\" (lowest if .5 or lower) with floor 1/32\"",
    "Allowed sizes mode: {}".format(sizes_mode),
    "Allowed sizes: {}".format(", ".join([frac32(s) for s in ACCEPTABLE_SIZES]) if ACCEPTABLE_SIZES else "<none>"),
    "Note: For TextNotes, size is controlled by TextNoteType TEXT_SIZE; no per-TextNote size to set.",
    ""
]

if not types:
    OUT = log + ["No TextNoteTypes found."]
else:
    # Read-only canonical preview first
    id2type = {}
    id2canon = {}
    id2target_in = {}
    preview = []

    for tt in types:
        tid = tt.Id.IntegerValue
        id2type[tid] = tt
        can, dbg = canonical_name_for(tt, AllowColorRGB)
        target_in, rgb, raw_t, raw_l, src = dbg
        id2canon[tid] = can
        id2target_in[tid] = target_in
        preview.append(
            "  '{}' | targetSize={} | TEXT_COLOR raw={} | LINE_COLOR raw={} | resolvedRGB={} via {} | â†’ '{}'".format(
                type_name(tt), frac32(target_in), raw_t, raw_l, rgb, src, can
            )
        )

    log.append("Preview (current â†’ canonical using target sizes):")
    log.extend(preview)
    log.append("")

    # Group by canonical
    canon2ids = {}
    for tid, can in id2canon.items():
        canon2ids.setdefault(can, []).append(tid)

    # Usage counts for keeper selection
    use_counts = {}
    for n in notes:
        try:
            tidint = n.GetTypeId().IntegerValue
        except:
            continue
        use_counts[tidint] = use_counts.get(tidint, 0) + 1

    # Choose keeper per canonical group
    keeper_for_canon = {}
    dup_to_target = {}

    for can, ids in canon2ids.items():
        if len(ids) == 1:
            keeper_for_canon[can] = ids[0]
            continue

        keep = None
        for tid in ids:
            if type_name(id2type[tid]) == can:
                keep = tid
                break
        if keep is None:
            keep = sorted(ids, key=lambda k: -use_counts.get(k, 0))[0]

        keeper_for_canon[can] = keep
        for tid in ids:
            if tid != keep:
                dup_to_target[tid] = ElementId(keep)

    t = Transaction(doc, "Text style conversion")
    t.Start()
    try:
        # 0) If colors are NOT allowed: set all styles to BLACK (both params if possible)
        forced_black = 0
        if not AllowColorRGB:
            for tt in id2type.values():
                if set_black(tt):
                    forced_black += 1
            log.append("Forced black on types (TEXT_COLOR/LINE_COLOR): {}".format(forced_black))

        # 1) Enforce TEXT_SIZE to match target sizes
        snapped = 0
        snap_samples = []
        for tid, tt in id2type.items():
            wrote, before_in, after_in = set_text_size_to_target(tt)
            if wrote:
                snapped += 1
                snap_samples.append("  {}: {} â†’ {}".format(type_name(tt), frac32(before_in), frac32(after_in)))
        log.append("Snapped TEXT_SIZE to policy/allowed sizes: {}".format(snapped))
        for s in snap_samples[:8]:
            log.append(s)
        if len(snap_samples) > 8:
            log.append("  ... {} more".format(len(snap_samples) - 8))

        # 2) Rename each keeper to its canonical name
        renamed = 0
        for can, keep_id in keeper_for_canon.items():
            tt_keep = id2type[keep_id]
            if type_name(tt_keep) != can and set_type_name(tt_keep, can):
                renamed += 1
        if renamed:
            log.append("Renamed keeper types to canonical: {}".format(renamed))

        # 3) Office tweaks for all types (Tab uses final size)
        for tid, tt in id2type.items():
            s_ft, _, _, _ = read_style_props(tt)
            apply_post_settings(tt, s_ft)

        # 4) Post-check: verify TEXT_SIZE matches the target size token we expect
        mismatched = 0
        for tid, tt in id2type.items():
            try:
                p = tt.get_Parameter(BuiltInParameter.TEXT_SIZE)
                cur_ft = p.AsDouble() if p else 0.0
                cur_in = snap_in_to_1_32(cur_ft * 12.0)
                tgt_in = id2target_in.get(tid, None)
                if tgt_in is None:
                    continue
                if abs(cur_in - tgt_in) > 1e-9:
                    mismatched += 1
            except:
                pass
        log.append("Post-check mismatched TEXT_SIZE vs target size: {}".format(mismatched))

        # 5) Retype notes dupâ†’target (respect groups, pinned, worksharing)
        retyped = 0
        skipped_group = []
        skipped_owned = []
        skipped_error = []

        for n in notes:
            try:
                nid = n.GetTypeId().IntegerValue
            except:
                continue
            if nid not in dup_to_target:
                continue

            target_eid = dup_to_target[nid]

            if is_in_group(n):
                gid, gname = group_info(n)
                skipped_group.append(
                    "In group '{}' (Id {}), View '{}', Note Id {}".format(
                        gname or "<group>", gid or -1, note_view_name(n), n.Id.IntegerValue
                    )
                )
                continue

            status = checkout_status(n.Id)
            if "Owned" in status or "Borrowed" in status or "NotEditable" in status:
                owner, borrower, ws = ws_tooltip(n.Id)
                skipped_owned.append(
                    "Owned/Borrowed ({} / {}), Workset '{}', View '{}', Note Id {}".format(
                        owner or "-", borrower or "-", ws or "-",
                        note_view_name(n), n.Id.IntegerValue
                    )
                )
                continue

            was_pinned = False
            try:
                was_pinned = bool(n.Pinned)
            except:
                pass

            try:
                if was_pinned:
                    try:
                        n.Pinned = False
                    except:
                        pass

                try:
                    n.ChangeTypeId(target_eid)
                except TypeError:
                    p_type = n.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM)
                    if p_type is None or p_type.IsReadOnly:
                        raise
                    p_type.Set(target_eid)

                retyped += 1

                if was_pinned:
                    try:
                        n.Pinned = True
                    except:
                        pass

            except Exception as rex:
                skipped_error.append(
                    "Error '{}', View '{}', Note Id {}".format(
                        str(rex), note_view_name(n), n.Id.IntegerValue
                    )
                )

        # 6) Delete unused duplicates
        used_ids = set()
        for n in notes:
            try:
                used_ids.add(n.GetTypeId().IntegerValue)
            except:
                pass

        deleted = 0
        kept = 0
        for tid, target_eid in dup_to_target.items():
            if tid in used_ids:
                kept += 1
            else:
                try:
                    doc.Delete(id2type[tid].Id)
                    deleted += 1
                except:
                    kept += 1

        # Summary
        log.append("Retyped notes: {}".format(retyped))
        if deleted:
            log.append("Deleted duplicate types: {}".format(deleted))
        if kept:
            log.append("Kept duplicate types still in use: {}".format(kept))
        if skipped_group:
            log.append("Skipped (in groups): {}".format(len(skipped_group)))
            for s in skipped_group[:6]:
                log.append("  " + s)
            if len(skipped_group) > 6:
                log.append("  ... {} more".format(len(skipped_group) - 6))
        if skipped_owned:
            log.append("Skipped (workshared / not editable): {}".format(len(skipped_owned)))
            for s in skipped_owned[:6]:
                log.append("  " + s)
            if len(skipped_owned) > 6:
                log.append("  ... {} more".format(len(skipped_owned) - 6))
        if skipped_error:
            log.append("Skipped (other errors): {}".format(len(skipped_error)))
            for s in skipped_error[:6]:
                log.append("  " + s)
            if len(skipped_error) > 6:
                log.append("  ... {} more".format(len(skipped_error) - 6))

        t.Commit()

    except Exception as ex:
        t.RollBack()
        log += ["An error occurred:", str(ex), repr(type(ex))]

OUT = log
