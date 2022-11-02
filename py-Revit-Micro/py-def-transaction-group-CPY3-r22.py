from Autodesk.Revit.DB import Transaction, TransactionGroup ##For outside and inner transactions
########################################
trans=TransactionGroup(doc, 'DYN:[some name for transaction]') ##Transaction group start name 'DYN:' optional
trans.Start()                                       ##Start outside transaction
    transGrp=Transaction(doc, 'DYN:TransGrpName')   ##GROUP Transaction(s) 'DYN:' optional
    transGrp.Start()                                ##Start Group transaction
    ##Do a wrapped thing
    transGrp.Commit()                               ##Commit group transaction for current view : 
trans.Commit()                                      ##Commit the transaction
