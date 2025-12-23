##These can be defined input values in a DYF:
##IN[0] = List_Text: var[]..[] = ["No Input."]        ## List of string values to report in separate lines
##IN[1] = Form_Width_PX_300: int = 300                ##Form width in pixels
##IN[2] = Form_Height_PX_800: int = 800               ##For height in pixels
##IN[3] = Title_String_Result: string = ["Result:"]   ##Title string at top of form

import clr
import sys

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System
from System import Drawing
import System.Drawing
import System.Windows.Forms

from System.Drawing import *
from System.Windows.Forms import *
import math

##https://forum.dynamobim.com/t/reporting-to-user-at-the-end-of-dynamo-player-script/37421/6
from System.Windows.Forms import Form,Label,Button,FormBorderStyle,FormStartPosition

text="\n".join(IN[0])           #String each list item together with a return wrapline

#if IN[1] > 0 :                      ##Form Width input 1
fWide=IN[1]                     ##Use it
#else:
#    fWide=int(400)                       ##Use default
# 
#if IN[2] > 0 :
fHigh=IN[2]                     ##Form Height input 2
#else:
#    fHigh=int(800)                       ##Use default
# 
#if IN[3] > "" :
title=IN[3]                     ##Form Height input 2
#else:
#    title="Result:" 
#################################################################################
class popup(Form):
    ##
    def __init__(self,text):
        self.InitializeComponent(text)
        
    def InitializeComponent(self,text): 
        #form = Form() 
        self.ClientSize = System.Drawing.Size(fWide, fHigh)                 ##Height
        self.Text = title           ##Form Title
    
        self.FormBorderStyle  = FormBorderStyle.FixedDialog ##Remove the maximize box.
        self.MaximizeBox = False            ## Set the MinimizeBox to false to remove the minimize box.
        self.MinimizeBox = False            ## Set the accept button of the form to button1.
        self.StartPosition = FormStartPosition.CenterScreen
        self.AutoScroll = True
        self.ScrollBars = ScrollBars.Vertical
       
        ########Label for text#####
        
        self.label = Label() 
        self.label.Parent = self 
        self.label.Text = text 
        self.label.TextAlign = ContentAlignment.TopLeft
        self.label.Font = System.Drawing.Font("Tahoma", 8, System.Drawing.FontStyle.Regular, System.Drawing.GraphicsUnit.Point, 0)
        
        self.label.AutoSize = True

        ##This was the key to wrapping hte text inside the lable on the form:
        ##https://stackoverflow.com/questions/1204804/word-wrap-for-a-label-in-windows-forms
        self.label.MaximumSize  = System.Drawing.Size(self.Width-40,0)
        self.label.WordWrap=True
        
        self.label.Left=10
        self.label.Top=10 
        self.ResumeLayout(False)


oForm=popup(text)    ##Set the form with the text value
oForm.ShowDialog()              ##Show the form

