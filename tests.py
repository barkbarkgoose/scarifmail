# --- general imports ---
import pdb

# --- django imports ---
from django.test import TestCase

# --- custom/project imports ---
from scarifmail import models, controller
from . import customlog

# ------------------------------------------------------------------------------
def iterate_emails():
    """
    manually iterate over emails to see their details, meant to be called from
    Django shell
    """
    for eml in EmailObj.objects.all():
        opt = input("quit? y/n: ")
        if opt in ("y", "Y"): break
        else:
            print("-------------")
            print("uidl: ", eml.uidl)
            print("subject: ", eml.subject)
            print("to: ", eml.recipient)
            print("from: ", eml.sender)
            print("date: ", eml.date)
#
# ------------------------------------------------------------------------------
def test_getmail_full(account, testid, keep=False):
    connection = account.get_connection()
    if not connection:
        customlog.writelog("tests", 'account: ' + str(account) + " - unable to connect")
        customlog.writelog("errorlog", 'account: ' + str(account) + " - unable to connect")
        return

    current_uidl = account.current_uidl
    try:
        customlog.writelog("tests", 'account: ' + str(account))
        customlog.writelog("tests", 'started main driver')
        mainerror = controller.main(account)
        if not mainerror:
            customlog.writelog("tests", 'main driver completed successfully')
        else:
            customlog.writelog("tests", 'error running main driver, see controller log for details')

    except Exception as e:
        customlog.writelog("tests", 'error')
        customlog.writelog("testerrors", 'test: ' + testid)
        customlog.writelog("testerrors", str(e))

    # --- delete everything if keep isn't True ---
    if not keep:
        account.current_uidl = current_uidl
        account.reset_mailbox() # clears everything, including trash
        account.save()
#
# ------------------------------------------------------------------------------
def test_get_one_email(account, testid, keep=False) -> object:
    # --- try running the test for one email on given account ---
    connection = account.get_connection()
    if not connection:
        customlog.writelog("tests", 'account: ' + str(account) + " - unable to connect")
        customlog.writelog("errorlog", 'account: ' + str(account) + " - unable to connect")
        return

    current_uidl = account.current_uidl
    eml_object = None
    try:
        customlog.writelog("tests", 'account: ' + str(account))
        customlog.writelog("tests", "grab_eml started")
        eml_message = controller.grab_eml(account)
        customlog.writelog("tests", "grab_eml completed successfully")
        #
        customlog.writelog("tests", "save_eml started")
        eml_object = controller.save_eml(account, eml_message)
        if not eml_object:
            customlog.writelog("tests", "mailbox is empty")
            return

        customlog.writelog("tests", "save_eml completed successfully")
        #
        customlog.writelog("tests", "write_eml started")
        if not controller.write_file(eml_message, eml_object):
            raise Exception("error writing file, check emailerror")
        customlog.writelog("tests", "write_eml completed successfully")
        #
        customlog.writelog("tests", "MSG-ID: " + str(eml_message['MSG-ID']))
        customlog.writelog("tests", "eml_object: " + str(eml_object.id))
        customlog.writelog("tests", "file: " + eml_object.fileloc)

    except Exception as e:
        customlog.writelog("tests", 'error')
        customlog.writelog("testerrors", 'test: ' + testid)
        customlog.writelog("testerrors", str(e))

    # --- reset mailbox to where it was before starting ---
    # uidl = eml_message['UIDL']
    if eml_object:
        if not keep:
            # --- reset uidl position for account ---
            account.current_uidl = current_uidl
            account.save()
            # --- delete email file ---
            eml_object.remove(skip_trash=True)
            eml_object = None
        #
    return eml_object

# ------------------------------------------------------------------------------
