#!python3                   ##Code pre-directive untested!
##Apsis0215 R Allen 2022-11-22-CPy3-R22
import clr
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager
doc = DocumentManager.Instance.CurrentDBDocument        ##Current Document
import Revit
from Autodesk.Revit.DB import FilteredElementCollector,ScheduleSheetInstance,ViewSchedule
from Autodesk.Revit.DB import Transaction                   ##For outside and inner transactions
import Autodesk.Revit.DB as ARDB
import System.Collections.Generic                           ##For dictionary

#SchDict=System.Collections.Generic.Dictionary[System.String,System.Collections.IList]()
SchArr=[]
def Views_Remove_ViewTemplates(Views):                      ##To remove view templates in list views
    viewlist = []   
    for view in Views:
    	if view.IsTemplate == False:                        ##If Is Template = false then
    		viewlist.append(view)                           ##Add to return list
    return viewlist                                         ##Return list of views (Not view templates)

PlacedSchedules = FilteredElementCollector(doc).OfClass(ScheduleSheetInstance).WhereElementIsNotElementType().ToElements()
PlacedSchedulesID=[VID.ScheduleId for VID in PlacedSchedules]

AllSchedules = FilteredElementCollector(doc).OfClass(ViewSchedule).WhereElementIsNotElementType().ToElements()
AllSchedulesID =[VID.Id for VID in AllSchedules]

##https://stackoverflow.com/questions/33577790/exclude-items-from-list-of-lists-python
SchedNotPlaced=[element for element in AllSchedulesID if element not in PlacedSchedulesID]  ##Get schedile IDs to comp
SchedNotPlaced=[doc.GetElement(VSHID)  for VSHID in SchedNotPlaced] ##Convert back to schedule

SchedNotPlaced = Views_Remove_ViewTemplates(SchedNotPlaced)

##https://forum.dynamobim.com/t/python-dictonnary-with-sheets-list/83380/2
Sch=PlacedSchedules.pop()                                   ##Pop one off to prime
sht=doc.GetElement(Sch.get_OwnerViewId())                   ##Get sheet from ID
SchArr=[[Sch,sht]]                                          ##Schedule Array: the list of sublists primed with 1st element

rev=[]
for Sch in PlacedSchedules:                                 ##For each additional place schedule
    sht=None                                                ##Set sheet for placed schedule
    sht=doc.GetElement(Sch.get_OwnerViewId())               ##Get SHEET from owner view ID               
     
    #sos=doc.GetElement(Sch.ScheduleId)                      ##Get source schedule
    
    found=False                                             ##REset found

    if doc.GetElement(Sch.ScheduleId).Name.find("<Revision Schedule>") == -1:   ## Not a revision schedule

        for ssch in SchArr:                                     ##Existing list of schedules
            if ssch[0].Name == Sch.Name:                        ##If Schedule name = data pair element 0 name (schedule)#
                ssch.append(sht)                                ##Append to data pair[1] (Array of sheets)
                found=True                                      ##Found=true
                break ##to for Sch...                           ##Break to outer loop
        if not found:
            SchArr.append([Sch,sht])
    else:                                                   ##Is a revision schedule - stack those together
        rev.append([Sch,sht])                               ##Separate list ofr sequential revision schedules on sheets
        
##SchArr.extend(rev)                                        ##Extend Schedule array: with revision schedules
#################################################################
for Sch in SchArr:											##convert schedule on sheet to schedule viewSet all the schedules to the original schedule object not the schedule on sheet object
    Sch[0]=doc.GetElement(Sch[0].ScheduleId)
    break
##SchArr.sort

Msg=[]                              ##PRetty text indented
for Sch in SchArr:                  ##For elements int each array
    Msg.append(Sch[0].Name)         ##Schedule name without indents
    for Sht in Sch[1:]:             ##from position 2 to end of array...
        Msg.append("   " + Sht.Name) ##Append a few spaces and the name

OUT=SchArr,Msg
