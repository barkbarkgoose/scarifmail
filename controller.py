import os, pdb
import threading # for acquiring lock
import dateutil.parser
import warnings
from bs4 import BeautifulSoup

from django.utils import timezone

from . import customlog
from scarifmail import models

MAILDIR = models.MAILDIR
LOCKFILE = "mailcontroller.lockfile"

"""
controller for managing data flow and process of creating emails, threads, etc.
"""
# ------------------------------------------------------------------------------
class MailLock:
    """
    static class for handling multiple requests to get mail at the same time

    blocks if lock already acquired
    """
    lock = threading.Lock()
    #
    def acquire() -> bool:
        return MailLock.lock.acquire(blocking=True, timeout=1)
    #
    def release():
        try:
            MailLock.lock.release()
        except:
            pass # tried to unlock an uninvoked lock, doesn't matter

# ------------------------------------------------------------------------------
def get_account_info(account=None) -> str:
    """
    prints stats on an account, or all if not specified
    returns the same string that is printed
    """
    outputstr = ""
    print("\n--- ACCOUNT INFO ---")
    if not account:
        account_list = models.MailAcct.objects.all()
        if len(account_list) == 0:
            outputstr = "No accounts set up"
    #
    else:
        account_list = [account]
    #
    info_list = []
    for account in account_list:
        info_list.append(account.stats())
    #
    for account_dict in info_list:
        for key in account_dict:
            outputstr += "%s: %s\n" % (str(key), str(account_dict[key]))
        outputstr += "\n"
    #
    # print(outputstr)
    return outputstr
#
# ------------------------------------------------------------------------------
def new_eml_object(mail_acct, msg_obj, rel_path) -> object:
    """
    save essential headers from email to an email object in database, will be
    used to reference on the page and for quick search/filters
    ** parse out emails for fields needing them
    ** assign email object to a thread object as well (based on references if present)
    if there are any errors the error message *should be* saved.

    """
    # won't make duplicate emails...
    email, email_created = models.EmailObj.objects.get_or_create(
        uidl=msg_obj['UIDL'],
        user=mail_acct,
    )
    if email_created:
        email.uidl = msg_obj['UIDL']
        email.message_id = msg_obj['MSG-ID']
        email.fileloc = str(rel_path)

        try:
            email.sender = models.parse_email(msg_obj['from'])[0]
            email.recipient = models.parse_email(msg_obj['to'])[0]
            if msg_obj['in-reply-to']:
                email.in_reply_to = models.parse_email(msg_obj['in-reply-to'])[0]

            if msg_obj['references']:
                refs = models.parse_email(msg_obj['references'])
                email.references += ', '.join(refs)

            if msg_obj['subject']:
                email.subject = msg_obj['subject']

            if msg_obj['date']:
                email.date = dateutil.parser.parse(msg_obj['date'])
                # email.date = datetime.datetime.strptime(msg_obj['date'], '%a, %d %b %Y %H:%M:%S %z')
                if not timezone.is_aware(email.date):
                    email.date = timezone.make_aware(email.date)

            if msg_obj['cc']:
                email.cc = msg_obj['cc']

            if msg_obj['bcc']:
                email.bcc = msg_obj['bcc']
            # --- save a cleantext version of the email body ---
            body = msg_obj.get_body(preferencelist=('html', 'related', 'plain'))
            content = body.get_content()

            try:
                warnings.filterwarnings('ignore', category=UserWarning, module='bs4')
                cleantext = " ".join((BeautifulSoup(content, "lxml").text).split())
            except:
                cleantext = content

            # vvv 16383 chars stops text from overflowing past SQL limit vvv
            cleantext = email.subject + " " + cleantext
            email.cleantext = cleantext[:16383].lower()
            # --- assign thread for this email ---
            email.assign_thread()

            # --- run filters and assign tags to email thread ---
            email.filter_for_tags()

            email.error = False
            email.save()

        except Exception as e:
            error_msg = 'error saving email: '
            error_msg += str(msg_obj['MSG-ID']) + '\n... ' + str(e)
            customlog.writelog("errorlog", error_msg)
            email.error_msg = error_msg
            email.save()

    return email
#
# ------------------------------------------------------------------------------
# --- processes to get email, save, write file ---
def grab_eml(account) -> object:
    """
    get a single email from the server
    """
    return account.grab_eml()
#
def save_eml(account, eml_message) -> object:
    """
    save eml_message as an object in db, thread will also be assigned inside of
    new_eml_object() function
    """
    fname = eml_message['UIDL'] + '.eml'
    filepath = os.path.join(MAILDIR, account.address, fname)
    return new_eml_object(account, eml_message, filepath)
#
def write_file(eml_message, eml_object) -> bool:
    return eml_object.write_file(eml_message)
#
# ------------------------------------------------------------------------------

def make_account_list(account_in) -> list:
    """
    get list of accounts to process, if one is given as an argument it is returned
    as a list by itself
    """
    if not account_in:
        return models.MailAcct.objects.all()
    else:
        return [account_in]
#
# ------------------------------------------------------------------------------
def main(account_in=None) -> bool:
    """
    main driver for getting and saving/writing emails

    - if account_in argument is missing then will process for all accounts
    """
    # --- attempt to get lock on lockfile here (if environment allows multiple threads) ---
    # if not MailLock.acquire():
    #     # --- couldn't get lock, return ---
    #     customlog.writelog("maillog", "another process is already getting mail --- quitting")
    #     return False # error is false

    account_list = make_account_list(account_in)
    # logstr = "main driver started, account %s, connection: %s, messages on server: %s"
    logstr = "main driver started, account %s, unread messages on server: %s"
    error = False
    try:
        for account in account_list:
            error = None
            customlog.writelog(
                'maillog',
                logstr % (
                    str(account),
                    # str(bool(account.get_connection())),
                    # "True",
                    str(account.stat_unread()),
                )
            )
            # --- acct.stat_unread will update connection status ---
            if not account.connection:
                continue # go to next iteration of for loop
            #
            while True:
                try:
                    eml_message = grab_eml(account)
                except Exception as e:
                    customlog.writelog("errorlog", "error in mail controller main.grab_eml" + str(e))
                    break
                #
                if not eml_message:
                    # --- eml_message will be False when mailbox is empty ---
                    customlog.writelog("maillog", "mailbox empty")
                    break
                #
                try:
                    eml_object = save_eml(account, eml_message)
                except Exception as e:
                    customlog.writelog("errorlog", "error in mail controller main.save_eml" + str(e))
                    break
                #
                try:
                    if not write_file(eml_message, eml_object):
                        # error logged in function call
                        error = True
                    else:
                        pass
                    #
                except Exception as e:
                    customlog.writelog("errorlog", "error in mail controller main.write_file" + str(e))
            #
            customlog.writelog(
                'maillog',
                'finished getting emails for %s, errors: %s, messages left: %s' % (
                    str(account),
                    str(error),
                    str(account.stat_unread()),
                )
            )
    except Exception as e:
        customlog.writelog("maillog", "error - check errorlog")
        customlog.writelog("errorlog", str(e))

    # # --- release lock if previously obtained ---
    # MailLock.release()

    return error
#
# ------------------------------------------------------------------------------
if __name__ == '__main__':
    main()
