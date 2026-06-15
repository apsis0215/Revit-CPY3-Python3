# py-Text-Style-Family-Labels.py
# V06-10
# IN[0]=FontPatternsCSV(str)       # filter, e.g. "", "Arial Narrow", "Arial*, *helvetica*"; supports * and ?
# IN[1]=TransparentOnly(bool)
# IN[2]=TabTo3_2(bool)
# IN[3]=AllowColorRGB(bool)
# IN[4]=TreatLabelAsBlue(bool)     # label/tag pool: black<->blue mapping
# IN[5]=CreateMissingSizes(bool)   # uses IN[6] sizes; does not require IN[7]=True
# IN[6]=SizesInput(str)            # input sizes, e.g. "3/32, 1/4"
# IN[7]=InputSizesOnly(bool)       # False=snap all to nearest 1/32"; True=limit to IN[6] only
# IN[8]=TreatTextAsBlue(bool)      # text pool: black<->blue mapping
# OUT=list[str]

#001-Imports
import clr, math, re, fnmatch

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInParameter, StorageType,
    TextElementType, TextNoteType, ElementId, Transaction
)

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

clr.AddReference("System")
from System import Int64

doc = DocumentManager.Instance.CurrentDBDocument

#002-Input helpers
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

#003-Inputs
FontPatternsCSV      = _s(0, "Arial Narrow")
TransparentOnly      = _b(1, False)
TabTo3_2             = _b(2, False)
AllowColorRGB        = _b(3, False)
TreatLabelAsBlue     = _b(4, False)
CreateMissingSizes   = _b(5, False)
SizesInput           = _s(6, "")
InputSizesOnly       = _b(7, False)
TreatTextAsBlue      = _b(8, False)

BLUE  = (0, 0, 128)
BLACK = (0, 0, 0)

#004-ElementId helpers
def eid_val(eid, default=-1):
    if eid is None:
        return default
    try:
        if hasattr(eid, "Value"):
            return int(eid.Value)
    except:
        pass
    try:
        if hasattr(eid, "IntegerValue"):
            return int(eid.IntegerValue)
    except:
        pass
    try:
        return int(eid)
    except:
        return default

def make_eid(v):
    try:
        return ElementId(int(v))
    except:
        return ElementId(Int64(v))

INVALID_ID_INT = eid_val(ElementId.InvalidElementId, -1)

#005-Type name helpers
def get_sym(tt):
    try:
        p = tt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p:
            s = p.AsString()
            return s if s else ""
    except:
        pass
    return ""

def set_sym(tt, name):
    try:
        p = tt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and (not p.IsReadOnly):
            p.Set(name)
            return True
    except:
        pass

    try:
        tt.Name = name
        return True
    except:
        return False

def tname(tt):
    s = get_sym(tt)
    if s:
        return s
    try:
        return tt.Name
    except:
        return "<unnamed>"

#006-Font filter/target helpers
def normalize_known_font_name(font_name):
    # Normalize known default font casing for Revit TEXT_FONT writes.
    s = str(font_name or "").strip()
    if s.lower() == "arial narrow":
        return "Arial Narrow"
    return s

def parse_font_patterns(csv_text):
    # Empty IN[0] defaults to Arial Narrow.
    raw = str(csv_text or "").strip()
    if not raw:
        raw = "Arial Narrow"

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts if parts else ["Arial Narrow"]

FONT_PATTERNS = parse_font_patterns(FontPatternsCSV)

FALLBACK_FONT = "Arial Narrow"
DEFAULT_FONT = FALLBACK_FONT

def font_matches_patterns(font_name):
    # Match against Revit-reported font name only.
    # No .NET/system font lookup is used.
    s = str(font_name or "").strip()
    if not s:
        return False

    s_low = s.lower()
    for pat in FONT_PATTERNS:
        if fnmatch.fnmatchcase(s_low, pat.lower()):
            return True

    return False

def target_font_for(font_name):
    # If current Revit font matches IN[0], keep it.
    # If not, force to Arial Narrow.
    cur = str(font_name or "").strip()
    if cur and font_matches_patterns(cur):
        return normalize_known_font_name(cur), False
    return FALLBACK_FONT, True

def font_token(font_name):
    # Convert "Arial Narrow" to "ArialNarrow".
    s = str(font_name or FALLBACK_FONT).strip()
    s = re.sub(r"[^A-Za-z0-9]+", " ", s).strip()

    if not s:
        return "UnknownFont"

    return "".join([w[:1].upper() + w[1:] for w in s.split()])

# Stores intended/updated font during this run.
# This prevents stale reads from producing old names.
EFFECTIVE_FONT_BY_ID = {}

#007-Size parsing helpers
def _parse_in(tok):
    if tok is None:
        return None

    s = str(tok).strip().replace('"', '')
    if not s:
        return None

    s = re.sub(r'\s+', ' ', s)

    if "-" in s and "/" in s:
        a, b = [x.strip() for x in s.split("-", 1)]
        try:
            whole = float(a)
            num, den = [float(x) for x in b.replace(" ", "").split("/", 1)]
            if den == 0:
                return None
            return whole + (num / den)
        except:
            return None

    if " " in s and "/" in s:
        try:
            a, b = s.split(" ", 1)
            whole = float(a)
            num, den = [float(x) for x in b.replace(" ", "").split("/", 1)]
            if den == 0:
                return None
            return whole + (num / den)
        except:
            pass

    if "/" in s:
        try:
            num, den = [float(x) for x in s.replace(" ", "").split("/", 1)]
            if den == 0:
                return None
            return num / den
        except:
            return None

    try:
        return float(s)
    except:
        return None

def snap_32(inches):
    if inches is None:
        return 1.0 / 32.0

    n = float(inches) * 32.0
    lo = math.floor(n)
    frac = n - lo

    return max(
        1.0 / 32.0,
        ((lo + 1.0) / 32.0) if frac > 0.5 else (lo / 32.0)
    )

def parse_sizes(s):
    if not str(s).strip():
        return []

    raw = str(s).replace(",", " ")
    tokens = [t for t in re.split(r'[\s;]+', raw) if t.strip()]
    vals = []

    for t in tokens:
        v = _parse_in(t)
        if v and v > 0:
            vals.append(snap_32(v))

    return sorted(set(vals))

ALLOWED_IN = parse_sizes(SizesInput)
INPUT_SIZES_AVAILABLE = bool(SizesInput.strip()) and len(ALLOWED_IN) > 0
LIMIT_TO_INPUT_SIZES = bool(InputSizesOnly and INPUT_SIZES_AVAILABLE)

def nearest_allowed(inches):
    base = snap_32(inches)
    if not ALLOWED_IN:
        return base
    return min(ALLOWED_IN, key=lambda s: (abs(s - base), s))

def target_size_in(inches):
    # Always snap to nearest 1/32".
    # If IN[7]=True and IN[6] has sizes, limit to nearest input size.
    base = snap_32(inches)
    if LIMIT_TO_INPUT_SIZES:
        return nearest_allowed(base)
    return base

def frac32(inches):
    n = int(round(float(inches) * 32.0))
    d = 32
    g = math.gcd(n, d)

    n //= g
    d //= g

    w, r = divmod(n, d)

    if w == 0:
        return '0"' if r == 0 else '{}/{}"'.format(r, d)

    return '{}"'.format(w) if r == 0 else '{}-{}/{}"'.format(w, r, d)

#008-Color helpers
def _rgb_from_packed(v):
    v = int(v)
    r = (v & 0xFF)
    g = (v >> 8) & 0xFF
    b = (v >> 16) & 0xFF
    return (r, g, b)

def pack_rgb(rgb):
    r, g, b = rgb

    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))

    return int(r | (g << 8) | (b << 16))

def set_rgb(tt, rgb):
    val = pack_rgb(rgb)

    for bip in (BuiltInParameter.TEXT_COLOR, BuiltInParameter.LINE_COLOR):
        try:
            p = tt.get_Parameter(bip)
            if p and (not p.IsReadOnly):
                p.Set(val)
        except:
            pass

def is_blue(rgb):
    return rgb == BLUE

def is_black(rgb):
    return rgb == BLACK

def is_other(rgb):
    return (rgb is not None) and (not is_blue(rgb)) and (not is_black(rgb))

_COLOR_WORDS = re.compile(
    r"\s+(red|green|blue|black|white|cyan|magenta|yellow|gray|grey)\s*$",
    re.IGNORECASE
)

_COLOR_WORD_TO_RGB = {
    "red":     (255, 0, 0),
    "green":   (0, 255, 0),
    "blue":    (0, 0, 255),
    "black":   (0, 0, 0),
    "white":   (255, 255, 255),
    "cyan":    (0, 255, 255),
    "magenta": (255, 0, 255),
    "yellow":  (255, 255, 0),
    "gray":    (128, 128, 128),
    "grey":    (128, 128, 128),
}

def _color_word_rgb_from_name(nm):
    if not nm:
        return None

    m = _COLOR_WORDS.search(nm.strip())
    if not m:
        return None

    return _COLOR_WORD_TO_RGB.get(m.group(1).lower())

def resolve_style_rgb(tt):
    # Read color word before name cleanup, used for legacy names like "... red".
    nm = tname(tt)

    if AllowColorRGB:
        w_rgb = _color_word_rgb_from_name(nm)
        if w_rgb and (w_rgb != BLUE) and (w_rgb != BLACK):
            return w_rgb

    for bip in (BuiltInParameter.LINE_COLOR, BuiltInParameter.TEXT_COLOR):
        try:
            p = tt.get_Parameter(bip)
            if p:
                raw = p.AsInteger()
                return _rgb_from_packed(int(raw))
        except:
            pass

    return BLACK

def normalize_color(rgb, allow_rgb, treat_as_blue):
    if rgb is None:
        rgb = BLACK

    if allow_rgb:
        if is_other(rgb):
            return rgb

        if treat_as_blue:
            return BLUE if is_black(rgb) else rgb

        return BLACK if is_blue(rgb) else rgb

    return BLUE if treat_as_blue else BLACK

def rgb_suffix_if_needed(final_rgb):
    # Token format is RGB order: ###-###-###.
    if not AllowColorRGB:
        return None

    if is_blue(final_rgb) or is_black(final_rgb):
        return None

    r, g, b = final_rgb
    return ".{:03d}-{:03d}-{:03d}".format(r, g, b)

#009-Style property helpers
def read_props(tt):
    size_ft = 0.0
    font = None
    bold = False
    italic = False

    try:
        p = tt.get_Parameter(BuiltInParameter.TEXT_SIZE)
        size_ft = p.AsDouble() if p else 0.0
    except:
        pass

    try:
        p = tt.get_Parameter(BuiltInParameter.TEXT_FONT)
        font = p.AsString() if p else None
    except:
        pass

    try:
        p = tt.get_Parameter(BuiltInParameter.TEXT_STYLE_BOLD)
        bold = (p.AsInteger() == 1) if p else False
    except:
        pass

    try:
        p = tt.get_Parameter(BuiltInParameter.TEXT_STYLE_ITALIC)
        italic = (p.AsInteger() == 1) if p else False
    except:
        pass

    return size_ft, font, bold, italic

def set_font(tt, font_name):
    # Write TEXT_FONT on the label/text style type.
    try:
        p = tt.get_Parameter(BuiltInParameter.TEXT_FONT)
        if p and (not p.IsReadOnly) and p.StorageType == StorageType.String:
            return bool(p.Set(str(normalize_known_font_name(font_name))))
    except:
        pass
    return False

def apply_font_policy(tt):
    # Update font first, then store effective font for naming.
    tid = eid_val(tt.Id, INVALID_ID_INT)
    _size_ft, cur_font, _bold, _italic = read_props(tt)

    target_font, forced = target_font_for(cur_font)
    target_font = normalize_known_font_name(target_font)

    ok = True

    if str(cur_font or "").strip() != target_font:
        ok = set_font(tt, target_font)

    final_font = target_font if ok else str(cur_font or target_font).strip()

    if tid != INVALID_ID_INT:
        EFFECTIVE_FONT_BY_ID[tid] = final_font

    return cur_font, final_font, forced, ok

def apply_office(tt, size_ft):
    if TransparentOnly:
        try:
            p = tt.get_Parameter(BuiltInParameter.TEXT_BACKGROUND)
            if p and (not p.IsReadOnly):
                p.Set(1)
        except:
            pass

    if TabTo3_2 and size_ft and size_ft > 0.0:
        try:
            p = tt.get_Parameter(BuiltInParameter.TEXT_TAB_SIZE)
            if p and (not p.IsReadOnly):
                p.Set(size_ft * 1.5)
        except:
            pass

#010-Name cleaning and canonical names
_RGB_DASH_RE = re.compile(r'\.\d{3}-\d{3}-\d{3}(?=\.DUP\d+$|$)', re.IGNORECASE)
_DUP_RE      = re.compile(r'\.DUP\d+$', re.IGNORECASE)
_SUFFIX_NUM  = re.compile(r"\s+\d+$")

def clean_display_name(nm):
    s = (nm or "").strip()

    s = s.replace("â€œ", '"').replace("â€", '"').replace("â€³", '"')
    s = re.sub(_DUP_RE, "", s).strip()
    s = re.sub(_RGB_DASH_RE, "", s).strip()
    s = re.sub(_COLOR_WORDS, "", s).strip()
    s = re.sub(_SUFFIX_NUM, "", s).strip()
    s = re.sub(r"\s+", " ", s)

    return s

def canonical_for(tt, base_font=DEFAULT_FONT, treat_as_blue=True):
    size_ft, font, bold, italic = read_props(tt)
    tid = eid_val(tt.Id, INVALID_ID_INT)

    # Name must follow updated/effective font.
    use_font = EFFECTIVE_FONT_BY_ID.get(tid, None)
    if not use_font:
        use_font, _forced = target_font_for(font)

    raw_in = (size_ft * 12.0) if (size_ft and size_ft > 0) else 3.0 / 32.0
    sz_in = target_size_in(raw_in)
    size32 = int(round(sz_in * 32.0))

    parts = ["{:02d}".format(size32), font_token(use_font)]

    if bold:
        parts.append("BOLD")

    if italic:
        parts.append("ITALIC")

    parts.append(frac32(sz_in))

    cur_rgb = resolve_style_rgb(tt)
    final_rgb = normalize_color(cur_rgb, AllowColorRGB, treat_as_blue)
    suffix = rgb_suffix_if_needed(final_rgb)

    base = ".".join(parts)
    return (base + (suffix if suffix else "")), final_rgb

#011-Rewire helpers
def change_type(e, target_id):
    try:
        e.ChangeTypeId(target_id)
        return True
    except:
        pass

    try:
        p = e.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM)
        if p and (not p.IsReadOnly):
            p.Set(target_id)
            return True
    except:
        pass

    return False

def rewire_element_params(e, map_ids):
    changed = 0

    try:
        for p in e.Parameters:
            try:
                if p and (not p.IsReadOnly) and p.StorageType == StorageType.ElementId:
                    vi = eid_val(p.AsElementId(), INVALID_ID_INT)
                    if vi in map_ids:
                        p.Set(map_ids[vi])
                        changed += 1
            except:
                pass
    except:
        pass

    return changed

def rewire_familytypes(doc, map_ids):
    changed = 0

    try:
        fm = doc.FamilyManager
    except:
        return 0

    fam_params = []

    try:
        for fp in fm.Parameters:
            if fp and fp.StorageType == StorageType.ElementId:
                fam_params.append(fp)
    except:
        fam_params = []

    cur_type = None

    try:
        cur_type = fm.CurrentType
    except:
        cur_type = None

    try:
        for ft in fm.Types:
            try:
                fm.CurrentType = ft
            except:
                pass

            for fp in fam_params:
                try:
                    vi = eid_val(ft.AsElementId(fp), INVALID_ID_INT)
                    if vi in map_ids:
                        fm.Set(fp, map_ids[vi])
                        changed += 1
                except:
                    pass
    finally:
        try:
            if cur_type is not None:
                fm.CurrentType = cur_type
        except:
            pass

    return changed

def collect_used_type_ids(doc):
    used = set()

    elems_inst = list(FilteredElementCollector(doc).WhereElementIsNotElementType())
    elems_type = list(FilteredElementCollector(doc).WhereElementIsElementType())

    for e in elems_inst + elems_type:
        try:
            used.add(eid_val(e.GetTypeId(), INVALID_ID_INT))
        except:
            pass

        try:
            for p in e.Parameters:
                if p and p.StorageType == StorageType.ElementId:
                    used.add(eid_val(p.AsElementId(), INVALID_ID_INT))
        except:
            pass

    try:
        fm = doc.FamilyManager
        for ft in fm.Types:
            for fp in fm.Parameters:
                if fp and fp.StorageType == StorageType.ElementId:
                    used.add(eid_val(ft.AsElementId(fp), INVALID_ID_INT))
    except:
        pass

    return used

def rewire_all(map_all):
    elems_inst = list(FilteredElementCollector(doc).WhereElementIsNotElementType())
    elems_type = list(FilteredElementCollector(doc).WhereElementIsElementType())

    retyped = 0
    rewired = 0

    for e in elems_inst + elems_type:
        try:
            cur_tid = eid_val(e.GetTypeId(), INVALID_ID_INT)
            if cur_tid in map_all:
                if change_type(e, map_all[cur_tid]):
                    retyped += 1
        except:
            pass

        rewired += rewire_element_params(e, map_all)

    rewired_fm = rewire_familytypes(doc, map_all)
    return retyped, rewired, rewired_fm

def delete_mapped_types(map_all):
    used = collect_used_type_ids(doc)
    deleted = 0
    kept = 0

    for tid in map_all.keys():
        if tid < 0:
            kept += 1
            continue

        if tid in used:
            kept += 1
            continue

        try:
            doc.Delete(make_eid(tid))
            deleted += 1
        except:
            kept += 1

    return deleted, kept

def collect_pools():
    all_text_types = list(
        FilteredElementCollector(doc)
        .OfClass(TextElementType)
        .WhereElementIsElementType()
    )

    all_textnote_types = list(
        FilteredElementCollector(doc)
        .OfClass(TextNoteType)
        .WhereElementIsElementType()
    )

    label_pool = [tt for tt in all_text_types if not isinstance(tt, TextNoteType)]
    text_pool = list(all_textnote_types)

    return label_pool, text_pool

#012-Process pool
def process_pool(pool_types, template, base_font, treat_as_blue):
    # Step 1: update font, size, office toggles, and color.
    processed = []
    font_changed = 0
    font_failed = []
    audit = []

    for tt in pool_types:
        try:
            live = doc.GetElement(tt.Id)
            if live is None:
                continue

            cur_rgb = resolve_style_rgb(live)

            nm0 = get_sym(live)
            nm1 = clean_display_name(nm0)

            if nm1 and nm1 != nm0:
                set_sym(live, nm1)

            old_font, new_font, forced, font_ok = apply_font_policy(live)

            if str(old_font or "").strip() != str(new_font or "").strip():
                if font_ok:
                    font_changed += 1
                else:
                    font_failed.append("{} '{}' -> '{}'".format(
                        eid_val(live.Id, 0),
                        old_font,
                        new_font
                    ))

            size_ft, _font, _bold, _italic = read_props(live)
            apply_office(live, size_ft)

            if size_ft and size_ft > 0:
                tgt_in = target_size_in(size_ft * 12.0)
                try:
                    p = live.get_Parameter(BuiltInParameter.TEXT_SIZE)
                    if p and (not p.IsReadOnly):
                        p.Set(float(tgt_in) / 12.0)
                except:
                    pass

            fin = normalize_color(cur_rgb, AllowColorRGB, treat_as_blue)
            set_rgb(live, fin)

            can, _ = canonical_for(live, base_font, treat_as_blue)

            audit.append("id={} font '{}' -> '{}' name '{}' -> '{}'".format(
                eid_val(live.Id, 0),
                old_font,
                new_font,
                nm0,
                can
            ))

            processed.append(live)

        except:
            pass

    # Step 2: group by canonical name after font policy is applied.
    groups = {}

    for tt in processed:
        can, _ = canonical_for(tt, base_font, treat_as_blue)
        if not can:
            continue
        groups.setdefault(can, []).append(tt)

    # Step 3: create missing sizes from IN[6].
    # This does not require IN[7]=InputSizesOnly to be True.
    # Missing styles are created with Arial Narrow.
    created = 0

    if CreateMissingSizes and INPUT_SIZES_AVAILABLE and template:
        use_font = FALLBACK_FONT

        for sz_in in ALLOWED_IN:
            size32 = int(round(sz_in * 32.0))
            base = "{:02d}.{}.{}".format(
                size32,
                font_token(use_font),
                frac32(sz_in)
            )

            desired = normalize_color(BLACK, AllowColorRGB, treat_as_blue)
            suf = rgb_suffix_if_needed(desired)
            want = base + (suf if suf else "")

            if want in groups:
                continue

            try:
                new_tt = template.Duplicate(want)

                tid = eid_val(new_tt.Id, INVALID_ID_INT)
                if tid != INVALID_ID_INT:
                    EFFECTIVE_FONT_BY_ID[tid] = use_font

                p = new_tt.get_Parameter(BuiltInParameter.TEXT_SIZE)
                if p and (not p.IsReadOnly):
                    p.Set(float(sz_in) / 12.0)

                set_font(new_tt, use_font)

                for bip in (
                    BuiltInParameter.TEXT_STYLE_BOLD,
                    BuiltInParameter.TEXT_STYLE_ITALIC
                ):
                    pp = new_tt.get_Parameter(bip)
                    if pp and (not pp.IsReadOnly):
                        pp.Set(0)

                apply_office(new_tt, float(sz_in) / 12.0)
                set_rgb(new_tt, desired)

                groups.setdefault(want, []).append(new_tt)
                processed.append(new_tt)
                created += 1

            except:
                pass

    # Step 4: build duplicate map.
    dup_map = {}
    keepers = {}

    for can, lst in groups.items():
        keep = None

        for tt in lst:
            if clean_display_name(get_sym(tt)).lower() == can.lower():
                keep = tt
                break

        if keep is None:
            keep = lst[0]

        keepers[can] = keep

        for tt in lst:
            if tt.Id != keep.Id:
                dup_map[eid_val(tt.Id, INVALID_ID_INT)] = keep.Id

    # Step 5: temp rename mapped-away duplicates.
    for tid in dup_map.keys():
        try:
            tt = doc.GetElement(make_eid(tid))
            if tt:
                set_sym(tt, "__delete_tmp__{}".format(tid))
        except:
            pass

    return created, dup_map, keepers, len(processed), font_changed, font_failed, audit

def final_rename_pass(pool_types, base_font, treat_as_blue):
    # Final pass:
    # 1. refresh live type
    # 2. force/update font by policy
    # 3. compute canonical from effective font
    # 4. temp rename all
    # 5. rename keepers
    # 6. map duplicates for another rewire/delete
    live_types = []
    audit = []
    failed = []
    font_changed = 0

    for tt in pool_types:
        try:
            live = doc.GetElement(tt.Id)
            if live is None:
                continue

            old_font, new_font, forced, font_ok = apply_font_policy(live)

            if str(old_font or "").strip() != str(new_font or "").strip():
                if font_ok:
                    font_changed += 1
                else:
                    failed.append("FONT {} '{}' -> '{}' failed".format(
                        eid_val(live.Id, 0),
                        old_font,
                        new_font
                    ))

            live_types.append(live)

        except:
            pass

    old_names = {}
    can2list = {}

    for tt in live_types:
        try:
            tid = eid_val(tt.Id, 0)
            old_names[tid] = clean_display_name(get_sym(tt)).lower()

            can, _ = canonical_for(tt, base_font, treat_as_blue)
            if not can:
                continue

            _size_ft, actual_font, _bold, _italic = read_props(tt)
            effective_font = EFFECTIVE_FONT_BY_ID.get(tid, actual_font)

            audit.append("id={} actual_font='{}' effective_font='{}' old='{}' new='{}'".format(
                tid,
                actual_font,
                effective_font,
                get_sym(tt),
                can
            ))

            can2list.setdefault(can, []).append(tt)

        except:
            pass

    # Temp rename every live type first to free all canonical names.
    for tt in live_types:
        try:
            tid = eid_val(tt.Id, 0)
            set_sym(tt, "__final_tmp__{}".format(tid))
        except:
            pass

    renamed = 0
    dup_map = {}

    for can, lst in can2list.items():
        if not lst:
            continue

        keep = lst[0]

        for tt in lst:
            try:
                tid = eid_val(tt.Id, 0)
                if old_names.get(tid, "") == can.lower():
                    keep = tt
                    break
            except:
                pass

        try:
            live_keep = doc.GetElement(keep.Id)
            if live_keep is None:
                failed.append("{} -> {} [deleted/stale]".format(
                    eid_val(keep.Id, 0),
                    can
                ))
            elif set_sym(live_keep, can):
                renamed += 1
            else:
                failed.append("{} -> {}".format(eid_val(live_keep.Id, 0), can))
        except Exception as ex:
            failed.append("{} -> {} [{}]".format(
                eid_val(keep.Id, 0),
                can,
                str(ex)
            ))

        for tt in lst:
            try:
                if tt.Id == keep.Id:
                    continue

                live_dup = doc.GetElement(tt.Id)
                if live_dup is None:
                    continue

                dup_id = eid_val(live_dup.Id, INVALID_ID_INT)
                dup_map[dup_id] = keep.Id

                dup_name = "{}.DUP{}".format(can, dup_id)
                set_sym(live_dup, dup_name)

            except:
                pass

    return renamed, failed, dup_map, audit, font_changed

#013-Main
log = []
log.append("V06-10: Labels+Text canonicalize")
log.append("Font patterns IN[0]: {}".format(", ".join(FONT_PATTERNS)))
log.append("Fallback font: {}".format(FALLBACK_FONT))
log.append("AllowColorRGB: {}".format(AllowColorRGB))
log.append("TreatLabelAsBlue: {}".format(TreatLabelAsBlue))
log.append("TreatTextAsBlue: {}".format(TreatTextAsBlue))
log.append("InputSizesOnly IN[7]: {}".format(InputSizesOnly))
log.append("Input sizes available: {}".format(INPUT_SIZES_AVAILABLE))
log.append("Size behavior: {}".format(
    "limit to IN[6] sizes" if LIMIT_TO_INPUT_SIZES else "snap to nearest 1/32 only"
))
log.append("Create missing: {}".format(
    "uses IN[6] sizes" if (CreateMissingSizes and INPUT_SIZES_AVAILABLE) else "off or no valid sizes"
))
log.append("Input sizes: {}".format(
    ", ".join(frac32(x) for x in ALLOWED_IN) if ALLOWED_IN else "<none>"
))

if not doc.IsFamilyDocument:
    OUT = log + ["Open a FAMILY (.rfa) and run."]
else:
    tx = Transaction(doc, "Labels+Text canonicalize V06-10")
    tx.Start()

    try:
        label_pool, text_pool = collect_pools()

        label_template = label_pool[0] if label_pool else None
        text_template = text_pool[0] if text_pool else None

        _ls, label_base_font, _lb, _li = (
            read_props(label_template)
            if label_template else (0.0, FALLBACK_FONT, False, False)
        )

        _ts, text_base_font, _tb, _ti = (
            read_props(text_template)
            if text_template else (0.0, FALLBACK_FONT, False, False)
        )

        label_base_font = label_base_font or FALLBACK_FONT
        text_base_font = text_base_font or FALLBACK_FONT

        created_lbl, map_lbl, keep_lbl, processed_lbl, fontchg_lbl, fontfail_lbl, audit_lbl1 = process_pool(
            label_pool,
            label_template,
            label_base_font,
            TreatLabelAsBlue
        )

        created_txt, map_txt, keep_txt, processed_txt, fontchg_txt, fontfail_txt, audit_txt1 = process_pool(
            text_pool,
            text_template,
            text_base_font,
            TreatTextAsBlue
        )

        log.append("Label pool: {}, processed: {}".format(len(label_pool), processed_lbl))
        log.append("Text pool: {}, processed: {}".format(len(text_pool), processed_txt))

        log.append("Labels: created_missing={}, map={}, font_changed={}".format(
            created_lbl,
            len(map_lbl),
            fontchg_lbl
        ))

        log.append("Text  : created_missing={}, map={}, font_changed={}".format(
            created_txt,
            len(map_txt),
            fontchg_txt
        ))

        if fontfail_lbl:
            log.append("Label font set failures:")
            log.extend(["  " + x for x in fontfail_lbl[:10]])

        if fontfail_txt:
            log.append("Text font set failures:")
            log.extend(["  " + x for x in fontfail_txt[:10]])

        map_all = {}
        map_all.update(map_lbl)
        map_all.update(map_txt)

        if map_all:
            retyped, rewired, rewired_fm = rewire_all(map_all)
            log.append("Initial rewire: retyped={}, rewired_params={}, rewired_familytypes={}".format(
                retyped,
                rewired,
                rewired_fm
            ))

            deleted, kept = delete_mapped_types(map_all)
            log.append("Initial delete mapped: deleted={}, kept={}".format(deleted, kept))
        else:
            log.append("Initial rewire/delete: no duplicate map")

        try:
            doc.Regenerate()
        except:
            pass

        # Refresh pools after delete/regenerate.
        label_pool, text_pool = collect_pools()

        final_lbl, failed_lbl, final_map_lbl, audit_lbl2, fontchg_lbl2 = final_rename_pass(
            label_pool,
            label_base_font,
            TreatLabelAsBlue
        )

        final_txt, failed_txt, final_map_txt, audit_txt2, fontchg_txt2 = final_rename_pass(
            text_pool,
            text_base_font,
            TreatTextAsBlue
        )

        log.append("Final rename pass: label={}, text={}, label_font_changed={}, text_font_changed={}".format(
            final_lbl,
            final_txt,
            fontchg_lbl2,
            fontchg_txt2
        ))

        log.append("Font/name audit:")
        for x in (audit_lbl2 + audit_txt2)[:24]:
            log.append("  " + x)

        more_audit = len(audit_lbl2 + audit_txt2) - 24
        if more_audit > 0:
            log.append("  ... {} more".format(more_audit))

        final_map_all = {}
        final_map_all.update(final_map_lbl)
        final_map_all.update(final_map_txt)

        if final_map_all:
            retyped2, rewired2, rewired_fm2 = rewire_all(final_map_all)

            log.append("Final consolidate rewire: retyped={}, rewired_params={}, rewired_familytypes={}".format(
                retyped2,
                rewired2,
                rewired_fm2
            ))

            deleted2, kept2 = delete_mapped_types(final_map_all)

            log.append("Final consolidate delete: deleted={}, kept={}".format(
                deleted2,
                kept2
            ))

            try:
                doc.Regenerate()
            except:
                pass
        else:
            log.append("Final consolidate: no duplicate map")

        if failed_lbl:
            log.append("Final label rename failures:")
            log.extend(["  " + x for x in failed_lbl[:10]])

        if failed_txt:
            log.append("Final text rename failures:")
            log.extend(["  " + x for x in failed_txt[:10]])

        tx.Commit()
        OUT = log

    except Exception as ex:
        try:
            tx.RollBack()
        except:
            pass

        OUT = log + ["An error occurred:", str(ex), repr(type(ex))]
