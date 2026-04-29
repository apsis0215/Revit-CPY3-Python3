# /Dynamo/py-resolve-export-path-from-dc-clsid.py
# Encoding: utf-8
#
# PURPOSE
# This Dynamo Python script resolves a reliable export file path for the current Revit model.
#
# OUTPUT CONTRACT
# OUT[0] = final target file path
# OUT[1] = additional info/details as a multi-line plain-text export block
#
# RESOLUTION ORDER
# 1. If IN[1] contains an override path, resolve special tokens and environment variables.
#    - If valid, use it immediately.
#    - If invalid, stop and use Desktop fallback.
# 2. If no valid override is supplied, search HKCR\CLSID for the Desktop Connector shell item.
# 3. Read the Desktop Connector local root from:
#    CLSID\Instance\InitPropertyBag\TargetFolderPath
# 4. If that fails, stop and use Desktop fallback.
# 5. Check whether the current document is workshared.
# 6. Search under the Desktop Connector local root for the actual current model file.
# 7. If found, use that model's folder and strip the Revit extension from the matched file name.
# 8. If any step fails, stop and use Desktop fallback.
#
# INPUTS
# IN[0] = desired export extension, such as ".txt", ".csv", ".params.txt", or "log"
#         If null, empty, or missing, ".txt" is used.
#
# IN[1] = optional override path
#         Supported examples:
#         - C:\Temp
#         - C:\Temp\MyFolder
#         - %desktop%
#         - %desktop%\Exports
#         - %userprofile%\Documents
#         - %downloads%
#         - %localappdata%\Temp
#
# NOTES
# - The script expands both custom shell-like tokens and normal Windows environment variables.
# - If an override path points to a file path whose parent folder exists, that parent folder is used.
# - The details block is formatted for easy copy/paste back into ChatGPT or a form.

import clr
import os
import re

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import ModelPathUtils

clr.AddReference("System")
from System import Environment

clr.AddReference("mscorlib")
from Microsoft.Win32 import Registry

doc = DocumentManager.Instance.CurrentDBDocument


# ------------------------------------------------------------
# STRING HELPERS
# ------------------------------------------------------------

def _safe_str(value, default=""):
    """
    Safely convert any value to a string.
    """
    try:
        if value is None:
            return default
        return str(value)
    except:
        return default


def _normalize_extension(value, default_ext=".txt"):
    """
    Normalize the requested extension and default to .txt when blank.
    """
    ext = _safe_str(value, "").strip()
    if not ext:
        return default_ext
    if not ext.startswith("."):
        ext = "." + ext
    return ext


def _strip_revit_extension(name):
    """
    Remove a trailing Revit file extension from a file or title.
    """
    s = _safe_str(name, "").strip()
    return re.sub(r"(?i)\.(rvt|rfa|rte|rft)$", "", s).strip()


def _sanitize_filename(name, fallback="Model"):
    """
    Remove invalid Windows filename characters and ensure a non-empty result.
    """
    s = _safe_str(name, fallback).strip()
    if not s:
        s = fallback
    s = re.sub(r'[<>:"/\\\\|?*]+', "_", s)
    s = s.strip(" .")
    return s or fallback


# ------------------------------------------------------------
# FOLDER HELPERS
# ------------------------------------------------------------

def _get_desktop_folder():
    """
    Return the current user's Desktop folder path.
    """
    return Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory)


def _folder_exists(path_value):
    """
    Check whether a folder exists.
    """
    try:
        return bool(path_value) and os.path.isdir(path_value)
    except:
        return False


def _file_exists(path_value):
    """
    Check whether a file exists.
    """
    try:
        return bool(path_value) and os.path.isfile(path_value)
    except:
        return False


# ------------------------------------------------------------
# PATH TOKEN HELPERS
# ------------------------------------------------------------

def _get_special_folder_map():
    """
    Return a map of supported shell-like folder tokens.
    """
    return {
        "%desktop%": Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
        "%desktopdirectory%": Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
        "%documents%": Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
        "%mydocuments%": Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
        "%personal%": Environment.GetFolderPath(Environment.SpecialFolder.Personal),
        "%favorites%": Environment.GetFolderPath(Environment.SpecialFolder.Favorites),
        "%programfiles%": Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
        "%programfilesx86%": Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
        "%appdata%": Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "%localappdata%": Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "%commonappdata%": Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
        "%userprofile%": Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        "%mypictures%": Environment.GetFolderPath(Environment.SpecialFolder.MyPictures),
        "%mypicturesfolder%": Environment.GetFolderPath(Environment.SpecialFolder.MyPictures),
        "%templates%": Environment.GetFolderPath(Environment.SpecialFolder.Templates),
        "%startup%": Environment.GetFolderPath(Environment.SpecialFolder.Startup),
        "%commonstartup%": Environment.GetFolderPath(Environment.SpecialFolder.CommonStartup),
        "%sendto%": Environment.GetFolderPath(Environment.SpecialFolder.SendTo),
        "%startmenu%": Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
        "%commonstartmenu%": Environment.GetFolderPath(Environment.SpecialFolder.CommonStartMenu),
        "%programs%": Environment.GetFolderPath(Environment.SpecialFolder.Programs),
        "%commonprograms%": Environment.GetFolderPath(Environment.SpecialFolder.CommonPrograms),
        "%temp%": Environment.GetEnvironmentVariable("TEMP") or "",
        "%tmp%": Environment.GetEnvironmentVariable("TMP") or "",
        "%home%": Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
    }


def _try_get_downloads_folder():
    """
    Best-effort Downloads folder resolution.
    """
    try:
        user_profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)
        candidate = os.path.join(user_profile, "Downloads")
        if _folder_exists(candidate):
            return candidate
    except:
        pass
    return ""


def _expand_special_tokens(path_value):
    """
    Expand supported custom tokens, shell-like tokens, and normal environment variables.
    """
    raw = _safe_str(path_value, "").strip()
    if not raw:
        return ""

    resolved = raw
    token_map = _get_special_folder_map()

    downloads = _try_get_downloads_folder()
    if downloads:
        token_map["%downloads%"] = downloads

    for token, token_value in token_map.items():
        if token_value:
            resolved = re.sub(re.escape(token), lambda m: token_value, resolved, flags=re.IGNORECASE)

    resolved = Environment.ExpandEnvironmentVariables(resolved)
    resolved = os.path.expandvars(resolved)
    resolved = os.path.expanduser(resolved)

    return os.path.normpath(resolved)


def _resolve_override_folder(override_value):
    """
    Resolve the override input to a usable folder path.
    Supports folder paths, file paths, and tokenized paths.
    """
    resolved = _expand_special_tokens(override_value)

    if not resolved:
        return {
            "provided": False,
            "input": _safe_str(override_value, ""),
            "resolved": "",
            "valid": False,
            "folder": ""
        }

    if _folder_exists(resolved):
        return {
            "provided": True,
            "input": _safe_str(override_value, ""),
            "resolved": resolved,
            "valid": True,
            "folder": resolved
        }

    if _file_exists(resolved):
        return {
            "provided": True,
            "input": _safe_str(override_value, ""),
            "resolved": resolved,
            "valid": True,
            "folder": os.path.dirname(resolved)
        }

    parent = os.path.dirname(resolved)
    if parent and _folder_exists(parent):
        return {
            "provided": True,
            "input": _safe_str(override_value, ""),
            "resolved": resolved,
            "valid": True,
            "folder": parent
        }

    return {
        "provided": True,
        "input": _safe_str(override_value, ""),
        "resolved": resolved,
        "valid": False,
        "folder": ""
    }


# ------------------------------------------------------------
# REGISTRY HELPERS
# ------------------------------------------------------------

def _open_subkey(root_key, subkey_path):
    """
    Open a registry subkey and return None if it does not exist.
    """
    try:
        return root_key.OpenSubKey(subkey_path)
    except:
        return None


def _read_default_value(reg_key):
    """
    Read the default unnamed value from a registry key.
    """
    try:
        return _safe_str(reg_key.GetValue(None), "")
    except:
        return ""


def _find_desktop_connector_clsid():
    """
    Search HKCR\CLSID for the shell namespace entry whose default value is Autodesk Docs.
    """
    clsid_root = _open_subkey(Registry.ClassesRoot, r"CLSID")
    if clsid_root is None:
        return ""

    try:
        for subkey_name in clsid_root.GetSubKeyNames():
            child_path = r"CLSID\{0}".format(subkey_name)
            child_key = _open_subkey(Registry.ClassesRoot, child_path)
            if child_key is None:
                continue

            display_name = _read_default_value(child_key).strip()
            if display_name.lower() == "autodesk docs":
                return subkey_name
    except:
        return ""

    return ""


def _get_dc_root_from_clsid(clsid_value):
    """
    Read the Desktop Connector local root from the CLSID InitPropertyBag TargetFolderPath.
    """
    if not clsid_value:
        return ""

    subkey_path = r"CLSID\{0}\Instance\InitPropertyBag".format(clsid_value)
    reg_key = _open_subkey(Registry.ClassesRoot, subkey_path)
    if reg_key is None:
        return ""

    try:
        target_folder_path = _safe_str(reg_key.GetValue("TargetFolderPath"), "").strip()
        if target_folder_path and _folder_exists(target_folder_path):
            return os.path.normpath(target_folder_path)
    except:
        return ""

    return ""


# ------------------------------------------------------------
# DOCUMENT HELPERS
# ------------------------------------------------------------

def _get_current_document_name_candidates(document):
    """
    Build likely file names for the current document based on its title.
    """
    title = _safe_str(document.Title, "").strip()
    base_name = _sanitize_filename(_strip_revit_extension(title), "Model")

    lower_title = title.lower()
    exts = []

    if lower_title.endswith(".rvt"):
        exts = [".rvt"]
    elif lower_title.endswith(".rfa"):
        exts = [".rfa"]
    elif lower_title.endswith(".rte"):
        exts = [".rte"]
    elif lower_title.endswith(".rft"):
        exts = [".rft"]
    else:
        exts = [".rvt", ".rfa", ".rte", ".rft"]

    return {
        "base_name": base_name,
        "file_names": [base_name + ext for ext in exts]
    }


def _is_workshared(document):
    """
    Return whether the current document is workshared.
    """
    try:
        return bool(document.IsWorkshared)
    except:
        return False


def _get_acc_bim360_reference_path(document):
    """
    Return the best available user-visible Revit path for ACC / BIM 360 / local reference.
    """
    try:
        if document.IsWorkshared:
            model_path = document.GetWorksharingCentralModelPath()
            if model_path is not None:
                visible = _safe_str(ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path), "")
                if visible:
                    return visible
    except:
        pass

    try:
        if document.IsModelInCloud:
            model_path = document.GetCloudModelPath()
            if model_path is not None:
                visible = _safe_str(ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path), "")
                if visible:
                    return visible
    except:
        pass

    try:
        return _safe_str(document.PathName, "")
    except:
        return ""


# ------------------------------------------------------------
# MODEL SEARCH HELPERS
# ------------------------------------------------------------

def _search_for_model_under_root(root_folder, target_file_names, max_hits=10, max_dirs=15000):
    """
    Search recursively for the actual model file under the Desktop Connector root.
    """
    if not _folder_exists(root_folder):
        return []

    target_names = set([name.lower() for name in target_file_names])
    hits = []
    visited = 0

    try:
        for current_root, dirnames, filenames in os.walk(root_folder):
            visited += 1
            if visited > max_dirs:
                break

            for file_name in filenames:
                if file_name.lower() in target_names:
                    full_path = os.path.join(current_root, file_name)
                    if _file_exists(full_path):
                        hits.append(os.path.normpath(full_path))
                        if len(hits) >= max_hits:
                            return hits
    except:
        return hits

    return hits


# ------------------------------------------------------------
# DETAILS / EXPORT HELPERS
# ------------------------------------------------------------

def _to_export_lines(result_dict):
    """
    Convert the result dictionary into a stable plain-text export block.
    """
    ordered_keys = [
        "Source",
        "IsWorkshared",
        "DesktopFolder",
        "TargetFolder",
        "BaseName",
        "Extension",
        "FileName",
        "FullPath",
        "AccBim360Path",
        "DcClsid",
        "DcRoot",
        "MatchedModelPath",
        "OverrideInput",
        "OverrideResolved",
        "FailReason",
    ]

    lines = []
    lines.append("EXPORT_PATH_RESOLUTION")
    lines.append("----------------------------------------")

    for key in ordered_keys:
        value = _safe_str(result_dict.get(key, ""), "")
        lines.append("{0}: {1}".format(key, value))

    return lines


def _to_export_text(result_dict):
    """
    Convert the result dictionary into a single copy/paste text block.
    """
    return "\n".join(_to_export_lines(result_dict))


# ------------------------------------------------------------
# FAILOVER BUILDER
# ------------------------------------------------------------

def _build_desktop_failover(document, extension_value, fail_reason, override_input="", override_resolved=""):
    """
    Build the Desktop fallback result when any earlier step fails.
    """
    desktop = _get_desktop_folder()
    doc_info = _get_current_document_name_candidates(document)
    base_name = doc_info["base_name"]
    extension_value = _normalize_extension(extension_value, ".txt")
    file_name = base_name + extension_value
    full_path = os.path.join(desktop, file_name)
    acc_bim360_path = _get_acc_bim360_reference_path(document)

    return {
        "Source": "DesktopFallback",
        "IsWorkshared": _is_workshared(document),
        "DesktopFolder": desktop,
        "TargetFolder": desktop,
        "BaseName": base_name,
        "Extension": extension_value,
        "FileName": file_name,
        "FullPath": full_path,
        "AccBim360Path": acc_bim360_path,
        "DcClsid": "",
        "DcRoot": "",
        "MatchedModelPath": "",
        "OverrideInput": override_input,
        "OverrideResolved": override_resolved,
        "FailReason": fail_reason
    }


# ------------------------------------------------------------
# MAIN RESOLUTION
# ------------------------------------------------------------

def resolve_export_path(document, requested_extension, override_path):
    """
    Resolve the final export path using the requested stop-on-failure logic.
    """
    extension_value = _normalize_extension(requested_extension, ".txt")
    acc_bim360_path = _get_acc_bim360_reference_path(document)

    override_info = _resolve_override_folder(override_path)

    if override_info["provided"] and override_info["valid"]:
        doc_info = _get_current_document_name_candidates(document)
        base_name = doc_info["base_name"]
        file_name = base_name + extension_value
        full_path = os.path.join(override_info["folder"], file_name)

        return {
            "Source": "Override",
            "IsWorkshared": _is_workshared(document),
            "DesktopFolder": _get_desktop_folder(),
            "TargetFolder": override_info["folder"],
            "BaseName": base_name,
            "Extension": extension_value,
            "FileName": file_name,
            "FullPath": full_path,
            "AccBim360Path": acc_bim360_path,
            "DcClsid": "",
            "DcRoot": "",
            "MatchedModelPath": "",
            "OverrideInput": override_info["input"],
            "OverrideResolved": override_info["resolved"],
            "FailReason": ""
        }

    if override_info["provided"] and not override_info["valid"]:
        return _build_desktop_failover(
            document,
            extension_value,
            "Override path was supplied but could not be resolved to a valid existing folder.",
            override_info["input"],
            override_info["resolved"]
        )

    dc_clsid = _find_desktop_connector_clsid()
    if not dc_clsid:
        return _build_desktop_failover(
            document,
            extension_value,
            "Desktop Connector CLSID was not found under HKCR\\CLSID.",
            override_info["input"],
            override_info["resolved"]
        )

    dc_root = _get_dc_root_from_clsid(dc_clsid)
    if not dc_root:
        return _build_desktop_failover(
            document,
            extension_value,
            "Desktop Connector TargetFolderPath could not be read from the CLSID registry key.",
            override_info["input"],
            override_info["resolved"]
        )

    workshared = _is_workshared(document)
    if not workshared:
        return _build_desktop_failover(
            document,
            extension_value,
            "Current document is not workshared.",
            override_info["input"],
            override_info["resolved"]
        )

    doc_info = _get_current_document_name_candidates(document)
    matches = _search_for_model_under_root(dc_root, doc_info["file_names"])

    if not matches:
        return _build_desktop_failover(
            document,
            extension_value,
            "No matching model file was found under the Desktop Connector local root.",
            override_info["input"],
            override_info["resolved"]
        )

    matched_model_path = matches[0]
    target_folder = os.path.dirname(matched_model_path)
    base_name = _sanitize_filename(
        _strip_revit_extension(os.path.basename(matched_model_path)),
        doc_info["base_name"]
    )
    file_name = base_name + extension_value
    full_path = os.path.join(target_folder, file_name)

    return {
        "Source": "DesktopConnector",
        "IsWorkshared": workshared,
        "DesktopFolder": _get_desktop_folder(),
        "TargetFolder": target_folder,
        "BaseName": base_name,
        "Extension": extension_value,
        "FileName": file_name,
        "FullPath": full_path,
        "AccBim360Path": acc_bim360_path,
        "DcClsid": dc_clsid,
        "DcRoot": dc_root,
        "MatchedModelPath": matched_model_path,
        "OverrideInput": override_info["input"],
        "OverrideResolved": override_info["resolved"],
        "FailReason": ""
    }


# ------------------------------------------------------------
# EXECUTION
# ------------------------------------------------------------

requested_extension = IN[0] if len(IN) > 0 else None
override_path = IN[1] if len(IN) > 1 else None

result = resolve_export_path(doc, requested_extension, override_path)
details_text = _to_export_text(result)

# ------------------------------------------------------------
# OUTPUT
# ------------------------------------------------------------

# OUT[0] = final target file path
# OUT[1] = one-item list containing the multiline details text
OUT = [result["FullPath"], [details_text]]
