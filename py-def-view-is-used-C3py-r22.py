import Autodesk                                             ##REquired for doc.Delete() Method
import Autodesk.Revit.DB as ARDB
def view_is_used(v : ARDB.View): ##-> bool:                 ##-> is a 'Meta data attachment' for hinting of return values
    typeViewPort = clr.GetClrType(ARDB.Viewport)            ##Viewports types (On sheets?)
    filterClass = ARDB.ElementClassFilter(typeViewPort)     ##All instance elements matching viewports type
    SheetId = [doc.GetElement(vId).SheetId for vId in v.GetDependentElements(filterClass) if doc.GetElement(vId).SheetId != ARDB.ElementId.InvalidElementId]
    
    return len(SheetId)>0                                   ##If the list has elements then then the legends are in viewports on sheets
