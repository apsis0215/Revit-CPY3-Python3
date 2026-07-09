# py-Text-Style-PROJECT.py
# V07-00
# IN[0]=FontPatternsCSV(str)       # filter, e.g. "", "Arial Narrow", "Arial*, *helvetica*"; supports * and ?
# IN[1]=TransparentOnly(bool)
# IN[2]=TabTo3_2(bool)
# IN[3]=AllowColorRGB(bool)        # True=preserve RGB colors; False=force black/redDk by IN[8]
# IN[4]=ReservedIgnored(bool)      # kept only for Dynamo Player compatibility; labels do not apply in projects
# IN[5]=CreateMissingSizes(bool)   # uses IN[6] sizes; does not require IN[7]=True
# IN[6]=SizesInput(str)            # input sizes, e.g. "3/32, 1/4"
# IN[7]=InputSizesOnly(bool)       # False=snap all to nearest 1/32"; True=limit to IN[6] only
# IN[8]=TreatTextAsRedDk(bool)     # default True; only overrides when IN[3]=False
# OUT=list[str]

import clr
import math
import re
import fnmatch

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInParameter,
    StorageType,
    TextNote,
    TextNoteType,
    ElementId,
    Transaction
)

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

clr.AddReference("System")
from System import Int64

doc = DocumentManager.Instance.CurrentDBDocument


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


FontPatternsCSV    = _s(0, "Arial Narrow")
TransparentOnly    = _b(1, False)
TabTo3_2           = _b(2, False)
AllowColorRGB      = _b(3, False)
ReservedIgnored    = _b(4, False)
CreateMissingSizes = _b(5, False)
SizesInput         = _s(6, "")
InputSizesOnly     = _b(7, False)
TreatTextAsRedDk   = _b(8, True)

BLACK = (0, 0, 0)
RED_DK = (64, 0, 0)

FALLBACK_FONT = "Arial Narrow"
DEFAULT_FONT = FALLBACK_FONT


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


def normalize_known_font_name(font_name):
    s = str(font_name or "").strip()
    if s.lower() == "arial narrow":
        return "Arial Narrow"
    return s


def parse_font_patterns(csv_text):
    raw = str(csv_text or "").strip()
    if not raw:
        raw = "Arial Narrow"

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts if parts else ["Arial Narrow"]


FONT_PATTERNS = parse_font_patterns(FontPatternsCSV)


def font_matches_patterns(font_name):
    s = str(font_name or "").strip()
    if not s:
        return False

    s_low = s.lower()
    for pat in FONT_PATTERNS:
        if fnmatch.fnmatchcase(s_low, pat.lower()):
            return True

    return False


def target_font_for(font_name):
    cur = str(font_name or "").strip()
    if cur and font_matches_patterns(cur):
        return normalize_known_font_name(cur), False

    return FALLBACK_FONT, True


def font_token(font_name):
    s = str(font_name or FALLBACK_FONT).strip()
    s = re.sub(r"[^A-Za-z0-9]+", " ", s).strip()

    if not s:
        return "UnknownFont"

    return "".join([w[:1].upper() + w[1:] for w in s.split()])


EFFECTIVE_FONT_BY_ID = {}


def _parse_in(tok):
    if tok is None:
        return None

    s = str(tok).strip().replace('"', "")
    if not s:
        return None

    s = re.sub(r"\s+", " ", s)

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
    tokens = [t for t in re.split(r"[\s;]+", raw) if t.strip()]
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


def _rgb_from_packed(v):
    v = int(v)
    r = v & 0xFF
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


_COLOR_WORDS = re.compile(
    r"\s+(red|green|blue|black|white|cyan|magenta|yellow|gray|grey)\s*$",
    re.IGNORECASE
)

_COLOR_WORD_TO_RGB = {
    "red":     (255, 0, 0),
    "green":   (0, 255, 0),
    "blue":    (0, 0, 255),
    "black":   BLACK,
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
    nm = tname(tt)

    if AllowColorRGB:
        w_rgb = _color_word_rgb_from_name(nm)
        if w_rgb is not None:
            return w_rgb

    for bip in (BuiltInParameter.LINE_COLOR, BuiltInParameter.TEXT_COLOR):
        try:
            p = tt.get_Parameter(bip)
            if p:
                return _rgb_from_packed(p.AsInteger())
        except:
            pass

    return BLACK


def normalize_color(rgb, allow_rgb, treat_as_reddk=False):
    if rgb is None:
        rgb = BLACK

    if allow_rgb:
        return rgb

    if treat_as_reddk:
        return RED_DK

    return BLACK


def rgb_suffix_if_needed(final_rgb):
    if not AllowColorRGB:
        return None

    if final_rgb in (BLACK, RED_DK):
        return None

    r, g, b = final_rgb
    return ".{:03d}-{:03d}-{:03d}".format(r, g, b)


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
    try:
        p = tt.get_Parameter(BuiltInParameter.TEXT_FONT)
        if p and (not p.IsReadOnly) and p.StorageType == StorageType.String:
            return bool(p.Set(str(normalize_known_font_name(font_name))))
    except:
        pass

    return False


def apply_font_policy(tt):
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


_RGB_DASH_RE = re.compile(r"\.\d{3}-\d{3}-\d{3}(?=\.DUP\d+$|$)", re.IGNORECASE)
_DUP_RE = re.compile(r"\.DUP\d+$", re.IGNORECASE)
_SUFFIX_NUM = re.compile(r"\s+\d+$")


def clean_display_name(nm):
    s = (nm or "").strip()

    s = s.replace("“", '"').replace("”", '"').replace("″", '"')
    s = re.sub(_DUP_RE, "", s).strip()
    s = re.sub(_RGB_DASH_RE, "", s).strip()
    s = re.sub(_COLOR_WORDS, "", s).strip()
    s = re.sub(_SUFFIX_NUM, "", s).strip()
    s = re.sub(r"\s+", " ", s)

    return s


def canonical_for(tt):
    size_ft, font, bold, italic = read_props(tt)
    tid = eid_val(tt.Id, INVALID_ID_INT)

    use_font = EFFECTIVE_FONT_BY_ID.get(tid, None)
    if not use_font:
        use_font, _forced = target_font_for(font)

    raw_in = (size_ft * 12.0) if (size_ft and size_ft > 0.0) else 3.0 / 32.0
    sz_in = target_size_in(raw_in)
    size32 = int(round(sz_in * 32.0))

    parts = ["{:02d}".format(size32), font_token(use_font)]

    if bold:
        parts.append("BOLD")

    if italic:
        parts.append("ITALIC")

    parts.append(frac32(sz_in))

    cur_rgb = resolve_style_rgb(tt)
    final_rgb = normalize_color(cur_rgb, AllowColorRGB, TreatTextAsRedDk)
    suffix = rgb_suffix_if_needed(final_rgb)

    base = ".".join(parts)
    return base + (suffix if suffix else ""), final_rgb


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


def collect_used_type_ids():
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

    return retyped, rewired


def delete_mapped_types(map_all):
    used = collect_used_type_ids()
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


def collect_text_types():
    return list(
        FilteredElementCollector(doc)
        .OfClass(TextNoteType)
        .WhereElementIsElementType()
    )


def process_text_pool(text_types, template):
    processed = []
    font_changed = 0
    font_failed = []
    audit = []

    for tt in text_types:
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

            if size_ft and size_ft > 0.0:
                tgt_in = target_size_in(size_ft * 12.0)
                try:
                    p = live.get_Parameter(BuiltInParameter.TEXT_SIZE)
                    if p and (not p.IsReadOnly):
                        p.Set(float(tgt_in) / 12.0)
                except:
                    pass

            fin = normalize_color(cur_rgb, AllowColorRGB, TreatTextAsRedDk)
            set_rgb(live, fin)

            can, _ = canonical_for(live)

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

    groups = {}

    for tt in processed:
        can, _ = canonical_for(tt)
        if not can:
            continue
        groups.setdefault(can, []).append(tt)

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

            desired = normalize_color(BLACK, AllowColorRGB, TreatTextAsRedDk)
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

    for tid in dup_map.keys():
        try:
            tt = doc.GetElement(make_eid(tid))
            if tt:
                set_sym(tt, "__delete_tmp__{}".format(tid))
        except:
            pass

    return created, dup_map, keepers, len(processed), font_changed, font_failed, audit


def final_rename_pass(text_types):
    live_types = []
    audit = []
    failed = []
    font_changed = 0

    for tt in text_types:
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

            can, _ = canonical_for(tt)
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


log = []
log.append("V07-00: Project TextNoteType style canonicalize")
log.append("Font patterns IN[0]: {}".format(", ".join(FONT_PATTERNS)))
log.append("Fallback font: {}".format(FALLBACK_FONT))
log.append("AllowColorRGB: {}".format(AllowColorRGB))
log.append("Reserved IN[4] ignored: {}".format(ReservedIgnored))
log.append("TreatTextAsRedDk: {}".format(TreatTextAsRedDk))
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
log.append("Color behavior: {}".format(
    "preserve RGB colors" if AllowColorRGB else (
        "force text to redDk" if TreatTextAsRedDk else "force text to black"
    )
))

if doc.IsFamilyDocument:
    OUT = log + ["Open a PROJECT (.rvt) and run this project text-style node."]
else:
    tx = Transaction(doc, "Project TextNoteType style canonicalize V07-00")
    tx.Start()

    try:
        text_pool = collect_text_types()
        text_template = text_pool[0] if text_pool else None

        created_txt, map_txt, keep_txt, processed_txt, fontchg_txt, fontfail_txt, audit_txt1 = process_text_pool(
            text_pool,
            text_template
        )

        log.append("Text style pool: {}, processed: {}".format(len(text_pool), processed_txt))
        log.append("Text: created_missing={}, map={}, font_changed={}".format(
            created_txt,
            len(map_txt),
            fontchg_txt
        ))

        if fontfail_txt:
            log.append("Text font set failures:")
            log.extend(["  " + x for x in fontfail_txt[:10]])

        if map_txt:
            retyped, rewired = rewire_all(map_txt)
            log.append("Initial rewire: retyped={}, rewired_params={}".format(
                retyped,
                rewired
            ))

            deleted, kept = delete_mapped_types(map_txt)
            log.append("Initial delete mapped: deleted={}, kept={}".format(deleted, kept))
        else:
            log.append("Initial rewire/delete: no duplicate map")

        try:
            doc.Regenerate()
        except:
            pass

        text_pool = collect_text_types()

        final_txt, failed_txt, final_map_txt, audit_txt2, fontchg_txt2 = final_rename_pass(
            text_pool
        )

        log.append("Final rename pass: text={}, text_font_changed={}".format(
            final_txt,
            fontchg_txt2
        ))

        log.append("Font/name audit:")
        for x in audit_txt2[:24]:
            log.append("  " + x)

        more_audit = len(audit_txt2) - 24
        if more_audit > 0:
            log.append("  ... {} more".format(more_audit))

        if final_map_txt:
            retyped2, rewired2 = rewire_all(final_map_txt)

            log.append("Final consolidate rewire: retyped={}, rewired_params={}".format(
                retyped2,
                rewired2
            ))

            deleted2, kept2 = delete_mapped_types(final_map_txt)

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
