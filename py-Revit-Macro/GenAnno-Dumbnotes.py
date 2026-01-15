def _bind_label_to_family_param(fm, label_elem, family_param):
    """
    Binds a label element's text parameter to a family parameter.
    Since we can't create labels via API, we must work with whatever
    parameter the existing label uses (e.g., "ID", "Label", "Text", etc.)
    
    Priority order:
    1. Try common label parameter names: "ID", "Label", "Text", "Value"
    2. Try any String parameter with text-related keywords
    3. Try ANY writable String parameter
    4. Try ElementId parameters for label parameter references
    
    Returns (ok, debug_dict)
    """
    dbg = {
        "elemId": label_elem.Id.IntegerValue,
        "elemType": _rt(label_elem),
        "attempts": [],
        "allParams": [],
    }

    # Collect all parameter info for debugging
    string_params = []
    try:
        for p in label_elem.Parameters:
            try:
                pname = (p.Definition.Name or "").strip()
                pinfo = {
                    "name": pname,
                    "storageType": int(p.StorageType),
                    "isReadOnly": bool(getattr(p, "IsReadOnly", False)),
                }
                dbg["allParams"].append(pinfo)
                
                # Collect String parameters (don't filter by read-only yet)
                if p.StorageType == StorageType.String:
                    string_params.append((pname, p))
            except Exception:
                pass
    except Exception:
        pass

    # Define common label parameter names in priority order
    # "ID" and "Label" are most common for label elements
    common_label_params = ["ID", "Label", "Text", "Value", "Sample Text", "Content"]
    
    # Strategy 1: Try common label parameter names first
    for target_name in common_label_params:
        for pname, p in string_params:
            if pname.lower() == target_name.lower():
                try:
                    fm.AssociateElementParameterToFamilyParameter(p, family_param)
                    dbg["attempts"].append("{} (exact match '{}') -> SUCCESS".format(pname, target_name))
                    return True, dbg
                except Exception as ex:
                    dbg["attempts"].append("{} (exact match '{}') -> FAIL: {}".format(pname, target_name, str(ex)))
    
    # Strategy 2: Try any String parameter with text-related keywords
    text_keywords = ["label", "id", "text", "value", "content", "sample"]
    for pname, p in string_params:
        pname_lower = pname.lower()
        if any(keyword in pname_lower for keyword in text_keywords):
            # Skip if we already tried it in strategy 1
            if any(pname.lower() == c.lower() for c in common_label_params):
                continue
            try:
                fm.AssociateElementParameterToFamilyParameter(p, family_param)
                dbg["attempts"].append("{} (keyword match) -> SUCCESS".format(pname))
                return True, dbg
            except Exception as ex:
                dbg["attempts"].append("{} (keyword match) -> FAIL: {}".format(pname, str(ex)))
    
    # Strategy 3: Try ANY String parameter
    for pname, p in string_params:
        # Skip if already tried
        pname_lower = pname.lower()
        already_tried = (
            any(pname.lower() == c.lower() for c in common_label_params) or
            any(keyword in pname_lower for keyword in text_keywords)
        )
        if already_tried:
            continue
        try:
            fm.AssociateElementParameterToFamilyParameter(p, family_param)
            dbg["attempts"].append("{} (any string) -> SUCCESS".format(pname))
            return True, dbg
        except Exception as ex:
            dbg["attempts"].append("{} (any string) -> FAIL: {}".format(pname, str(ex)))
    
    # Strategy 4: Try ElementId parameters (label parameter reference)
    try:
        fp_id = family_param.Id
        for p in label_elem.Parameters:
            try:
                if p.StorageType != StorageType.ElementId:
                    continue
                pname = (p.Definition.Name or "").strip()
                pname_lower = pname.lower()
                
                # Look for parameters that reference label parameters
                if any(kw in pname_lower for kw in ["label", "param", "parameter"]):
                    try:
                        p.Set(fp_id)
                        dbg["attempts"].append("{} (ElementId set) -> SUCCESS".format(pname))
                        return True, dbg
                    except Exception as ex:
                        dbg["attempts"].append("{} (ElementId set) -> FAIL: {}".format(pname, str(ex)))
            except Exception:
                continue
    except Exception:
        pass

    return False, dbg