import clr                                                  ##Import .net https://forum.dynamobim.com/t/import-os-sys-system/34604/2
import System                                               ##Underlying base  system functions (Windows?)
clr.AddReference("RevitAPI")

import Autodesk                                             ##REquired for doc.Delete() Method
import Autodesk.Revit.DB as ARDB

from RevitServices.Persistence import DocumentManager
#from RevitServices.Transactions import TransactionManager

from Autodesk.Revit.DB import Transaction                   ##For outside and inner transactions

doc = DocumentManager.Instance.CurrentDBDocument

clr.AddReference("System.Core")
from System.Linq import Enumerable

def view_is_used(v : ARDB.View): ##-> bool:                 ##-> is a 'Meta data attachment' for hinting of return values
    typeViewPort = clr.GetClrType(ARDB.Viewport)            ##Viewports types (On sheets?)
    filterClass = ARDB.ElementClassFilter(typeViewPort)     ##All instance elements matching viewports type
    SheetId = [doc.GetElement(vId).SheetId for vId in v.GetDependentElements(filterClass) if doc.GetElement(vId).SheetId != ARDB.ElementId.InvalidElementId]
    
    return len(SheetId)>0                                   ##If the list has elements then then the legends are in viewports on sheets


def view_delete(NotOnSheets):
    if NotOnSheets:
        trans=Transaction(doc, 'trans:DeleteViews')  ##Transaction group start name
        trans.Start()                                       ##Start outside transaction
    
        deleted=["Deleted Views:"]                        ##PRefix list with "Deleted"
        for i in NotOnSheets:                               ##For each element not on sheets
            deleted.append(i.Name)                          ##Append its name tothe deleted list    
            doc.Delete(i.Id)           ##<<<DELETE          ##Delete the element VIA the doc handler and its Id
            
        trans.Commit()                                      ##Commit the transaction
    else:
        deleted=["No views to delete."]                     ##Report nothign to delete
    
    return deleted                                          ##Return deleted view names or nothing to delete
    
############################################################
    
def get_plan_views():
    ##Filter instances matching ViewType.Legend
    Filter_View = System.Func[ARDB.Element, System.Boolean](lambda v : v.ViewType == ARDB.ViewType.FloorPlan)
    ##Element instances where view legends have viewports (I.e. on sheets only)
    views = Enumerable.Where[ARDB.Element](ARDB.FilteredElementCollector(doc).OfCategory(ARDB.BuiltInCategory.OST_Views), Filter_View)
    return views

def view_dependants_on_sheets(view):                        ##Check if unused (primary) view has dependants onhseet
    for id in view.GetDependentViewIds():                   ##If it has dependants
        if view_is_used(doc.GetEloement(id)):               ##Check each if it is on sheet - could get some optimization by removing associated views in LIST()
            return True
    return False
    
############################################################
ViewsToDelete = get_plan_views()                            ##Get all views

ViewsToDelete = [ v for v in ViewsToDelete if view_is_used(v)== False ]     ##Compare to viewports  - remove all on sheets(Having viewports)

##Appears to be unnecessary - if a dependant is on a shet the primary view also registers in teh viewport ; )
ViewsToDelete = [ v for v in ViewsToDelete if view_dependants_on_sheets(v)== False ] ##Compare if doesn't ahve dependants on sheets remain in set

OUT=view_delete(ViewsToDelete)
