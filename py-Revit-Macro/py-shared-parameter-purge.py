# py-shared-parameter-purge.py
# v00.01 [2026-02-05 hhnnap]
# Encoding: utf-8
# Purges Shared + (optionally) Project Parameters by name patterns, with Keep/Force rules,
# schedule protection for shared params, optional ListOnly reporting, optional Legend+Summary,
# and appends a GUID classification tag: DETERMINISTIC / RANDOM / #N/A (per reversible VBA scheme).

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
# Deterministic reversible GUID check (ported from your VBA)
# ------------------------------------------------------------
BASE_ALL = r'.1234ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz056789!"#$%&\'()*+,-./:;<=>?@[\]^`{|}~'
SEP = "-" * 64

def _strip_guid(g):
    if not g:
        return ""
    s = str(g).strip()
    if "-" in s:
        s = s.replace("-", "")
    return s.lower()

def _dec2bin(n, bits):
    n = int(n)
    out = ""
    while n != 0:
        out = str(n % 2) + out
        n //= 2
    return (("0" * bits) + out)[-bits:]

def _bin2dec(b):
    res = 0
    for i in range(len(b)):
        res = (res << 1) | (1 if b[i] == "1" else 0)
    return res

def _guid_bit_size_and_clear_lsb(hex32):
    """
    Returns (bit_size, cleared_hex32)
    bit_size: 5 if last bit is 0, else 6
    cleared_hex32: same hex32 but last nibble has LSB cleared (VBA GUIDbitSize behavior)
    """
    if not hex32 or len(hex32) != 32:
        return (0, hex32)

    last_nib = int(hex32[-1], 16)
    bit_size = 6 if (last_nib & 0x1) == 1 else 5
    last_nib_cleared = last_nib & 0xE
    cleared_hex32 = hex32[:-1] + format(last_nib_cleared, "x")
    return (bit_size, cleared_hex32)

def _guid_string_bit_size_and_mutate_name(name, case_sensitive=False):
    """
    VBA GUIDstringBitSize behavior.
    Returns: (bit_size, mutated_name_trimmed)
      - trims initial to 25 (128/5)
      - chooses 5-bit by default; upgrades to 6-bit if any UCase(char) index >= 32
      - if 5-bit, flips name to UPPERCASE
      - trims again to 25 (5-bit) or 21 (6-bit)
    """
    s = (name or "").strip()
    maxlen_5 = int(128 / 5)  # 25
    s = s[:maxlen_5]

    if case_sensitive:
        bit_size = 6
    else:
        bit_size = 5
        for ch in s:
            up = ch.upper()
            idx = BASE_ALL.find(up)
            if idx >= 32:
                bit_size = 6
                break
        if bit_size == 5:
            s = s.upper()

    maxlen = int(128 / bit_size)  # 25 or 21
    s = s[:maxlen]
    return (bit_size, s)

def _guid_decode(guid_str):
    """
    VBA GUIDdecode behavior:
      - determine bit size from last bit (and clear that bit)
      - hex -> binary
      - read BitSize chunks until remaining bits contain no '1'
    """
    h = _strip_guid(guid_str)
    if not h or len(h) != 32:
        return ""

    bit_size, h_cleared = _guid_bit_size_and_clear_lsb(h)
    if bit_size not in (5, 6):
        return ""

    bin_str = ""
    for i in range(0, 32, 2):
        byte_val = int(h_cleared[i:i + 2], 16)
        bin_str += _dec2bin(byte_val, 8)

    decoded = ""
    while len(bin_str) >= bit_size:
        if "1" not in bin_str:
            break
        chunk = bin_str[:bit_size]
        val = _bin2dec(chunk)
        if val < 0 or val >= len(BASE_ALL):
            break
        decoded += BASE_ALL[val]
        bin_str = bin_str[bit_size:]
    return decoded.strip()

def guid_classification_for_shared_param(shared_param_elem, param_name):
    """
    Always returns:
      - 'DETERMINISTIC' (matches reversible encoding scheme)
      - 'RANDOM'        (has GUID but doesn't decode/match)
      - '#N/A'          (no GUID / invalid)
    """
    try:
        guid_val = getattr(shared_param_elem, "GuidValue", None)
        if guid_val is None:
            return "#N/A"
        guid_str = str(guid_val)
        if not guid_str:
            return "#N/A"
    except:
        return "#N/A"

    decoded = _guid_decode(guid_str)
    if not decoded:
        return "RANDOM"

    try:
        _, mutated = _guid_string_bit_size_and_mutate_name(param_name, case_sensitive=False)
        b = decoded.strip()
        v = mutated.strip()
        if not v or not b:
            return "RANDOM"
        for i in range(len(v)):  # VBA compares up to VarName length
            if i >= len(b) or b[i] != v[i]:
                return "RANDOM"
        return "DETERMINISTIC"
    except:
        return "RANDOM"

def guid_classification_for_project_param(_param_elem):
    return "#N/A"

def append_guid_flag(line, guid_flag):
    return "{0} |GUID={1}".format(line, guid_flag)

# ------------------------------------------------------------
# Legend / Summary helpers
# ------------------------------------------------------------
def add_header(results, title):
    results.append("")
    results.append(SEP)
    results.append(title)
    results.append(SEP)

def add_legend(results, PrefixTarget, ForcePatterns, KeepPatterns, PurgeProjectParams, ListOnly):
    results.append(SEP)
    results.append("LEGEND / MEANINGS")
    results.append(SEP)
    results.append("[Shared]   = Shared parameter (SharedParameterElement)")
    results.append("[Project]  = Project parameter (non-shared ParameterElement)")
    results.append("[LIST]     = ListOnly=True (no deletions; reporting only)")
    results.append("KEPT       = excluded by KeepPatterns (always kept)")
    results.append("MATCH      = matched PrefixTarget and not kept; candidate for deletion")
    results.append("PROTECTED  = used in schedules; not deleted unless ForcePatterns match")
    results.append("SKIPPED    = not deleted (project param; no usage detection unless forced)")
    results.append("--Deleted  = deleted (normal)")
    results.append("-DelForce  = deleted due to ForcePatterns override")
    results.append("[SYSTEM]   = delete failed (exception)")
    results.append("")
    results.append("GUID flag:")
    results.append("  |GUID=DETERMINISTIC = GUID decodes back to parameter name (reversible scheme)")
    results.append("  |GUID=RANDOM        = GUID exists but does not decode/match")
    results.append("  |GUID=#N/A          = GUID not applicable/available (e.g. non-shared project params)")
    results.append("")
    results.append("Inputs summary:")
    results.append("PrefixTarget       = {0}".format(", ".join(PrefixTarget)))
    results.append("ForcePatterns      = {0}".format(", ".join(ForcePatterns) if ForcePatterns else "(none)"))
    results.append("KeepPatterns       = {0}".format(", ".join(KeepPatterns)))
    results.append("PurgeProjectParams = {0}".format(PurgeProjectParams))
    results.append("ListOnly           = {0}".format(ListOnly))
    results.append(SEP)
    results.append("")

def add_section_summary(results, title, counts, guid_counts, ListOnly):
    add_header(results, "{0} SUMMARY".format(title))
    if ListOnly:
        results.append("Listed     = {0}".format(counts.get("listed", 0)))
        results.append("Matched    = {0}".format(counts.get("matched", 0)))
        results.append("Kept       = {0}".format(counts.get("kept", 0)))
        results.append("Protected  = {0}".format(counts.get("protected", 0)))
        results.append("Skipped    = {0}".format(counts.get("skipped", 0)))
        results.append("Errors     = {0}".format(counts.get("errors", 0)))
    else:
        results.append("Matched    = {0}".format(counts.get("matched", 0)))
        results.append("Kept       = {0}".format(counts.get("kept", 0)))
        results.append("Protected  = {0}".format(counts.get("protected", 0)))
        results.append("Deleted    = {0}".format(counts.get("deleted", 0)))
        results.append("Skipped    = {0}".format(counts.get("skipped", 0)))
        results.append("Errors     = {0}".format(counts.get("errors", 0)))

    results.append("")
    results.append("GUID classification counts:")
    results.append("  DETERMINISTIC = {0}".format(guid_counts.get("DETERMINISTIC", 0)))
    results.append("  RANDOM        = {0}".format(guid_counts.get("RANDOM", 0)))
    results.append("  #N/A          = {0}".format(guid_counts.get("#N/A", 0)))

def add_overall_summary(results, shared_counts, shared_guid, project_counts, project_guid, PurgeProjectParams, ListOnly):
    add_header(results, "OVERALL SUMMARY")

    results.append("Shared:")
    results.append("  Matched   = {0}".format(shared_counts.get("matched", 0)))
    results.append("  Kept      = {0}".format(shared_counts.get("kept", 0)))
    results.append("  Protected = {0}".format(shared_counts.get("protected", 0)))
    results.append("  Errors    = {0}".format(shared_counts.get("errors", 0)))
    if ListOnly:
        results.append("  Listed    = {0}".format(shared_counts.get("listed", 0)))
    else:
        results.append("  Deleted   = {0}".format(shared_counts.get("deleted", 0)))
    results.append("  GUID: D={0}, R={1}, N/A={2}".format(
        shared_guid.get("DETERMINISTIC", 0),
        shared_guid.get("RANDOM", 0),
        shared_guid.get("#N/A", 0)
    ))

    results.append("")
    results.append("Project:")
    if not PurgeProjectParams:
        results.append("  Disabled (PurgeProjectParams=False)")
        return

    results.append("  Matched   = {0}".format(project_counts.get("matched", 0)))
    results.append("  Kept      = {0}".format(project_counts.get("kept", 0)))
    results.append("  Skipped   = {0}".format(project_counts.get("skipped", 0)))
    results.append("  Errors    = {0}".format(project_counts.get("errors", 0)))
    if ListOnly:
        results.append("  Listed    = {0}".format(project_counts.get("listed", 0)))
    else:
        results.append("  Deleted   = {0}".format(project_counts.get("deleted", 0)))
    results.append("  GUID: D={0}, R={1}, N/A={2}".format(
        project_guid.get("DETERMINISTIC", 0),
        project_guid.get("RANDOM", 0),
        project_guid.get("#N/A", 0)
    ))

# ------------------------------------------------------------
# Inputs
# ------------------------------------------------------------
PrefixTarget = parse_patterns(IN[0])
ForcePatterns = parse_patterns(IN[1])
KeepPatterns = parse_patterns(IN[2])

PurgeProjectParams = bool(IN[3]) if len(IN) > 3 and IN[3] is not None else False
ListOnly = bool(IN[4]) if len(IN) > 4 and IN[4] is not None else False

# IN[5] show legend + summary (False by default)
ShowLegend = bool(IN[5]) if len(IN) > 5 and IN[5] is not None else False

# ------------------------------------------------------------
# Defaults
# ------------------------------------------------------------
if not PrefixTarget:
    PrefixTarget = ["*"]

if not KeepPatterns:
    KeepPatterns = ["ae*", "__*"]

ForceActive = bool(ForcePatterns)

# ------------------------------------------------------------
# Revit helpers
# ------------------------------------------------------------
def binding_info(defn):
    if not bindings.Contains(defn):
        return "Unbound"

    b = bindings.get_Item(defn)
    scope = "Instance" if isinstance(b, InstanceBinding) else "Type"
    try:
        cats = sorted([c.Name for c in b.Categories])
        cat_str = ", ".join(cats) if cats else "No Categories"
    except:
        cat_str = "No Categories"
    return "{0} | {1}".format(scope, cat_str)

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

shared_counts = {"matched": 0, "kept": 0, "protected": 0, "deleted": 0, "errors": 0, "listed": 0, "skipped": 0}
project_counts = {"matched": 0, "kept": 0, "protected": 0, "deleted": 0, "errors": 0, "listed": 0, "skipped": 0}

shared_guid_counts = {"DETERMINISTIC": 0, "RANDOM": 0, "#N/A": 0}
project_guid_counts = {"DETERMINISTIC": 0, "RANDOM": 0, "#N/A": 0}

if ShowLegend:
    add_legend(results, PrefixTarget, ForcePatterns, KeepPatterns, PurgeProjectParams, ListOnly)

tg = TransactionGroup(doc, "Parameter purge")
tg.Start()

# ============================================================
# SHARED PARAMETERS
# ============================================================
add_header(results, "SHARED PARAMETERS")

t1 = Transaction(doc, "Shared Parameters")
t1.Start()

shared_params = FilteredElementCollector(doc).OfClass(SharedParameterElement).ToElements()

for sp in shared_params:
    defn = sp.GetDefinition()
    name = sp.Name
    name_l = name.lower()

    # Phase 1: Prefix candidate
    if not matches_any(name_l, PrefixTarget):
        continue

    guid_flag = guid_classification_for_shared_param(sp, name)
    shared_guid_counts[guid_flag] = shared_guid_counts.get(guid_flag, 0) + 1

    # Phase 2: Keep exclusion (absolute)
    if matches_any(name_l, KeepPatterns):
        shared_counts["kept"] += 1
        if ListOnly:
            line = "[LIST] [Shared] {0} | KEPT".format(name)
            shared_counts["listed"] += 1
        else:
            line = "+++Kept [Shared] {0}".format(name)
        results.append(append_guid_flag(line, guid_flag))
        continue

    shared_counts["matched"] += 1

    bind = binding_info(defn)
    sched = used_in_schedules(defn)
    in_use = bool(sched)

    # Phase 3: Force logic
    force_hit = matches_any(name_l, ForcePatterns)

    if ListOnly:
        status = "MATCH"
        extra = ""
        if in_use and not (ForceActive and force_hit):
            status = "PROTECTED"
            shared_counts["protected"] += 1
        if sched:
            extra = " | Schedules: " + ", ".join(sched[:5])
        line = "[LIST] [Shared] {0} | {1} | {2}{3}".format(name, bind, status, extra)
        shared_counts["listed"] += 1
        results.append(append_guid_flag(line, guid_flag))
        continue

    if in_use and not (ForceActive and force_hit):
        extra = " | Schedules: " + ", ".join(sched[:5]) if sched else ""
        line = "!!!PROTECTED [Shared] {0} | {1}{2}".format(name, bind, extra)
        shared_counts["protected"] += 1
        results.append(append_guid_flag(line, guid_flag))
        continue

    try:
        doc.Delete(sp.Id)
        tag = "-DelForce" if force_hit else "--Deleted"
        line = "{0} [Shared] {1} | {2}".format(tag, name, bind)
        shared_counts["deleted"] += 1
        results.append(append_guid_flag(line, guid_flag))
    except Exception as e:
        line = "[SYSTEM] [Shared] {0} | {1}".format(name, e)
        shared_counts["errors"] += 1
        results.append(append_guid_flag(line, guid_flag))

t1.Commit()

# ============================================================
# PROJECT PARAMETERS
# ============================================================
add_header(results, "PROJECT PARAMETERS (NON-SHARED)")

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

        guid_flag = guid_classification_for_project_param(pe)  # always #N/A
        project_guid_counts[guid_flag] = project_guid_counts.get(guid_flag, 0) + 1

        # Phase 2: Keep exclusion
        if matches_any(name_l, KeepPatterns):
            project_counts["kept"] += 1
            if ListOnly:
                line = "[LIST] [Project] {0} | KEPT".format(name)
                project_counts["listed"] += 1
            else:
                line = "+++Kept [Project] {0}".format(name)
            results.append(append_guid_flag(line, guid_flag))
            continue

        project_counts["matched"] += 1

        # Phase 3: Force permission only
        force_hit = matches_any(name_l, ForcePatterns)

        if ListOnly:
            status = "MATCH" if ForceActive else "MATCH (blind)"
            line = "[LIST] [Project] {0} | {1}".format(name, status)
            project_counts["listed"] += 1
            results.append(append_guid_flag(line, guid_flag))
            continue

        if not ForceActive and not force_hit:
            line = "!!!SKIPPED [Project] {0} | No usage detection".format(name)
            project_counts["skipped"] += 1
            results.append(append_guid_flag(line, guid_flag))
            continue

        try:
            doc.Delete(pe.Id)
            line = "-DelForce [Project] {0}".format(name)
            project_counts["deleted"] += 1
            results.append(append_guid_flag(line, guid_flag))
        except Exception as e:
            line = "[SYSTEM] [Project] {0} | {1}".format(name, e)
            project_counts["errors"] += 1
            results.append(append_guid_flag(line, guid_flag))

    t2.Commit()
else:
    # Project params disabled; no per-param GUID flags to emit here
    results.append("Disabled (PurgeProjectParams=False)")

tg.Assimilate()

# ------------------------------------------------------------
# Summary (only when ShowLegend=True)
# ------------------------------------------------------------
if ShowLegend:
    add_section_summary(results, "SHARED", shared_counts, shared_guid_counts, ListOnly)
    if PurgeProjectParams:
        add_section_summary(results, "PROJECT", project_counts, project_guid_counts, ListOnly)
    add_overall_summary(results, shared_counts, shared_guid_counts, project_counts, project_guid_counts, PurgeProjectParams, ListOnly)

OUT = results
