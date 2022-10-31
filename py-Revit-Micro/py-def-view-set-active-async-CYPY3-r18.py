##http://thebuildingcoder.typepad.com/blog/2017/02/setting-active-view-during-idling.html
##https://github.com/DynamoDS/Dynamo/issues/5651  
import clr
clr.AddReference("RevitServices")
import RevitServices
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
app = DocumentManager.Instance.CurrentUIApplication.Application
uiapp = DocumentManager.Instance.CurrentUIApplication

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *
############################################################
def view_set_active(view):                                  ##def to select a view in the project and make it active (Open/View/Set the view)
    TransactionManager.Instance.ForceCloseTransaction()     ##Must be OUTSIDE a transaction- Including DYNAMO which is a transaction
    try:                                                    ##Try/Catch for errors
        uiapp.ActiveUIDocument.RequestViewChange(view)      ## request view change as an async process
        retutrn view                                        ##return view if successful
    except:
        return "Error, couldn't set active view"            ##Return error on set active view
