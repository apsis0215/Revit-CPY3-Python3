# -*- coding: utf-8 -*-
# py-LinePattern-Remap-Fuzzy+Purge.py
# Author: Apsis0215 / ZTN
#
# Purpose:
# Fuzzy remap and optional purge of Revit LinePatternElements.
#
# "Register" naming requirement:
# - Execute (mergeLinetypes=True)  -> status/registerAs: "Line Pattern Fuzzy Remap & Purge"
# - Preview / non-execute (False)  -> status/registerAs: "LIST Line Pattern Fuzzy Remap & Purge"
#
# IO:
# IN[0] keepCsv: CSV/newline string (or list) of KEEP names. Supports * and ? wildcards. Case-insensitive.
# IN[1] mergeLinetypes (bool): False=preview only, True=execute remap + delete old patterns
# OUT: dict report (includes status + mode)

import clr

# RevitServices: document + Dynamo transaction wrapper
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager  # get doc
from RevitServices.Transactions import TransactionManager  # Dynamo transaction wrapper

# Revit API
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector, LinePatternElement,
    BuiltInCategory, BuiltInParameter,
    GraphicsStyleType, View,
    TransactionGroup, ElementId
)

# Python stdlib
import re
import difflib

doc = DocumentManager.Instance.CurrentDBDocument

# ----------------------------
# Helpers
# ----------------------------

def Flatten(x):
    # Flatten nested lists/tuples into a single list (Dynamo-safe).
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        out = []
        for i in x:
            out.extend(Flatten(i))
        return out
    return [x]

def ParseKeepCsvToRegex(csv_in):
    # Parse KEEP list into compiled regex patterns (supports * and ?, case-insensitive).
    raw = Flatten(csv_in)

    parts = []
    for s in raw:
        if s is None:
            continue
        try:
            s2 = str(s)
        except Exception:
            continue
        for chunk in re.split(r"[,\n\r]+", s2):
            chunk = chunk.strip()
            if chunk:
                parts.append(chunk)

    regexes = []
    for p in parts:
        p_esc = re.escape(p)
        p_re = p_esc.replace(r"\*", ".*").replace(r"\?", ".")
        regexes.append(re.compile(r"^" + p_re + r"$", re.IGNORECASE))

    return regexes

def Sig(lp_elem):
    # Signature for a line pattern definition: [[segmentTypeString, normalizedLength], ...]
    # Normalized to total positive length to make scaled patterns comparable.
    try:
        lp = lp_elem.GetLinePattern()
        segs = []
        total = 0.0

        for seg in lp.Segments:
            t = seg.Type.ToString()
            l = float(seg.Length)
            segs.append([t, l])
            if l > 0.0:
                total += l

        if total > 0.0:
            for s in segs:
                s[1] = round(s[1] / total, 6)
        else:
            for s in segs:
                s[1] = 0.0

        return segs
    except Exception:
        return []

def DefSim(a, b):
    # Similarity score between two signatures.
    # - segment type match weighted 0.6
    # - normalized length similarity weighted 0.4
    # Penalizes different segment counts.
    if not a or not b:
        return 0.0

    n = min(len(a), len(b))
    if n == 0:
        return 0.0

    score = 0.0
    for i in range(n):
        ta, la = a[i]
        tb, lb = b[i]

        type_score = 1.0 if ta == tb else 0.0

        if la == 0.0 and lb == 0.0:
            len_score = 1.0
        else:
            len_score = 1.0 - abs(la - lb)
            if len_score < 0.0:
                len_score = 0.0

        score += (type_score * 0.6 + len_score * 0.4)

    score = (score / float(n)) * (float(n) / float(max(len(a), len(b))))
    return round(score, 6)

def PickBestTarget(old_pat, targets, target_sigs, target_by_name_lower):
    # Priority:
    # 1) exact name match (case-insensitive)
    # 2) fuzzy: definition(0.8) + name similarity(0.2)
    old_name = old_pat.Name

    exact = target_by_name_lower.get(old_name.lower())
    if exact:
        return exact, 1.0, 1.0, 1.0, "exact-name"

    old_sig = Sig(old_pat)

    best = None
    best_combo = -1.0
    best_def = 0.0
    best_name = 0.0

    for t in targets:
        d = DefSim(old_sig, target_sigs[t.Id.IntegerValue])
        ns = difflib.SequenceMatcher(None, old_name.lower(), t.Name.lower()).ratio()
        combo = d * 0.8 + ns * 0.2

        if combo > best_combo:
            best_combo = combo
            best = t
            best_def = d
            best_name = ns

    return best, best_def, round(best_name, 6), round(best_combo, 6), "fuzzy-def+name"

# ----------------------------
# Inputs
# ----------------------------

keepCsv = IN[0]
mergeLinetypes = bool(IN[1]) if len(IN) > 1 else False

# "Register" labels (exclusive)
REGISTER_EXEC = "Line Pattern Fuzzy Remap & Purge"
REGISTER_LIST = "LIST Line Pattern Fuzzy Remap & Purge"
registerAs = REGISTER_EXEC if mergeLinetypes else REGISTER_LIST

# ----------------------------
# Collect patterns and build sets
# ----------------------------

all_patterns = list(FilteredElementCollector(doc).OfClass(LinePatternElement))
rx_list = ParseKeepCsvToRegex(keepCsv)

# Resolve KEEP targets by matching existing line pattern names against KEEP regexes
merge_targets = []
for p in all_patterns:
    for rx in rx_list:
        if rx.match(p.Name):
            merge_targets.append(p)
            break

# Unique targets by ElementId
seen_t = set()
uniq_targets = []
for t in merge_targets:
    tid = t.Id.IntegerValue
    if tid not in seen_t:
        seen_t.add(tid)
        uniq_targets.append(t)
merge_targets = uniq_targets

merge_target_ids = set([t.Id.IntegerValue for t in merge_targets])
merge_target_names = sorted(list(set([t.Name for t in merge_targets])))

# Candidates are everything NOT in KEEP targets
candidates = [p for p in all_patterns if p.Id.IntegerValue not in merge_target_ids]
candidate_names = [p.Name for p in candidates]

# ----------------------------
# Guards / no-op
# ----------------------------

def BuildOut(mode, reason, mapping_pairs=None, mapping_rows=None, replaced_counts=None, deleted=None, failed_deletion=None, skipped=None):
    return {
        "status": registerAs,            # requested "register" string
        "registerAs": registerAs,        # explicit field too
        "mode": mode,                   # "no-op" | "preview" | "execute"
        "reason": reason,
        "mergeLinetypes": bool(mergeLinetypes),
        "keepCsv": keepCsv,
        "merge_targets": merge_target_names,
        "candidates": sorted(candidate_names),
        "mapping_new_left_old_right": mapping_pairs or [],
        "mapping_details": mapping_rows or [],
        "replaced_counts": replaced_counts or {},
        "deleted": deleted or [],
        "failed_deletion": failed_deletion or [],
        "skipped": skipped or []
    }

if not rx_list:
    OUT = BuildOut(
        mode="no-op",
        reason="keepCsv IN[0] produced 0 patterns (empty/invalid)."
    )

elif not merge_targets:
    OUT = BuildOut(
        mode="no-op",
        reason="No existing LinePatternElement names matched keepCsv; merge targets = 0."
    )

else:
    # ----------------------------
    # Build mapping (always) for preview/execution
    # ----------------------------

    target_sigs = {t.Id.IntegerValue: Sig(t) for t in merge_targets}
    target_by_name_lower = {t.Name.lower(): t for t in merge_targets}

    mapping_pairs = []          # list of "New <- Old" strings
    mapping_rows = []           # detailed mapping rows with scores
    skipped = []                # old patterns that could not map

    oldIdInt_to_newId = {}      # oldIdInt -> new ElementId

    for old_pat in candidates:
        best, s_def, s_name, s_combo, method = PickBestTarget(
            old_pat, merge_targets, target_sigs, target_by_name_lower
        )
        if best is None:
            skipped.append(old_pat.Name)
            continue

        mapping_pairs.append(best.Name + " <- " + old_pat.Name)
        mapping_rows.append({
            "new": best.Name,
            "old": old_pat.Name,
            "method": method,
            "def_score": s_def,
            "name_score": s_name,
            "combo": s_combo
        })

        oldIdInt_to_newId[old_pat.Id.IntegerValue] = best.Id

    # ----------------------------
    # Preview mode
    # ----------------------------
    if not mergeLinetypes:
        OUT = BuildOut(
            mode="preview",
            reason=None,
            mapping_pairs=mapping_pairs,
            mapping_rows=mapping_rows,
            skipped=skipped
        )

    # ----------------------------
    # Execute mode: replace + delete, wrapped in named Undo group
    # ----------------------------
    else:
        tg = TransactionGroup(doc, REGISTER_EXEC)
        tg_started = False
        in_tx = False

        try:
            tg.Start()
            tg_started = True

            # Dynamo-managed write transaction (single transaction)
            TransactionManager.Instance.EnsureInTransaction(doc)
            in_tx = True

            oldIdInt_set = set(oldIdInt_to_newId.keys())
            oldIdInt_to_name = {p.Id.IntegerValue: p.Name for p in candidates}

            # Replace counts for reporting
            replaced_line_count = {}  # oldName -> occurrences replaced on model lines
            replaced_cat_count = {}   # oldName -> occurrences replaced in categories
            replaced_vt_count = {}    # oldName -> occurrences replaced in view templates

            # Replace in Model Lines
            for el in FilteredElementCollector(doc).WhereElementIsNotElementType().OfCategory(BuiltInCategory.OST_Lines):
                try:
                    param = el.get_Parameter(BuiltInParameter.LINE_PATTERN)
                    if not param:
                        continue
                    oid = param.AsElementId()
                    if oid and oid.IntegerValue in oldIdInt_set:
                        param.Set(oldIdInt_to_newId[oid.IntegerValue])
                        nm = oldIdInt_to_name.get(oid.IntegerValue, str(oid.IntegerValue))
                        replaced_line_count[nm] = replaced_line_count.get(nm, 0) + 1
                except Exception:
                    pass

            # Replace in Categories / Object Styles (Projection + Cut where supported)
            for cat in doc.Settings.Categories:
                # Projection
                try:
                    oid = cat.GetLinePatternId(GraphicsStyleType.Projection)
                    if oid and oid.IntegerValue in oldIdInt_set:
                        cat.SetLinePatternId(GraphicsStyleType.Projection, oldIdInt_to_newId[oid.IntegerValue])
                        nm = oldIdInt_to_name.get(oid.IntegerValue, str(oid.IntegerValue))
                        replaced_cat_count[nm] = replaced_cat_count.get(nm, 0) + 1
                except Exception:
                    pass

                # Cut
                try:
                    oid = cat.GetLinePatternId(GraphicsStyleType.Cut)
                    if oid and oid.IntegerValue in oldIdInt_set:
                        cat.SetLinePatternId(GraphicsStyleType.Cut, oldIdInt_to_newId[oid.IntegerValue])
                        nm = oldIdInt_to_name.get(oid.IntegerValue, str(oid.IntegerValue))
                        replaced_cat_count[nm] = replaced_cat_count.get(nm, 0) + 1
                except Exception:
                    pass

            # Replace in View Templates: category overrides (Projection + Cut)
            cat_ids = [c.Id for c in doc.Settings.Categories]
            for vt in FilteredElementCollector(doc).OfClass(View):
                try:
                    if not vt.IsTemplate:
                        continue
                except Exception:
                    continue

                for cid in cat_ids:
                    try:
                        ogs = vt.GetCategoryOverrides(cid)
                        modified = False

                        pid = ogs.GetProjectionLinePatternId()
                        if pid and pid.IntegerValue in oldIdInt_set:
                            ogs.SetProjectionLinePatternId(oldIdInt_to_newId[pid.IntegerValue])
                            nm = oldIdInt_to_name.get(pid.IntegerValue, str(pid.IntegerValue))
                            replaced_vt_count[nm] = replaced_vt_count.get(nm, 0) + 1
                            modified = True

                        cid2 = ogs.GetCutLinePatternId()
                        if cid2 and cid2.IntegerValue in oldIdInt_set:
                            ogs.SetCutLinePatternId(oldIdInt_to_newId[cid2.IntegerValue])
                            nm = oldIdInt_to_name.get(cid2.IntegerValue, str(cid2.IntegerValue))
                            replaced_vt_count[nm] = replaced_vt_count.get(nm, 0) + 1
                            modified = True

                        if modified:
                            vt.SetCategoryOverrides(cid, ogs)

                    except Exception:
                        pass

            # Delete OLD patterns after reassignment
            deleted = []
            failed_deletion = []

            for old_id_int in list(oldIdInt_set):
                try:
                    old_eid = ElementId(old_id_int)
                    old_elem = doc.GetElement(old_eid)

                    # Extra safety: skip read-only elements (Revit will usually fail delete anyway)
                    try:
                        if old_elem and hasattr(old_elem, "IsReadOnly") and old_elem.IsReadOnly:
                            failed_deletion.append(old_elem.Name)
                            continue
                    except Exception:
                        pass

                    old_name = old_elem.Name if old_elem else oldIdInt_to_name.get(old_id_int, str(old_id_int))
                    doc.Delete(old_eid)
                    deleted.append(old_name)
                except Exception:
                    failed_deletion.append(oldIdInt_to_name.get(old_id_int, str(old_id_int)))

            # Close Dynamo transaction
            TransactionManager.Instance.TransactionTaskDone()
            in_tx = False

            # Commit undo group
            tg.Assimilate()

            OUT = BuildOut(
                mode="execute",
                reason=None,
                mapping_pairs=mapping_pairs,
                mapping_rows=mapping_rows,
                replaced_counts={
                    "model_lines": replaced_line_count,
                    "categories": replaced_cat_count,
                    "view_templates": replaced_vt_count
                },
                deleted=deleted,
                failed_deletion=failed_deletion,
                skipped=skipped
            )

        except Exception as ex:
            # Best-effort cleanup
            try:
                if in_tx:
                    TransactionManager.Instance.TransactionTaskDone()
            except Exception:
                pass
            try:
                if tg_started:
                    tg.RollBack()
            except Exception:
                pass

            OUT = BuildOut(
                mode="execute",
                reason="Exception: {0}".format(str(ex)),
                mapping_pairs=mapping_pairs,
                mapping_rows=mapping_rows,
                skipped=skipped
            )
