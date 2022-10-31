##Adapted from
##https://forum.dynamobim.com/t/how-to-set-the-starting-view-in-current-project-file-with-python/76971/5
# Boilerplate text
import clr

clr.AddReference("RevitServices")
import RevitServices
from RevitServices.Persistence import DocumentManager 
from RevitServices.Transactions import TransactionManager 

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *

def SetStartView(view):                                 ##CAnnot delete starting view- set as current 

    targetView = UnwrapElement(view)                    ##Unwrap if Dynamp Script component to get to revit component
    targetId = targetView.Id                            ##Set ID to use
    # Do some action in a Transaction
    trans=Transaction(doc, 'trans:Dyn.Start.View.Set')  ##Transaction group start name
    trans.Start()                                       ##Start outside transaction
    
    if svs.IsAcceptableStartingView(targetId):          ##If acceptable starting view do next indent
    	try:                                              ##"Try" error trap... if it breaks catch...
    		svs.ViewId = targetView.Id                      ##Set update for startup view
    		return "Start view updated."                    ##Report 
    	except:                                           ##Try failed...
        return "Start view unable to be updated."       ##Return an erro message
    
    else:                                               ##System from IF... not acceptable start view
    	return "View is not an accceptable start view."   ##Return error message
    
    TransactionManager.Instance.TransactionTaskDone()
  
