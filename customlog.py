"""
# custom logging, skipping all the unhelpful django crap

# imports inside of a project file would look like this
from <app_name>.customlog import writelog

# calling the function would look like this
writelog('errorlog', 'this is an error log')

# the first parameter is the name of the log file to be written to
# that automatically puts in a timestamp, followed by the message passed in

# LOG_DIR needs to be defined in <project_name>.settings
# that will typically be something like: LOG_DIR = os.path.join(BASE_DIR, 'logs')
"""

import datetime
import os
from main.settings import LOG_DIR
#
def writelog(logname, message):
    '''
    writes a custom log at a location decided in project main.settings

    to do:
        - rotate logs based on set timeframe (set in main.settings)
            - default monthly?
    '''
    logfile = os.path.join(LOG_DIR, logname)
    if not os.path.exists(LOG_DIR): os.makedirs(LOG_DIR)
    try:
        with open(logfile, "a+") as targetfile:
            timestamp = datetime.datetime.now().strftime("%b%d-%D-%H:%M:%S")
            logstring = timestamp + " " + str(message) + "\n"
            targetfile.write(logstring)
        #
    except Exception as e:
        print("error in website logging, reason: ", str(e))


#
# ------------------------------------------------------------------------------
