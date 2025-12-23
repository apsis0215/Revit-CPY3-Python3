import clr                                                  ##Import .net https://forum.dynamobim.com/t/import-os-sys-system/34604/2
import System                                               ##Underlying base  system functions (Windows?)
clr.AddReference("RevitAPI")

import Autodesk                                             ##REquired for doc.Delete() Method
import Autodesk.Revit.DB as ARDB

from RevitServices.Persistence import DocumentManager
#from RevitServices.Transactions import TransactionManager


from Autodesk.Revit.DB import Transaction                   ##For outside and inner transactions
from Autodesk.Revit.DB import Element                       ##Element reference
from Autodesk.Revit.DB import FilteredElementCollector      ##FEC add
from Autodesk.Revit.DB import FamilySymbol, FamilyInstance, AnnotationSymbol
from Autodesk.Revit.DB import BuiltInCategory               ##Generic annos
from Autodesk.Revit.DB import BuiltInParameter              #For fonversin fo family type to ID and b

from itertools import groupby

doc = DocumentManager.Instance.CurrentDBDocument

clr.AddReference("System.Core")
from System.Linq import Enumerable


import System                                   ##filterAnnot = System.Predicate  <<Work on removing         
from System.Collections.Generic import List     ##Not same as type() = List       <<Work on removing 


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
def GetNameByID(oID):                                   ##Get Broken Element.Name as work around GLOBAL ByID.Name
    return doc.GetElement(oID).get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
    
def get_draft_views():
    ##Filter instances matching ViewType.Legend
    Filter_View = System.Func[ARDB.Element, System.Boolean](lambda v : v.ViewType == ARDB.ViewType.DraftingView)
    ##Element instances where view legends have viewports (I.e. on sheets only)
    views = Enumerable.Where[ARDB.Element](ARDB.FilteredElementCollector(doc).OfCategory(ARDB.BuiltInCategory.OST_Views), Filter_View)
    return views

def view_dependants_on_sheets(view):                        ##Check if unused (primary) view has dependants onhseet
    for id in view.GetDependentViewIds():                   ##If it has dependants
        if view_is_used(doc.GetEloement(id)):               ##Check each if it is on sheet - could get some optimization by removing associated views in LIST()
            return True
    return False

def view_draft_preserve_names(view):                       ##List of possible view names based e.g. gen.anno.schedules
    found = False                                          ##Set found to false    
    SaveName=[]                                            ##SavedNAmes based on criteria added belpow - genanno title names
    ##Return Names of (genAnno) families in project
    SaveName = [x.Family.Name for x in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_GenericAnnotation).WhereElementIsElementType()] ##Gets instances placed

    SaveName = sorted(set(SaveName))                        ##De-Duplicate
    
    for sn in SaveName:
        if view.Name == sn:
            found = True
            break        

    return found                                            ## IF found return true

def Main():
    DeletedViews=[]                                         ##Actual deleted views
    ############################################################
    ViewsToDelete = get_draft_views()                       ##Get all views
    
    ViewsToDelete = [ v for v in ViewsToDelete if view_is_used(v)== False ]     ##Compare to viewports  - remove all on sheets(Having viewports)
    
    ##Appears to be unnecessary - if a dependant is on a shet the primary view also registers in teh viewport ; )
    ViewsToDelete = [ v for v in ViewsToDelete if view_dependants_on_sheets(v)== False ] ##Compare if doesn't ahve dependants on sheets remain in set
    
    ViewsToDelete = [ v for v in ViewsToDelete if view_draft_preserve_names(v)== False ] ##Compare remove if matched generic anno drafting views

    return view_delete(ViewsToDelete)                       ##Return views to delete success or not

################################################################
OUT= Main()                                                 ##Call MAIN <<<<<<<<<ENTRY POINT
