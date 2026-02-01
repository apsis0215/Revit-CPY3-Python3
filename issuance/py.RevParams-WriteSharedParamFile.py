# [py.RevParams-WriteSharedParamFile.py]
# V00-07-2026-02-01t1519p
# encoding: utf-8
# Purpose and IO:
#   Manual inputs:
#     IN[0]=ParamGroupAssignment (string)                     # stored for downstream (this node does NOT load/bind)
#     IN[1]=RevisionParamPrefix (string) default "REV."       # used as literal prefix in ParamName
#     IN[2]=MakeParamsNonUserModifiable (bool) default False  # written into USERMODIFIABLE column for NEW params AND UPDATED existing params
#     IN[3]=revisionsData (list[dict]) from py.Revisions-InProject-Data.py OUT[0]
#
#   Behavior (NO Revit API loading/binding here):
#     0) Shared parameter file path is STABLE per-model:
#          %TEMP%\Revisions_<ModelName>.txt
#     1) Build canonical ParamName (FORCE 6-bit) per revision:
#          ParamName := {RevPrefix}{yyyymmdd}{snippet}
#          - max ParamName length for forced 6-bit encoder is 21 chars
#     2) Deterministic GUID is computed from ParamName (FORCE 6-bit, VBA-compatible charset)
#        - Characters NOT in the charset are substituted with '.' (index 0)
#     3) If file exists: PARSE existing PARAM rows and UPSERT by GUID:
#        - If GUID exists -> UPDATE row fields:
#            NAME, VISIBLE=1, DESCRIPTION (tooltip), USERMODIFIABLE
#        - If GUID missing -> APPEND new PARAM row
#     4) DESCRIPTION (tooltip) := full revision name (long form)
#     5) Output file path + packets for downstream node(s) (do not load yet)
#
#   OUT=list:
#     OUT[0]=SharedParamFilePath (string)
#     OUT[1]=ParamNames (list[string])                 # canonical names used for CURRENT revisions
#     OUT[2]=RevIdToParam (dict[str,str])              # revision id -> canonical param name
#     OUT[3]=Report (dict)
#     OUT[4]=ParamPacket (list[dict])                  # revision + param + guid bundle (CURRENT revisions)
#     OUT[5]=ParamNameToGuid (dict[str,str])           # canonical param name -> guid (CURRENT revisions)

import os
import re
import tempfile
from datetime import datetime

import clr
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

#####################################
## 0000_Constants()
#####################################
BASE_ALL = r""".1234ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz056789!\"#$%&'()*+,-./:;<=>?@[\]^`{|}~"""

DISCLAIMER = (
    "# Patent Pending: Deterministic reversible GUID encoding system\n"
    "# Inventor: Ron E. Allen\n"
    "# ©2026 Ron E. Allen - all rights reserved.\n"
)

GROUP_NAME_IN_FILE = "DynamoProjectLocal"

# Forced 6-bit => max length = floor(128/6) = 21
MAX_LEN_6BIT = int(128 / 6)  # 21

#####################################
## 0100_String-Helpers()
#####################################
def safe_str(x):
    """Comment: defensive string conversion."""
    try:
        return "" if x is None else str(x)
    except:
        return ""

def pad2(num_str):
    """Comment: 2-digit revision number formatting (best effort)."""
    try:
        n = int(str(num_str).strip())
        return "{:02d}".format(n)
    except:
        s = safe_str(num_str).strip()
        if len(s) >= 2:
            return s
        return ("0" + s) if s else "00"

def sanitize_for_param_name(name):
    """
    Comment: sanitize input for a Revit parameter name (NOT the compression).
    Keeps it readable and stable for downstream.
    """
    name = safe_str(name)
    for b in ["\n", "\r", "\t"]:
        name = name.replace(b, " ")
    name = " ".join(name.split())
    for ch in ["{", "}", "[", "]", "<", ">", "|", ";"]:
        name = name.replace(ch, "")
    return name.strip()

def sanitize_filename(name):
    """Comment: make a safe Windows filename stem."""
    s = safe_str(name).strip()
    if not s:
        return "UnnamedModel"
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", "_", s)
    s = s.strip("._ ")
    return s if s else "UnnamedModel"

#####################################
## 0150_Normalize-Inputs()
#####################################
def normalize_revisions_data(obj):
    """
    Comment: accept list[dict] or wrapped [[dict..]] and return list[dict].
    """
    if obj is None:
        return []
    if isinstance(obj, list):
        if len(obj) == 0:
            return []
        if isinstance(obj[0], dict):
            return obj
        if isinstance(obj[0], list) and obj[0] and isinstance(obj[0][0], dict):
            return obj[0]
    return []

#####################################
## 0200_Date-Normalization(yyyymmdd)
#####################################
def to_yyyymmdd(date_str):
    """
    Comment: best-effort convert RevisionDate to yyyymmdd.
    Accepts common formats:
      - YYYY-MM-DD / YYYY/MM/DD
      - MM/DD/YYYY
      - digits-only (tries yyyyMMdd, else mmddyyyy)
    Fallback: "00000000"
    """
    s = safe_str(date_str).strip()
    if not s:
        return "00000000"

    m = re.match(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s*$", s)
    if m:
        y = m.group(1)
        mo = "{:02d}".format(int(m.group(2)))
        d = "{:02d}".format(int(m.group(3)))
        return "{}{}{}".format(y, mo, d)

    m = re.match(r"^\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$", s)
    if m:
        mo = "{:02d}".format(int(m.group(1)))
        d = "{:02d}".format(int(m.group(2)))
        y = m.group(3)
        return "{}{}{}".format(y, mo, d)

    digits = re.sub(r"\D+", "", s)
    if len(digits) >= 8:
        digits = digits[:8]
        if digits.startswith("19") or digits.startswith("20"):
            return digits
        mm = digits[0:2]
        dd = digits[2:4]
        yy = digits[4:8]
        if yy.startswith("19") or yy.startswith("20"):
            return "{}{}{}".format(yy, mm, dd)

    return "00000000"

#####################################
## 0300_Snippet-Compression(~10 chars)
#####################################
def compress_desc_to_snippet(desc):
    """
    Comment: compress Description into alnum-only (A-Z0-9), removing separators.
    We upper-case to stabilize output and avoid locale casing surprises.
    """
    s = sanitize_for_param_name(desc).upper()
    s = re.sub(r"[^A-Z0-9]+", "", s)
    return s or "X"

def build_canonical_param_name(prefix, yyyymmdd, desc, max_len=MAX_LEN_6BIT, desired_snip=10):
    """
    Comment: canonical ParamName := {prefix}{yyyymmdd}{snippet}
    Ensures total length <= 21 for forced 6-bit encoding.
    """
    pfx = safe_str(prefix)
    base = "{}{}".format(pfx, yyyymmdd)
    remaining = max_len - len(base)
    if remaining <= 0:
        return base[:max_len]

    snippet = compress_desc_to_snippet(desc)
    snip_len = min(desired_snip, remaining)
    return (base + snippet[:snip_len])[:max_len]

#####################################
## 0400_Deterministic-GUID(VBA-Compatible, FORCE 6-bit)
#####################################
def _dec2bin(n, bits):
    """Comment: decimal -> fixed-width binary."""
    n = int(n)
    s = ""
    while n != 0:
        s = str(n % 2) + s
        n //= 2
    return (("0" * bits) + s)[-bits:]

def _bin2dec(bs):
    """Comment: binary string -> int."""
    res = 0
    for i in range(len(bs)):
        res += int(bs[-1 - i]) * (2 ** i)
    return res

def guid_encode_from_name_force6(var_name):
    """
    Comment: VBA-compatible deterministic GUID encoding (FORCED 6-bit).
    Illegal chars are substituted with '.' because idx=0 -> BASE_ALL[0] == '.'
    Returns: (guid_str, bit_size, name_used_for_guid)
    """
    sname = (var_name or "").strip()
    bit_size = 6

    max_len = int(128 / bit_size)  # 21
    sname = sname[:max_len]

    bin_string = ""
    for ch in sname:
        idx = BASE_ALL.find(ch)
        if idx < 0 or idx >= (2 ** bit_size):
            idx = 0
        bin_string += _dec2bin(idx, bit_size)

    bin_string += "0" * 128
    bin_string = bin_string[:127] + "1"  # forced 6-bit -> last bit = 1

    hex32 = ""
    while len(bin_string) > 0:
        byte_val = _bin2dec(bin_string[:8])
        hex32 += ("0" + format(byte_val, "X"))[-2:]
        bin_string = bin_string[8:]

    # ensure last nibble LSB set to 1
    last = int(hex32[-1], 16)
    last = (last & 0xE) | 1
    hex32 = hex32[:-1] + format(last, "X")

    guid_str = "{}-{}-{}-{}-{}".format(hex32[:8], hex32[8:12], hex32[12:16], hex32[16:20], hex32[20:32])

    return guid_str.upper(), bit_size, sname

#####################################
## 0500_File-Path(Stable-Per-Model)
#####################################
def get_model_based_sharedparam_path():
    """
    Comment: Stable shared parameter file path per model.
    Uses doc.PathName if available; else doc.Title.
    """
    doc = DocumentManager.Instance.CurrentDBDocument
    model_name = ""
    try:
        pn = safe_str(getattr(doc, "PathName", ""))
        if pn and pn.strip():
            model_name = os.path.splitext(os.path.basename(pn))[0]
    except:
        model_name = ""

    if not model_name:
        try:
            model_name = safe_str(getattr(doc, "Title", "")) or "UnnamedModel"
        except:
            model_name = "UnnamedModel"

    stem = sanitize_filename(model_name)
    td = tempfile.gettempdir()
    return os.path.join(td, "Revisions_{}.txt".format(stem)), stem

#####################################
## 0600_Read-Existing-File-And-Upsert()
#####################################
def parse_existing_guids_and_header(lines):
    """
    Comment: Parse existing PARAM GUIDs.
    Returns: (guid_set_upper, has_param_header)
    """
    guid_set = set()
    has_param_header = False

    for ln in lines:
        s = ln.rstrip("\n\r")
        if s.startswith("*PARAM"):
            has_param_header = True
        if s.startswith("PARAM\t"):
            parts = s.split("\t")
            if len(parts) >= 3:
                g = safe_str(parts[1]).strip().upper()
                if g:
                    guid_set.add(g)
    return guid_set, has_param_header

def build_new_file_header(group_name):
    """Comment: create a clean Revit shared parameter file header with disclaimer."""
    out = []
    out.append("# This is a Revit shared parameter file.")
    for ln in DISCLAIMER.splitlines():
        out.append(ln)
    out.extend([
        "*META\tVERSION\tMINVERSION",
        "META\t2\t1",
        "*GROUP\tID\tNAME",
        "GROUP\t1\t{}".format(group_name),
        "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE",
    ])
    return out

def build_param_line(guid, pname, tooltip, non_user_modifiable):
    """Comment: build a single PARAM row."""
    user_mod = "0" if bool(non_user_modifiable) else "1"
    tip = safe_str(tooltip).replace("\t", " ")
    return "PARAM\t{}\t{}\tTEXT\t\t1\t1\t{}\t{}".format(guid, pname, tip, user_mod)

def parse_param_rows(lines):
    """
    Comment: build a GUID->(rowIndex, parts) map for existing PARAM rows.
    Expected parts:
      0=PARAM,1=GUID,2=NAME,3=DATATYPE,4=DATACATEGORY,5=GROUP,6=VISIBLE,7=DESCRIPTION,8=USERMODIFIABLE
    """
    guid_to_row = {}
    for i, ln in enumerate(lines):
        s = safe_str(ln).rstrip("\n\r")
        if not s.startswith("PARAM\t"):
            continue
        parts = s.split("\t")
        if len(parts) < 9:
            continue
        g = safe_str(parts[1]).strip().upper()
        if g:
            guid_to_row[g] = (i, parts)
    return guid_to_row

def upsert_param_row(lines, guid_to_row, guid, pname, tooltip, non_user_modifiable):
    """
    Comment:
      If GUID exists -> UPDATE row: NAME, VISIBLE=1, DESCRIPTION, USERMODIFIABLE.
      If GUID missing -> APPEND new row.
    Returns: "added" | "updated" | "unchanged"
    """
    g = safe_str(guid).strip().upper()
    n = safe_str(pname).strip()
    tip = safe_str(tooltip).replace("\t", " ").strip()
    desired_user_mod = "0" if bool(non_user_modifiable) else "1"

    if g in guid_to_row:
        row_i, parts = guid_to_row[g]
        while len(parts) < 9:
            parts.append("")

        changed = False

        if safe_str(parts[2]) != n:
            parts[2] = n
            changed = True

        if safe_str(parts[6]) != "1":
            parts[6] = "1"
            changed = True

        if safe_str(parts[7]) != tip:
            parts[7] = tip
            changed = True

        if safe_str(parts[8]) != desired_user_mod:
            parts[8] = desired_user_mod
            changed = True

        if changed:
            lines[row_i] = "\t".join(parts)
            guid_to_row[g] = (row_i, parts)
            return "updated"
        return "unchanged"

    lines.append(build_param_line(g, n, tip, non_user_modifiable))
    guid_to_row[g] = (len(lines) - 1, lines[-1].split("\t"))
    return "added"

def safe_write_lines(path, lines):
    """
    Comment: write lines to path.
    If locked, write to an alternate file and return that path.
    """
    text = "\n".join(lines)
    try:
        with open(path, "w") as f:
            f.write(text)
        return path, None
    except Exception as ex:
        base, ext = os.path.splitext(path)
        for i in range(1, 50):
            alt = "{}_ALT{:02d}{}".format(base, i, ext)
            try:
                with open(alt, "w") as f:
                    f.write(text)
                return alt, "Primary file locked; wrote ALT instead: {}".format(safe_str(ex))
            except:
                continue
        return path, "Failed to write file (locked?): {}".format(safe_str(ex))

#####################################
## 0900_Main()
#####################################
param_group_assignment = IN[0] if IN and len(IN) > 0 and IN[0] is not None else "Text"
rev_prefix = IN[1] if IN and len(IN) > 1 and IN[1] else "REV."
make_num = IN[2] if IN and len(IN) > 2 and IN[2] is not None else False
raw_revisions = IN[3] if IN and len(IN) > 3 else None

revisions_data = normalize_revisions_data(raw_revisions)

notes = []
report = {
    "RuntimeStamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    "ParamGroupAssignment_Input": safe_str(param_group_assignment),
    "RevPrefix": safe_str(rev_prefix),
    "MakeNonUserModifiable": bool(make_num),
    "GroupNameInFile": GROUP_NAME_IN_FILE,
    "MaxNameLen_6bit": MAX_LEN_6BIT,
    "RevisionsData_Count": len(revisions_data),
}

sp_path, model_stem = get_model_based_sharedparam_path()
report["ModelStem"] = model_stem
report["SharedParamFilePath"] = sp_path

try:
    revs_sorted = sorted(revisions_data, key=lambda r: int(r.get("SequenceNumber", 10**9)))
except:
    revs_sorted = list(revisions_data)
    notes.append("Warning: revisionsData sort by SequenceNumber failed; using input order.")

param_packet = []
param_names = []
rev_id_to_param = {}
param_name_to_guid = {}

for r in revs_sorted:
    if not isinstance(r, dict):
        continue

    rid = r.get("Id", None)
    if rid is None:
        continue
    try:
        rid_int = int(rid)
    except:
        continue

    seq = r.get("SequenceNumber", 10**9)
    rev_num = safe_str(r.get("RevisionNumber", ""))
    rev_date_raw = safe_str(r.get("RevisionDate", ""))
    desc_raw = safe_str(r.get("Description", ""))

    yyyymmdd = to_yyyymmdd(rev_date_raw)
    pname = build_canonical_param_name(rev_prefix, yyyymmdd, desc_raw, max_len=MAX_LEN_6BIT, desired_snip=10)

    full_tip = sanitize_for_param_name("{}{}.{}.{}".format(
        safe_str(rev_prefix),
        pad2(rev_num),
        rev_date_raw,
        desc_raw
    ))

    guid, bit_size, name_used_for_guid = guid_encode_from_name_force6(pname)

    row = {
        "RevisionId": str(rid_int),
        "SequenceNumber": int(seq) if safe_str(seq).strip() else int(10**9),
        "RevisionNumber": rev_num,
        "RevisionDate": rev_date_raw,
        "Description": desc_raw,
        "ParamName": str(pname),
        "ParamGuid": str(guid),
        "BitSize": int(bit_size),
        "NameUsedForGuid": str(name_used_for_guid),
        "ParamTip": str(full_tip),
        "YYYYMMDD": str(yyyymmdd),
        "UserModifiableDesired": (False if bool(make_num) else True),
    }

    param_packet.append(row)
    param_names.append(str(pname))
    rev_id_to_param[rid_int] = str(pname)
    param_name_to_guid[str(pname)] = str(guid)

param_names_out = [str(x) for x in param_names]
rev_id_to_param_out = {str(k): str(v) for k, v in rev_id_to_param.items()}

report["ParamCount_CurrentRevs"] = len(param_names_out)

existing_lines = []
file_existed = os.path.exists(sp_path)
report["FileExisted"] = bool(file_existed)

if file_existed:
    try:
        with open(sp_path, "r") as f:
            existing_lines = f.read().splitlines()
    except Exception as ex:
        existing_lines = []
        notes.append("Warning: failed reading existing file; will rebuild header. {}".format(safe_str(ex)))

existing_guid_set, has_param_header = parse_existing_guids_and_header(existing_lines)
report["ExistingGuidCount"] = len(existing_guid_set)
report["ExistingHasParamHeader"] = bool(has_param_header)

if (not file_existed) or (not has_param_header) or (len(existing_lines) < 5):
    lines_out = build_new_file_header(GROUP_NAME_IN_FILE)
    report["HeaderMode"] = "RebuiltHeader"
else:
    lines_out = list(existing_lines)
    report["HeaderMode"] = "PreservedExisting"

guid_to_row = parse_param_rows(lines_out)

added = 0
updated = 0
unchanged = 0
added_sample = []
updated_sample = []

for row in param_packet:
    g = safe_str(row.get("ParamGuid")).upper()
    n = safe_str(row.get("ParamName"))
    tip = safe_str(row.get("ParamTip"))

    action = upsert_param_row(lines_out, guid_to_row, g, n, tip, make_num)

    if action == "added":
        added += 1
        if len(added_sample) < 20:
            added_sample.append({"ParamName": n, "Guid": g})
    elif action == "updated":
        updated += 1
        if len(updated_sample) < 20:
            updated_sample.append({"ParamName": n, "Guid": g})
    else:
        unchanged += 1

report["AddedNewParams"] = int(added)
report["UpdatedExistingParams"] = int(updated)
report["UnchangedParams"] = int(unchanged)
report["AddedSample"] = added_sample
report["UpdatedSample"] = updated_sample

final_path, warn = safe_write_lines(sp_path, lines_out)
if warn:
    notes.append(warn)
if final_path != sp_path:
    report["SharedParamFilePath_AltWritten"] = final_path
    sp_path = final_path

report["SharedParamFilePath"] = sp_path
report["WroteFile"] = True if os.path.exists(sp_path) else False
report["Notes"] = notes

OUT = [sp_path, param_names_out, rev_id_to_param_out, report, param_packet, param_name_to_guid]
