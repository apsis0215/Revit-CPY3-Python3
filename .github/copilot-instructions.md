# Copilot Instructions for Dynamo Python Nodes (Revit 2025+ CPython3)

This repository contains Python scripts for Dynamo for Revit using the CPython3 (PythonNet) engine in Revit 2025+ (Dynamo 3.3+).

## Core Requirements

### Script Structure
- **Input/Output Pattern**: Use `IN[]` for inputs and return results via `OUT`
- **Documentation**: Include PURPOSE and IO comments at the top of each script
  ```python
  # PURPOSE: [Brief description of what this node does]
  # INPUTS:
  #   IN[0]: [Description and expected type]
  #   IN[1]: [Description and expected type]
  # OUTPUTS:
  #   OUT: [Description of output format, typically dict + warnings list]
  ```

### Standard Imports and References
Always use this pattern for Revit API access:
```python
import clr
clr.AddReference("RevitAPI")
import Autodesk.Revit.DB as ARDB

from RevitServices.Persistence import DocumentManager
```

### Document Access
Use RevitServices DocumentManager to access Revit application and document:
```python
doc = DocumentManager.Instance.CurrentDBDocument
uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application
```

### Input Validation
**Always validate inputs before starting any transaction:**
- Check for None values
- Verify expected types
- Validate list lengths and content
- Provide clear error messages
```python
# Example validation
if IN[0] is None:
    OUT = {"error": "Element input is required", "warnings": ["No elements provided"]}
else:
    # Proceed with logic
```

### Transaction Management
**Keep all Revit modifications inside a single Transaction:**
```python
from Autodesk.Revit.DB import Transaction

# Validate inputs first
if valid_input:
    trans = Transaction(doc, 'Transaction Name')
    trans.Start()
    try:
        # All Revit modifications here
        result = modify_elements()
        trans.Commit()
    except Exception as e:
        trans.RollBack()
        warnings.append(f"Transaction failed: {str(e)}")
```

**Key transaction rules:**
- Use descriptive transaction names
- Start transaction only after input validation
- Keep transaction scope minimal
- Always handle exceptions with RollBack
- Never nest transactions unnecessarily
- Avoid per-element transactions (batch operations instead)

### Enum Handling
CPython3 may receive enums as integers. Always cast explicitly:
```python
# Example: ViewType enum
from Autodesk.Revit.DB import ViewType

# Safe casting when input might be an int
if isinstance(IN[0], int):
    view_type = ViewType(IN[0])
else:
    view_type = IN[0]

# Or use a try-except for robust handling
try:
    view_type = ViewType(IN[0]) if isinstance(IN[0], int) else IN[0]
except:
    warnings.append(f"Invalid ViewType value: {IN[0]}")
    view_type = ViewType.FloorPlan  # Default fallback
```

### Output Format
**Return stable, machine-readable outputs:**
```python
# Preferred output structure
OUT = {
    "success": True,
    "count": len(processed_elements),
    "elements": processed_elements,
    "warnings": warnings_list
}

# Alternative with separate warnings
OUT = [result_dict, warnings_list]
```

**Output guidelines:**
- Use dictionaries for structured data
- Include success/failure status
- Provide counts and summaries
- Separate warnings list for non-critical issues
- Avoid relying on print() output
- No UI prompts or dialogs in production code
- Make outputs consumable by downstream nodes

### CPython3 Compatibility
**Avoid IronPython-only patterns:**
- Don't use .NET collection types directly (prefer Python lists/dicts)
- Be cautious with System.Collections.Generic types
- Use Python's native iteration instead of .NET enumerators when possible
- Import from System.Linq only when necessary (e.g., Enumerable.Where)

**Acceptable patterns:**
```python
# Good: Python list comprehension
elements = [doc.GetElement(id) for id in element_ids]

# Acceptable: System.Linq when needed for complex LINQ operations
from System.Linq import Enumerable
filtered = Enumerable.Where[ARDB.Element](collector, predicate_func)
```

### Performance Best Practices
- Use FilteredElementCollector with category and class filters
- Batch changes instead of per-element transactions
- Cache document queries when reusing results
- Avoid unnecessary element.Document access in loops

### Safety Checks
- Never modify elements in linked documents
- Check worksharing status before writes in collaborative projects
- Verify element ownership when applicable
- Handle invalid ElementIds gracefully

## Code Style
- Use clear, descriptive variable names
- Add comments for complex logic, loops, and conditionals
- Keep comments concise with `#` prefix
- Avoid decorative comment characters
- Use 4-space indentation
- Group related imports together

## Example Template
```python
# PURPOSE: Example node that processes Revit elements
# INPUTS:
#   IN[0]: List of Revit elements or ElementIds
#   IN[1]: Optional parameter (default: None)
# OUTPUTS:
#   OUT: Dictionary with results and warnings list

import clr
clr.AddReference("RevitAPI")
import Autodesk.Revit.DB as ARDB

from RevitServices.Persistence import DocumentManager
from Autodesk.Revit.DB import Transaction

doc = DocumentManager.Instance.CurrentDBDocument

# Initialize outputs
warnings = []
results = []

# Input validation
input_elements = IN[0] if IN[0] else []
if not input_elements:
    OUT = {"error": "No elements provided", "warnings": ["Input is empty"]}
else:
    # Convert to list if needed
    elements = input_elements if isinstance(input_elements, list) else [input_elements]
    
    # Process elements (read-only operations)
    for elem in elements:
        try:
            # Get element if ID provided
            if isinstance(elem, ARDB.ElementId):
                elem = doc.GetElement(elem)
            
            # Read operations here
            results.append(elem.Name)
        except Exception as e:
            warnings.append(f"Failed to process element: {str(e)}")
    
    # Modifications (if needed)
    if results:
        trans = Transaction(doc, 'Modify Elements')
        trans.Start()
        try:
            # All write operations here
            trans.Commit()
        except Exception as e:
            trans.RollBack()
            warnings.append(f"Transaction failed: {str(e)}")
    
    # Output
    OUT = {
        "success": True,
        "count": len(results),
        "results": results,
        "warnings": warnings
    }
```

## File Naming Convention
Follow the repository naming schema:
- Prefix with `py` for Python files
- Use descriptive names (general to specific)
- Include `CPY3` to indicate CPython3
- Include Revit version if relevant (e.g., `r22` for Revit 2022)
- Example: `py-View-Delete-Unused-CPY3-r22.py`

## Categories
- **py-Revit-Macro/**: Full standalone scripts that complete single or multiple tasks within a self-contained Python script. Use for complete workflows that can run independently.
- **py-Revit-Micro/**: Single-use functions (`def()`) and micro snippets focused on specific tasks with detailed comments for easy adaptation. Use for reusable helper functions and small utilities that can be integrated into larger scripts.
