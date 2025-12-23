import clr                                                  ##Import .net https://forum.dynamobim.com/t/import-os-sys-system/34604/2
import re                                                   ##Import Regex
import System                                               ##Underlying base  system functions (Windows?)
clr.AddReference("RevitAPI")

import Autodesk                                             ##REquired for doc.Delete() Method
import Autodesk.Revit.DB as ARDB

from RevitServices.Persistence import DocumentManager       ##For DOC access

from Autodesk.Revit.DB import Transaction,TransactionGroup  ##For outside and inner transactions

doc = DocumentManager.Instance.CurrentDBDocument

clr.AddReference("System.Core")
from System.Linq import Enumerable

##############################################################
def get_viewtemplates_unused():
    ## Assums all views are in use. Purge views first for more comprehensive cleaning!
    views=[]
    views = ARDB.FilteredElementCollector(doc).OfClass(ARDB.View) ##Get all views in th eproject
    appliedtemplates = [v.ViewTemplateId for v in views]        ##Get all applied view tempaltes
    templates = [v.Id for v in views if v.IsTemplate == True]   ##Gather ALL views that are Templates

    UnusedViewTemplateElements = []                         ##Initialize
    for tid in templates:                                   ##For each of ALL the tempaltes
    	if tid not in appliedtemplates:                     ##If the ID isn't in Applied templates
    		UnusedViewTemplateElements.append(doc.GetElement(tid))  ##Add the element to the group
    return UnusedViewTemplateElements

##############################################################
def view_delete(Views):                                     ##Return deleted views  
    if len(Views)>0:                                        ##Not on sheets is not null - so candidates to delete
        ######################################################In Traqnsaction
        V_Deleted=["Deleted Views:"]                        ##PRefix list with "Deleted"
        for view in Views:                                  ##For each element not on sheets
            transGrp=Transaction(doc, view.Name)            ##GROUP Transaction(s)
            transGrp.Start()                                ##Start Group transaction
            ##################################################
            try:
                V_name=view.Name                            ##Append its name tothe deleted list    
                doc.Delete(view.Id)                         ##<<<DELETE  ##Delete the element VIA the doc handler and its Id
            except:
                V_name="Error deleting: "
                try:
                    V_name = V_name + view.Name               ##Append its name tothe deleted list    
                except:
                    V_name = V_name + "Cannot extract Name"     ##If not view or cannot get name report that
            finally:
                V_Deleted.append(V_name) ##Append its name tothe deleted list    
            ##################################################
            transGrp.Commit()                               ##Commit group transaction for current view : 
    else:                                                    
        V_Deleted=["No views to delete."]                     ##Report nothign to delete
    return V_Deleted                                        ##Return deleted view names or nothing to delete
##############################################################
##############################################################
##############################################################
##def Main():
trans=TransactionGroup(doc, 'Dynamo:DeleteViewTemplatesUnused') ##Transaction group start name
trans.Start()   
##############################################################
Templates_Unused = get_viewtemplates_unused()               ##Get Unused view templates
Message= [tu.Name for tu in Templates_Unused]
Message = view_delete(Templates_Unused)                     ##Return the application of deleted views
trans.Commit()                                              ##Commit the transaction

##############################################################


OUT=Message #Main()
