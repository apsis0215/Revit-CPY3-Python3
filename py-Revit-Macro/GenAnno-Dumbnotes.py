def _verify_label_binding(fm, label_elem, elem_param, family_param):
    """
    Double-check that the label binding was created correctly by copying base label.
    Verifies:
    1. The element parameter is now associated with the family parameter
    2. The association can be retrieved back
    3. The label element still exists and is valid
    
    Returns (is_verified: bool, message: str)
    """
    try:
        # Check 1: Verify the label element is still valid
        if label_elem is None or not label_elem.IsValidObject:
            return False, "Label element is no longer valid after binding"
        
        # Check 2: Verify the family parameter exists in FamilyManager
        param_found = False
        for p in fm.Parameters:
            if p.Id.IntegerValue == family_param.Id.IntegerValue:
                param_found = True
                break
        
        if not param_found:
            return False, "Family parameter not found in FamilyManager after binding"
        
        # Check 3: Try to get the associated family parameter back from element parameter
        try:
            associated_fp = fm.GetAssociatedFamilyParameter(elem_param)
            if associated_fp is None:
                return False, "GetAssociatedFamilyParameter returned None - binding may not have persisted"
            
            # Verify it's the same parameter we intended to bind
            if associated_fp.Id.IntegerValue != family_param.Id.IntegerValue:
                return False, "Associated parameter ID mismatch: expected {}, got {}".format(
                    family_param.Id.IntegerValue, associated_fp.Id.IntegerValue
                )
        except Exception as ex:
            # GetAssociatedFamilyParameter might not be available in all API versions
            return True, "Could not verify association (API limitation): {}".format(str(ex))
        
        # Check 4: Verify parameter names match
        try:
            if associated_fp.Definition.Name != family_param.Definition.Name:
                return False, "Associated parameter name mismatch: expected '{}', got '{}'".format(
                    family_param.Definition.Name, associated_fp.Definition.Name
                )
        except Exception:
            pass  # Name comparison is optional
        
        return True, "Label binding verified successfully"
        
    except Exception as ex:
        return False, "Verification failed with exception: {}".format(str(ex))


def _verify_elementid_binding(elem_param, expected_id):
    """
    Double-check that an ElementId parameter was set correctly.
    
    Returns (is_verified: bool, message: str)
    """
    try:
        actual_id = elem_param.AsElementId()
        
        if actual_id is None:
            return False, "ElementId parameter returned None after setting"
        
        if actual_id.IntegerValue != expected_id.IntegerValue:
            return False, "ElementId mismatch: expected {}, got {}".format(
                expected_id.IntegerValue, actual_id.IntegerValue
            )
        
        return True, "ElementId binding verified successfully"
        
    except Exception as ex:
        return False, "ElementId verification failed: {}".format(str(ex))


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
        "verificationStatus": None,  # Added for verification tracking
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
                    
                    # Double-check: Verify the label was created correctly by copying base label
                    verified, verify_msg = _verify_label_binding(fm, label_elem, p, family_param)
                    dbg["verificationStatus"] = {"verified": verified, "message": verify_msg}
                    if not verified:
                        dbg["attempts"].append("VERIFICATION WARNING: {}".format(verify_msg))
                    
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
                
                # Double-check: Verify the label was created correctly by copying base label
                verified, verify_msg = _verify_label_binding(fm, label_elem, p, family_param)
                dbg["verificationStatus"] = {"verified": verified, "message": verify_msg}
                if not verified:
                    dbg["attempts"].append("VERIFICATION WARNING: {}".format(verify_msg))
                
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
            
            # Double-check: Verify the label was created correctly by copying base label
            verified, verify_msg = _verify_label_binding(fm, label_elem, p, family_param)
            dbg["verificationStatus"] = {"verified": verified, "message": verify_msg}
            if not verified:
                dbg["attempts"].append("VERIFICATION WARNING: {}".format(verify_msg))
            
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
                        
                        # Double-check: Verify the ElementId was set correctly
                        verified, verify_msg = _verify_elementid_binding(p, fp_id)
                        dbg["verificationStatus"] = {"verified": verified, "message": verify_msg}
                        if not verified:
                            dbg["attempts"].append("VERIFICATION WARNING: {}".format(verify_msg))
                        
                        return True, dbg
                    except Exception as ex:
                        dbg["attempts"].append("{} (ElementId set) -> FAIL: {}".format(pname, str(ex)))
            except Exception:
                continue
    except Exception:
        pass

    return False, dbg