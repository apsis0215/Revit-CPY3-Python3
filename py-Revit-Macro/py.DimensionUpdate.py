# ============================================================
# DimensionStyles â€“ Revit 2025 SAFE (Canonical + Combine)
#
# - Canonicalize text size, font, color
# - Canonical name derived from FINAL size
# - If rename blocked -> duplicate
# - Swap non-reporting dimensions
# - Delete unused old types
#
# IN[0] = ArialNarrowOnly (bool)
# IN[1] = AllowColorRGB   (bool)
# IN[2] = SizesInput      (string) e.g. "3/32,1/8,1/4"
# OUT   = list[str]
# ============================================================

import clr, math, re
##from Autodesk.Revit.DB import UnitTypeId

# ---------------- Revit API ----------------
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    DimensionType,
    Dimension,
    BuiltInParameter,
    Transaction,
    ParameterTypeId,
    UnitTypeId
)

# ---------------- Dynamo ----------------
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

# ============================================================
# Inputs
# ============================================================

def _b(i, default=False):
    try: return bool(IN[i])
    except: return default

def _s(i, default=""):
    try:
        v = IN[i]
        return str(v).strip() if v else default
    except:
        return default

ArialNarrowOnly = _b(0, False)
AllowColorRGB   = _b(1, False)
SizesInput      = _s(2, "")

# ============================================================
# Size helpers
# ============================================================

_DEFAULT_SIZES_IN = [3.0 / 32.0]

def _parse_size_in(token):
    t = token.replace('"', '').strip()
    if "-" in t and "/" in t:
        w, f = t.split("-", 1)
        n, d = f.split("/", 1)
        return float(w) + float(n) / float(d)
    if "/" in t:
        n, d = t.split("/", 1)
        return float(n) / float(d)
    return float(t)

def build_sizes(s):
    if not s:
        return list(_DEFAULT_SIZES_IN)
    out = []
    for tok in re.split(r"[;, ]+", s):
        try:
            v = _parse_size_in(tok)
            if v > 0:
                out.append(v)
        except:
            pass
    return out or list(_DEFAULT_SIZES_IN)

ACCEPTABLE_SIZES_IN = build_sizes(SizesInput)

def nearest_size_in(size_ft):
    size_in = size_ft * 12.0
    return min(ACCEPTABLE_SIZES_IN, key=lambda x: abs(x - size_in))

def frac32(sz_in):
    n = int(round(sz_in * 32.0))
    g = math.gcd(n, 32)
    return '{}/{}"'.format(n // g, 32 // g)

# ============================================================
# Param helpers
# ============================================================

def get_text_size_param(dt):
    try: return dt.GetParameter(ParameterTypeId.TextSize)
    except: return dt.LookupParameter("Text Size")

def get_text_font_param(dt):
    try: return dt.GetParameter(ParameterTypeId.TextFont)
    except: return dt.LookupParameter("Text Font")

def get_text_color_param(dt):
    return dt.LookupParameter("Text Color")

def get_line_color_param(dt):
    return dt.LookupParameter("Line Color")

def get_type_name(dt):
    p = dt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p and p.HasValue else None

# ============================================================
# UNIT helpers
# ============================================================

def get_length_format_suffix(dt, doc):
    try:
        # Per-dimension-type format override (preferred)
        fmt = dt.GetFormatOptions(UnitTypeId.Length)
        if fmt and not fmt.UseDefault:
            ut = fmt.GetUnitTypeId()
        else:
            units = doc.GetUnits()
            fo = units.GetFormatOptions(UnitTypeId.Length)
            ut = fo.GetUnitTypeId()

        if ut == UnitTypeId.Feet:
            return "FT"
        if ut == UnitTypeId.FeetFractionalInches:
            return "FT-IN"
        if ut == UnitTypeId.Inches:
            return "IN"
        if ut == UnitTypeId.UsSurveyFeet:
            return "FT(US)"
        if ut == UnitTypeId.Millimeters:
            return "mm"
        if ut == UnitTypeId.Centimeters:
            return "cm"
        if ut == UnitTypeId.Meters:
            return "M"

        return ut.TypeId.split("-")[-1]
    except:
        return "PROJ"



# ============================================================
# Main
# ============================================================

types = list(FilteredElementCollector(doc).OfClass(DimensionType))
dims  = list(FilteredElementCollector(doc).OfClass(Dimension))

log = [
    "DimensionStyles â€“ canonical + combine",
    "Document: {}".format(doc.Title),
    "Types found: {}".format(len(types)),
    ""
]

t = Transaction(doc, "DimensionStyles â€“ canonical + combine")
t.Start()

renamed = duplicated = swapped = deleted = skipped = 0

for dt in list(types):

    name_before = get_type_name(dt)
    if not name_before:
        skipped += 1
        continue

    # ---------------- text size ----------------
    p_size = get_text_size_param(dt)
    if not p_size:
        skipped += 1
        continue

    try:
        cur_ft = p_size.AsDouble()
    except:
        skipped += 1
        continue

    target_in = nearest_size_in(cur_ft)
    target_ft = target_in / 12.0

    if not p_size.IsReadOnly and abs(cur_ft - target_ft) > 1e-9:
        try: p_size.Set(target_ft)
        except: pass

    # ---------------- font ----------------
    font_token = "Unknown"
    if ArialNarrowOnly:
        p_font = get_text_font_param(dt)
        if p_font and not p_font.IsReadOnly:
            try: p_font.Set("Arial Narrow")
            except: pass
        font_token = "ArialNarrow"

    # ---------------- color ----------------
    tok = None
    if not AllowColorRGB:
        for p in (get_text_color_param(dt), get_line_color_param(dt)):
            if p and not p.IsReadOnly:
                try: p.Set(0)
                except: pass

    # ---------------- canonical name ----------------
    size32 = int(round(target_in * 32.0))           ##Calculate 32'nds
    size32_tok = "{:02d}".format(size32)            ##Zero-pad '32 index
    unit_suffix = get_length_format_suffix(dt, doc) ##Get unit type of dim style

    new_name = "{}.{}.{}.{}".format(
        size32_tok,
        font_token,
        frac32(target_in),
        unit_suffix
    )

    if name_before == new_name:
        continue

    # ---------------- try rename ----------------
    p_name = dt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    target_type = dt

    if p_name and not p_name.IsReadOnly:
        try:
            p_name.Set(new_name)
            renamed += 1
        except:
            pass
    else:
        # ---------------- duplicate ----------------
        try:
            target_type = dt.Duplicate(new_name)
            duplicated += 1
        except:
            skipped += 1
            continue

    # ---------------- swap instances ----------------
    for d in dims:
        if d.DimensionType.Id != dt.Id:
            continue

        # safe reporting guard
        if hasattr(d, "IsReporting"):
            try:
                if d.IsReporting:
                    continue
            except:
                continue

        try:
            d.DimensionType = target_type
            swapped += 1
        except:
            pass

    # ---------------- delete old if unused ----------------
    still_used = any(d.DimensionType.Id == dt.Id for d in dims)
    if not still_used and target_type.Id != dt.Id:
        try:
            doc.Delete(dt.Id)
            deleted += 1
        except:
            pass

t.Commit()

log += [
    "Renamed in-place: {}".format(renamed),
    "Duplicated: {}".format(duplicated),
    "Instances swapped: {}".format(swapped),
    "Old types deleted: {}".format(deleted),
    "Skipped: {}".format(skipped)
]

OUT = log
