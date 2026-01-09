# PURPOSE:
# IN[0] = ViewSheet or list[ViewSheet]
# IN[1] = table data (list of dictionaries)
#
# OUT = list of dictionaries:
# {
#   "sheet": ViewSheet,
#   "header": str,   # header_general
#   "n_id": str,
#   "d_id": str,
#   "code": str,
#   "description": str
# }

import difflib
import re

sheets = IN[0]
table  = IN[1] or []

sheet_list = sheets if isinstance(sheets, list) else [sheets]

# -----------------------------
# HELPERS
# -----------------------------
def normalize(text):
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def is_level_00(row):
    nid = row.get("n_id", "")
    return nid.endswith("-00") and nid != "00-00"

def get_row_by_nid(nid):
    for r in table:
        if r.get("n_id") == nid:
            return r
    return None

def get_row_by_code(code2):
    code2 = (code2 or "").upper()
    if not code2:
        return None
    for r in table:
        c = (r.get("code") or "").upper()
        if c == code2:
            return r
    return None

def row_search_string(row):
    # keep it focused: description + header_general + code
    return normalize("{} {} {}".format(
        row.get("header_general",""),
        row.get("code",""),
        row.get("description","")
    ))

def guess_header_general(sheet_name_norm):
    # quick intent classifier to restrict fuzzy candidates
    # add/adjust terms as needed
    if any(k in sheet_name_norm for k in ["floor plan", "rcp", "reflected ceiling", "elevation", "section", "detail", "schedule"]):
        return "ARCHITECTURAL"
    if any(k in sheet_name_norm for k in ["site", "grading", "civil"]):
        return "ARCHITECTURAL"
    if any(k in sheet_name_norm for k in ["general", "code", "notes", "index", "cover"]):
        return "GENERAL"
    if any(k in sheet_name_norm for k in ["struct", "foundation", "framing"]):
        return "STRUCTURAL"
    if any(k in sheet_name_norm for k in ["interior", "finish", "furniture"]):
        return "INTERIORS"
    if any(k in sheet_name_norm for k in ["plumb", "domestic water", "sanitary", "storm"]):
        return "PLUMBING"
    if any(k in sheet_name_norm for k in ["mech", "hvac", "duct", "air", "boiler", "chiller"]):
        return "MECHANICAL"
    if any(k in sheet_name_norm for k in ["elect", "lighting", "power", "panel"]):
        return "ELECTRICAL"
    if any(k in sheet_name_norm for k in ["telecom", "data", "network", "it", "av", "audio", "cctv", "security"]):
        return "TECHNOLOGY"
    if any(k in sheet_name_norm for k in ["shop drawing", "contractor"]):
        return "CONTRACTOR"
    if any(k in sheet_name_norm for k in ["ops", "operations", "facility"]):
        return "OPERATIONS"
    if any(k in sheet_name_norm for k in ["estimate", "estimating", "cost"]):
        return "ESTIMATING"
    return None

def fuzzy_match(ref_norm, candidates, cutoff=0.48):
    best_row = None
    best_score = 0.0

    for r in candidates:
        score = difflib.SequenceMatcher(None, ref_norm, row_search_string(r)).ratio()
        if score > best_score:
            best_score = score
            best_row = r

    return best_row if best_score >= cutoff else None

# -----------------------------
# FALLBACK ROW (00-00)
# -----------------------------
fallback_row = get_row_by_nid("00-00") or {
    "n_id": "00-00",
    "d_id": "##",
    "code": "##",
    "header_general": "GENERAL",
    "description": "General-unmatched"
}

# pre-filtered candidates (exclude ##-00 except 00-00)
base_candidates = [r for r in table if not is_level_00(r) and r.get("n_id") != "00-00"]

# -----------------------------
# MAIN LOOP
# -----------------------------
results = []

for s in sheet_list:
    if not s:
        continue

    sheet_db = UnwrapElement(s)
    if not sheet_db:
        continue

    sheet_number = sheet_db.SheetNumber or ""
    sheet_name   = sheet_db.Name or ""

    match = None

    # 1) PRIMARY: first two letters of sheet number → table.code
    m = re.match(r"\s*([A-Za-z]{2})", sheet_number)
    if m:
        match = get_row_by_code(m.group(1))

    # 2) SECONDARY: restrict candidates by header intent from NAME
    name_norm = normalize(sheet_name)
    header_guess = guess_header_general(name_norm)

    if not match:
        if header_guess:
            candidates = [r for r in base_candidates if (r.get("header_general") or "").upper() == header_guess]
        else:
            candidates = base_candidates

        # 3) FUZZY within restricted candidates (name only, then number+name)
        match = fuzzy_match(name_norm, candidates, cutoff=0.48)

        if not match:
            combined = normalize("{} {}".format(sheet_number, sheet_name))
            match = fuzzy_match(combined, candidates, cutoff=0.48)

    # 4) FINAL: 00-00
    row = match if match else fallback_row

    results.append({
        "sheet": s,  # Dynamo ViewSheet pointer for later steps
        "header": row.get("header_general"),
        "n_id": row.get("n_id"),
        "d_id": row.get("d_id"),
        "code": row.get("code"),
        "description": row.get("description")
    })

OUT = results
