##https://forum.dynamobim.com/t/how-to-retain-information-within-a-transaction-after-a-forceclosetransaction/38239
##ekkonap
import clr

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
doc = DocumentManager.Instance.CurrentDBDocument

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *

par_name = IN[0]
exec("par_type = ParameterType.%s" % IN[1])
exec("par_grp = BuiltInParameterGroup.%s" % IN[2])
inst_or_typ = IN[3]
families = UnwrapElement(IN[4])

# class for overwriting loaded families in the project
class FamOpt1(IFamilyLoadOptions):
    def __init__(self): pass
    def OnFamilyFound(self,familyInUse, overwriteParameterValues): return True
    def OnSharedFamilyFound(self,familyInUse, source, overwriteParameterValues): return True

trans1 = TransactionManager.Instance
trans1.ForceCloseTransaction() #just to make sure everything is closed down
# Dynamo's transaction handling is pretty poor for
# multiple documents, so we'll need to force close
# every single transaction we open
result = []

for f1 in families:
    famdoc = doc.EditFamily(f1)
    fResult = []
    try: # this might fail if the parameter exists or for some other reason
        trans1.EnsureInTransaction(famdoc)

	    p=famdoc.FamilyManager.AddParameter(par_name, par_grp, par_type, inst_or_typ)
        fResult.append([f1,True,p.Definition.Name])
        #I don't think I can return the new parameter itself, since it exists in 'famdoc', not in 'doc'
        trans1.ForceCloseTransaction()
        famdoc.LoadFamily(doc, FamOpt1())
    except Exception, e:
	    fResult.append([f1,False,str(e)])
        
    result.append([f1,fResult])
OUT = result
