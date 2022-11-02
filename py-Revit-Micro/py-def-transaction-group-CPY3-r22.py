from Autodesk.Revit.DB import Transaction, TransactionGroup ##For outside and inner transactions
########################################
trans=TransactionGroup(doc, 'trans:DynamoSetDraftCrop') ##Transaction group start name
trans.Start()                                       ##Start outside transaction
    transGrp=Transaction(doc, **Trans_Name_Str**)   ##GROUP Transaction(s)
    transGrp.Start()                                ##Start Group transaction
    ##Do a wrapped thing
    transGrp.Commit()                               ##Commit group transaction for current view : 
trans.Commit()                                      ##Commit the transaction
