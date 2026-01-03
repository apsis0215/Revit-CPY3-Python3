# Create PROJECT TextNoteType styles
# IN[0]=FontNames(str, optional) e.g. "Arial Narrow, Arial"
# IN[1]=SizesInput(str, optional) e.g. "3/32, 1/8"
# Defaults:
#   FontNames = "Arial Narrow"
#   SizesInput = "3/32"
#
# Size policy:
# - Snap to nearest 1/32"
# - Lowest wins on .5
# - HARD FLOOR = 1/32"
#
# Revit 2025+, Dynamo Revit, CPython3
# OUT=list[str]

import clr, math, re

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector, TextNoteType,
    BuiltInParameter, Transaction
)

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

# ---------------- inputs ----------------
def _s(i, default=""):
    try:
        v = IN[i]
        if v is None:
            return default
        s = str(v).strip()
        return s if s else default
    except:
        return default

fonts_raw = _s(0, "Arial Narrow")
sizes_raw = _s(1, "3/32")

FONT_NAMES = [f.strip() for f in fonts_raw.split(",") if f.strip()]
SIZE_TEXT  = sizes_raw

# ---------------- size helpers ----------------
_SIZE_TOKEN_RE = re.compile(
    r'(\d+\s*-\s*\d+\s*/\s*\d+)|'
    r'(\d+\s+\d+\s*/\s*\d+)|'
    r'(\d+\s*/\s*\d+)|'
    r'(\d*\.\d+)|'
    r'(\d+)'
)

def snap_in_to_1_32(sz_in):
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

def parse_size_token(tok):
    t = tok.replace('"', '').strip()
    if "-" in t and "/" in t:
        w, f = t.split("-", 1)
        n, d = f.split("/", 1)
        return float(w) + float(n) / float(d)
    if " " in t and "/" in t:
        w, f = t.split(" ", 1)
        n, d = f.split("/", 1)
        return float(w) + float(n) / float(d)
    if "/" in t:
        n, d = t.split("/", 1)
        return float(n) / float(d)
    return float(t)

def build_sizes_in(s):
    matches = _SIZE_TOKEN_RE.findall(s)
    vals = []
    for tup in matches:
        tok = next((x for x in tup if x), None)
        if tok:
            try:
                vals.append(parse_size_token(tok))
            except:
                pass
    if not vals:
        vals = [3.0/32.0]
    snapped = [snap_in_to_1_32(v) for v in vals]
    snapped.sort()
    out = []
    for v in snapped:
        if not out or abs(v - out[-1]) > 1e-9:
            out.append(v)
    return out

SIZES_IN = build_sizes_in(SIZE_TEXT)

def frac32(sz_in):
    num = int(round(sz_in * 32.0))
    den = 32
    g = math.gcd(num, den)
    num //= g
    den //= g
    if num >= den:
        w, r = divmod(num, den)
        return '{}"'.format(w) if r == 0 else '{}-{}/{}"'.format(w, r, den)
    return '{}/{}"'.format(num, den)

def font_token(s):
    return "".join(w.capitalize() for w in s.split())

# ---------------- collect existing ----------------
types = list(FilteredElementCollector(doc).OfClass(TextNoteType).ToElements())
if not types:
    OUT = ["No TextNoteTypes found in document."]
    raise SystemExit

existing = {}
for tt in types:
    try:
        n = tt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        existing[n] = tt
    except:
        pass

base_type = types[0]

# ---------------- create ----------------
log = []
created = 0
skipped = 0

t = Transaction(doc, "Create Text Styles")
t.Start()
try:
    for font in FONT_NAMES:
        for sz_in in SIZES_IN:
            sz_ft = sz_in / 12.0
            size32 = int(round(sz_in * 32.0))
            name = "{:02d}.{}.{}".format(size32, font_token(font), frac32(sz_in))

            if name in existing:
                skipped += 1
                log.append("Exists: {}".format(name))
                continue

            try:
                new_tt = base_type.Duplicate(name)
                p_font = new_tt.get_Parameter(BuiltInParameter.TEXT_FONT)
                p_size = new_tt.get_Parameter(BuiltInParameter.TEXT_SIZE)
                p_tab  = new_tt.get_Parameter(BuiltInParameter.TEXT_TAB_SIZE)

                if p_font and not p_font.IsReadOnly:
                    p_font.Set(font)
                if p_size and not p_size.IsReadOnly:
                    p_size.Set(sz_ft)
                if p_tab and not p_tab.IsReadOnly:
                    p_tab.Set(sz_ft)

                created += 1
                log.append("Created: {}".format(name))
            except Exception as ex:
                log.append("Failed '{}': {}".format(name, str(ex)))
finally:
    t.Commit()

OUT = (
    ["Create Text Styles"]
    + ["Fonts: {}".format(", ".join(FONT_NAMES))]
    + ["Sizes: {}".format(", ".join([frac32(s) for s in SIZES_IN]))]
    + [""]
    + log
    + [""]
    + ["Summary: Created {}, Skipped {}".format(created, skipped)]
)
