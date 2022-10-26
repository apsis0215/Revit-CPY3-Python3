import clr                                                  ##Import .net https://forum.dynamobim.com/t/import-os-sys-system/34604/2
import System                                               ##Underlying base  system functions (Windows?)
clr.AddReference("RevitAPI")

import Autodesk                                             ##REquired for doc.Delete() Method
import Autodesk.Revit.DB as ARDB

from RevitServices.Persistence import DocumentManager
#from RevitServices.Transactions import TransactionManager
doc = DocumentManager.Instance.CurrentDBDocument

def view_delete(views):
    if views:
        trans=Transaction(doc, 'trans:DeletedViews')  ##Transaction group start name
        trans.Start()                                       ##Start outside transaction
    
        deleted=["Deleted Views:"]                        ##PRefix list with "Deleted"
        for i in views:                               ##For each element not on sheets
            deleted.append(i.Name)                          ##Append its name tothe deleted list    
            doc.Delete(i.Id)           ##<<<DELETE          ##Delete the element VIA the doc handler and its Id
            
        trans.Commit()                                      ##Commit the transaction
    else:
        deleted=["No views to delete."]                     ##Report nothign to delete
    
    return deleted                                          ##Return deleted view names or nothing to delete
  ############################################################
