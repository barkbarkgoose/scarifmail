# --- general imports ---
import poplib, datetime, os, re, email, pdb, time, concurrent.futures
import dateutil.parser
import random, shutil, time, signal
from multiprocessing import Process
from passlib.hash import pbkdf2_sha256

# --- django imports ---
from django.db import models
from django.contrib.auth.models import User
from django import forms
from django.utils import timezone

# --- custom app imports ---
from main import settings
from scarifmail import scarifsettings
from jake_template.django_things import customlog
from bs4 import BeautifulSoup

# email import stuff
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
import smtplib, html2text, pprint

# from support.logs_housekeeping import errorlogs as ilog
# from scarifmail.email_processing import mailfunc

# --- define static global vars ---
EFILE_ROOT = scarifsettings.EFILE_ROOT # where email files will be written to
#
# --- directory for email files to be placed under when they are set to delete
MAILDIR = os.path.join(settings.BASE_DIR, 'scarifmail/eml_files')

# ------------------------------------------------------------------------------
def parse_email(e_in):
    """
    returns list of emails from string (in most cases will be 1 string in list)
    - so to get just one string or the first in the set call parse_email(e_in)[0]
    from outside of this function
    """
    try:
        matches = re.findall('[^<>,\s]+@[^<>,\s]+', str(e_in))
        if len(matches) > 0:
            return matches
        else:
            # why this second case??
            # need to figure out how to handle when empty strings are found
            matches = re.findall('[^<>\s]+', str(e_in))
            return matches
    except:
        ### if all else fails return the original string as single element in array
        if str(e_in) == '':
            return []
        return [e_in]

# ******************************************************************************
class MailGroup(models.Model):
    name = models.CharField(
        verbose_name='group name',
        max_length=128,
        unique=True,
    )
    is_active = models.BooleanField(
        # --- set this to False to deactivate a group without deleting it ---
        default=True,
        verbose_name="group is active"
    )
    require_staff = models.BooleanField(
        default=False,
        verbose_name="group requires users to have staff permissions",
    )
    require_admin = models.BooleanField(
        default=False,
        verbose_name="group requires users to have admin permissions",
    )
    users = models.ManyToManyField(User)
    mail_accounts = models.ManyToManyField('MailAcct')

    # --------------------------------------------------------------------------
    def __str__(self):
        return self.name

    # --------------------------------------------------------------------------
    def save(self, *args, **kwargs):
        # if self.require_admin == True:
        #     # --- update any admin groups to also be staff ---
        #     self.require_staff = True
        super(MailGroup, self).save(*args, **kwargs)

# ******************************************************************************
class Thread(models.Model):
    """
    class that links emails together if they are part of the same conversation
    """
    thread_id = models.TextField()
    subject = models.TextField(null=True, default="")
    unread = models.BooleanField(default=True)
    user = models.ForeignKey('MailAcct', null=True, on_delete=models.SET_NULL)
    tags = models.ManyToManyField('FilterTag')

    # --------------------------------------------------------------------------
    @property
    def thread_tags(self):
        return self.tags.all()

    # --------------------------------------------------------------------------
    def get_related_emails(self) -> list:
        """ return QuerySet of all email objects with thread in ForeignKey """
        return EmailObj.objects.filter(thread=self)

    # --------------------------------------------------------------------------
    def last_email(self) -> object:
        """ returns info based on last email in the thread """
        if len(EmailObj.objects.filter(thread=self)) == 0:
            return None
        return EmailObj.objects.filter(thread=self).latest('date')

    @property
    def last_email_topage(self):
        return self.last_email()

    # --------------------------------------------------------------------------
    def clear_thread(self):
        pass

    # def delete(self):
        # self.remove()
    # --------------------------------------------------------------------------
    def remove(self, skip_trash=False):
        '''
        goes througha and removes all related email files, then deletes the email
        object
        '''
        #
        for email in self.get_related_emails():
            email.remove(skip_trash)
            # os.remove(email.fileloc)
            self.user.current_uidl = email.uidl
            # email.delete()
        #
        self.user.save()
        self.delete()

# ******************************************************************************
class FilterTag(models.Model):
    """
    tags can be assigned to threads
    """
    def __str__(self):
        return self.name
    #
    name = models.CharField(max_length=128)

# ******************************************************************************
class Filter(models.Model):
    def __str__(self):
        return self.name
    #
    name = models.CharField(max_length=128)
    match_all = models.BooleanField(default=False)
    subject = models.CharField(max_length=128, null=True, blank=True, default=None)
    subject_exact_match = models.BooleanField(default=False)
    sender = models.CharField(max_length=128, null=True, blank=True, default=None)
    sender_exact_match = models.BooleanField(default=False)
    recipient = models.CharField(max_length=128, null=True, blank=True, default=None)
    recipient_exact_match = models.BooleanField(default=False)
    cleantext = models.CharField(
        max_length=128,
        null=True, blank=True,
        default=None,
        verbose_name="body",
    )
    cleantext_exact_match = models.BooleanField(default=False, verbose_name="exact match on body")
    # date = models.CharField(max_length=128, null=True, blank=True, default=None)
    # date_exact_match = models.BooleanField(default=False)
    cc = models.CharField(max_length=128, null=True, blank=True, default=None)
    cc_exact_match = models.BooleanField(default=False)
    bcc = models.CharField(max_length=128, null=True, blank=True, default=None)
    bcc_exact_match = models.BooleanField(default=False)
    # ??? age in days ???
    tag = models.ForeignKey('FilterTag', null=True, on_delete=models.SET_NULL)

    def filter_email(self, emailobj) -> bool:
        """
        checks if attributes of filter match those of given emailobj, returns true
        or false

        case insensitive
        """
        attr_list = ["subject", "sender", "recipient", "cleantext", "cc", "bcc"]
        for item in attr_list:
            filter_attr = getattr(self, item)
            if filter_attr:
                # --- filter attribute is not None ---
                email_attr = getattr(emailobj, item)
                if email_attr:
                    filter_attr = filter_attr.lower()
                    email_attr = email_attr.lower()

                filter_attr_exact = getattr(self, item + "_exact_match")
                #
                if filter_attr_exact:
                    # --- exact match on attr ---
                    match = filter_attr == email_attr
                else:
                    # ---
                    match = filter_attr in email_attr
                #
                # --- check if match_all case is met for filter ---
                if self.match_all:
                    # --- return False with first unmatched attribute ---
                    if not match: return False
                else:
                    # --- return True with first matched attribute ---
                    if match: return True

        # --- no return conditions met inside of the for loop ---
        # --- return conditions for match_all flip outside of loop ---
        if self.match_all:
            # getting to this point implies that all fields matched
            return True
        else:
            # this implies that no fields matched
            return False
    #
# ******************************************************************************
class EmailObj(models.Model):
    """
    EmailObj is unaware of the MailAcct class written below.

    """
    uidl = models.TextField(null=True, blank=True)
    error = models.BooleanField(default=True)
    error_msg = models.TextField(null=True, blank=True)
    thread = models.ForeignKey('Thread', on_delete=models.CASCADE, null = True)
    user = models.ForeignKey('MailAcct', null=True, on_delete=models.SET_NULL)
    sender = models.EmailField(null=True)
    recipient = models.EmailField(null=True)
    in_reply_to = models.TextField(null=True)
    references = models.TextField()
    subject = models.TextField(null=True)
    date = models.DateTimeField(default=(timezone.now))
    message_id = models.TextField(null=True)
    cc = models.TextField(null=True)
    bcc = models.TextField(null=True)
    fileloc = models.TextField()
    # --- cleantext is the stripped down text from email body ---
    # max size for TextField is 65,535 bytes.
    # utf-8 uses up to 4 bytes for each character, at that rate you have roughly
    # 16,383 characters that can be stored in a single field.
    cleantext = models.TextField(default="")

    # --------------------------------------------------------------------------
    def assign_thread(self):
        """
        - threads are based on the 'references' header. This app's will always look
        at the first reference.  If no previous references then the new email's
        id is used as the id for a new thread.
        - filters will get emails by the user && a thread match.  If an email is
        bcc'd you could potentially have two emails (in different inboxes) with
        the same Message-ID.
        - will save email object
        """
        match = False
        refs = parse_email(self.references)
        refs.insert(0, self.message_id)
        for item in refs:
            if Thread.objects.filter(thread_id__icontains=item).exists():
                tlist = Thread.objects.filter(thread_id__icontains=item)
                self.thread = tlist[len(tlist)-1]
                match = True

        if not match:
            thread = Thread(thread_id=self.message_id, user=self.user)
            thread.subject = self.subject
            thread.save()
            self.thread = thread

        # # --- run filters on email and assign matching tags to thread ---
        # for filter in Filter.objects.all():
        #     if filter.filter_email(self):
        #         self.thread.tags.add(filter.tag)

        self.thread.save()
        #
        # thread is marked as unread by default when email is linked
        self.thread.unread = True
        # self.thread.save()
        self.save()

    # --------------------------------------------------------------------------
    def filter_for_tags(self):
        # --- run filters on email and assign matching tags to thread ---
        for filter in Filter.objects.all():
            if filter.filter_email(self):
                self.thread.tags.add(filter.tag)
        #
        self.save()

    # --------------------------------------------------------------------------
    def read_file(self):
        """
        - gets file and returns message object
        - relpath is the date -> fname

        - will return False and set error flag if unable to read or find file
        """
        try:
            f = open(self.fileloc, 'rb')
            msg = email.message_from_binary_file(f, policy=(email.policy.default))
            f.close()
            return msg
        except:
            self.error = True
            self.error_msg = "Unable to find file: " + self.fileloc
            return False

    # --------------------------------------------------------------------------
    @property
    def body_to_page(self):
        """ send email body to template """
        msg = self.read_file()
        if msg:
            if msg.is_multipart() and not self.has_attachments:
                body = self.walk_email_for_body(msg)
            else:
                body = self.get_body()

            body = body.replace("!important;", ";")
            return body

    # --------------------------------------------------------------------------
    def get_cleantext(self):
        """
        returns body of email in format without any spacing or newlines
        """
        cleantext = " ".join((BeautifulSoup(self.get_body(), "lxml").text).split())
        return cleantext

    # --------------------------------------------------------------------------
    def get_body(self):
        """
        - returns body of email file, uses read_file function
        - preferred types go in order they are placed in the preferencelist arg
        """
        msg = self.read_file()
        if msg:
            body = msg.get_body(preferencelist=('html', 'related', 'plain'))
            content = body.get_content()
            return content
        else:
            return str(self.error_msg)

    # --------------------------------------------------------------------------
    def date_match(self, datein) -> bool:
        """
        checks to see if datetime object passed in matches the year, month, and day
        of this email's saved date attribute.
        """
        if datein.year != self.date.year:
            return False
        if datein.month != self.date.month:
            return False
        if datein.day != self.date.day:
            return False
        #
        return True

    # --------------------------------------------------------------------------
    def search_attributes(self, *args, **kwargs) -> bool:
        """
        goes through each named argument passed in, if it is an EmailObj attribute then
        check if there is a match.  Positional arguments are ignored

        if all arguments match then the function resolves as True

        dateutil.parser.parse(msg_obj['date'])

        NOTE ON SEARCHING DATES:
            datetime(year, month, day[, hour[, minute[, second[, microsecond[,tzinfo]]]]])

            The year, month and day arguments are required. tzinfo may be None, or an
            instance of a tzinfo subclass. The remaining arguments may be ints.
        """
        for kwarg in kwargs:
            if hasattr(EmailObj, kwarg):
                value = getattr(self, kwarg)
                if str(kwargs[kwarg]) != str(value):
                    return False

        # --- all valid arguments match, return True ---
        return True
    #
    # --------------------------------------------------------------------------
    def search_body(self, searchstr, exact_match=False) -> bool:
        """
        searches email body (and subject) for a string, returns True/False on match

        breaks search string into a list of parts, checks for each of those parts
        inside the email body, if they are all found (in order) then the function
        resolves as True.

        this search does not worry if duplicate instances of a word exist, just
        that each one is present and appears in the order given

        exact_match=True will search for exact string matches
        """
        cleantext = self.subject
        cleantext += BeautifulSoup(self.get_body(), "lxml").text

        if exact_match:
            # --- need exact match for entire search string ---
            # exact match also takes capitalization and spacing into account
            if searchstr in cleantext:
                return True
            #
        else:
            # --- check if all items of search_list are in the body_list ---
            body_list = cleantext.lower().split()
            search_list = searchstr.lower().split()
            #
            for item in body_list:
                if search_list[0] in item:
                    search_list.pop(0)
                    if len(search_list) == 0:
                        # --- all search parameters have been found ---
                        return True
        #
        # --- neither case for a matching string was found ---
        return False
    #
    # --------------------------------------------------------------------------
    @property
    def has_attachments(self):
        if len(self.get_attachments()) > 0:
            return True
        else:
            # will return an emply list if
            return False

    # --------------------------------------------------------------------------
    @property
    def is_html(self):
        msg = self.read_file()
        if msg:
            tlist = [item['content-type'] for item in msg.walk()]
            for item in tlist:
                if 'text/html' in item:
                    return True
        return False

    # --------------------------------------------------------------------------
    def walk_email_for_body(self, original, parent_headers=None):
        '''
        walks through email in case it is multipart and returns portion that should
        be the body, if a section is html formatted that is preferred.

        takes email message as 2nd parameter since that will change in recursive calls
        to grab body from a multipart message
        '''
        tlist = [item['content-type'] for item in original.walk()]

        html_format = False
        if len(tlist) > 0:
            for item in tlist:
                if item and 'text/html' in item:
                    html_format = True
        if parent_headers is None:
            parent_headers = original.keys()
        for part in original.walk():
            # vvv in multipart headers, go on to next iteration vvv
            if part.is_multipart() and part.keys() == parent_headers: #max 5 recursion for walk_email()
                continue
            #vvv if part is multipart then recursively walk that part again
            elif part.is_multipart() and part.keys() != parent_headers:
                self.walk_email_for_body(part, part.keys())
                # ??? might need to turn ^^^ into a return statement ???
            #vvv leaf found
            else:
                #vvv return part if it isn't an attachment (body is usually only one section)
                ''' vvv need to check if body ever has more than one part vvv '''
                if not part.is_attachment():
                    # if a part of email is html format wait to return that
                    if html_format:
                        if part.get_content_type() == 'text/html':
                            body = part.get_body(
                                preferencelist=('html', 'related', 'plain')
                            )
                            return body.get_content()
                    else: # if no html parts return first body part that matches
                        body = part.get_body(
                            preferencelist=('html', 'related', 'plain')
                        )
                        return body.get_content()
    #
    # --------------------------------------------------------------------------
    def get_attachments(self):
        """
        - returns iterator over attachments from .eml file
        """
        alist = []
        msg = self.read_file()
        if msg:
            attachments = msg.iter_attachments()
            for item in attachments:
                alist.append(item)
        # returns an empty list if none found
        return alist

    # --------------------------------------------------------------------------
    def write_file(self, eml_message) -> bool:
        """
        - uidl is a custom header added to all emails.  pulled from the id assigned
        by the mailserver
        - save email obj as text .eml file
        """
        try:
            # check for mail directory
            filepath = os.path.join(self.fileloc)
            filedir = os.path.dirname(self.fileloc)
            os.makedirs(filedir, exist_ok=True)

            with open(filepath, 'wb') as f:
                f.write(bytes(eml_message))
                # gen = email.generator.Generator(f)
                # gen.flatten(eml_message)
            return True
        except Exception as e:
            self.error = True
            self.save()
            errorstr = "unable to write email file - " + str(self.fileloc) + " "+ str(e)
            customlog.writelog('errorlog', errorstr)
            return False

    # --------------------------------------------------------------------------
    def trash_file(self) -> bool:
        """
        returns bool value of whether file moved successfully or not
        """
        filename = os.path.basename(self.fileloc)
        basepath = os.path.dirname(self.fileloc)
        filepath = os.path.join(basepath, 'trash')
        os.makedirs(filepath, exist_ok=True)
        try:
            if not os.path.exists(os.path.join(filepath, filename)):
                shutil.move(self.fileloc, filepath)
                # self.fileloc = os.path.join(filepath, filename)
                # self.save()
            # self.fileloc = filepath
            # self.save()
            return True
        except FileNotFoundError:
            return True

        except Exception as e:
            self.error = True
            self.error_msg = str(e)
            customlog.writelog('errorlog', 'email.trash_file - ' + str(e))
            # self.save()
            return False

    # --------------------------------------------------------------------------
    def remove(self, skip_trash=False):
        # --- first check thread and delete if empty or if this is it's only related email---
        #
        if self.thread:
            if len(self.thread.get_related_emails()) <= 1:
                self.thread.delete()
        #
        if skip_trash:
            # --- remove file skipping trash ---
            try:
                os.remove(self.fileloc)
            except Exception as e:
                customlog.writelog('errorlog', 'unable to delete %s - %s' % (str(self.fileloc), str(e)))
            self.delete()
        #
        else:
            # --- attempt to move file to trash, mark with error if not ---
            if self.trash_file():
                self.delete()


# ******************************************************************************
class MailAcct(models.Model):
    """
    - MailAcct acts like a mail account and has a one to many relationship with
    threads and email objects saved.  Its primary function is connecting to the
    mail server.

    common mailservers:
    Faxpipe    both     office.aircomusa.com
    gmail	   IMAP4	imap.gmail.com
    gmail	   POP3	    pop.gmail.com
    comprehensive lists can be found online

    Default Ports:                      Server: 	      Auth: 	    Port:
    SMTP Server (Outgoing Messages) 	Non-Encrypted 	  AUTH 	        25 (or 587)
  	                                    Secure (TLS)   	  StartTLS 	    587
  	                                    Secure (SSL)   	  SSL 	        465
    POP3 Server (Incoming Messages) 	Non-Encrypted     AUTH 	        110
  	                                    Secure (SSL)      SSL 	        995
    """
    user = models.TextField()
    address = models.EmailField()
    server = models.CharField(max_length=128)
    autoremove = models.BooleanField(
        verbose_name = "automatically delete emails from server after they are popped",
        default=False,
    )
    portno_in = models.IntegerField(default=995) # default is pop3 ssl
    portno_out = models.IntegerField(default=465) # default is ssl smtp
    password = models.CharField(max_length=128)
    current_uidl = models.CharField(max_length=64, null=True, blank=True, default=None)

    # --------------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        """
        # --- constructor ---
        initialize self.connection variable
        """
        super(MailAcct, self).__init__(*args, **kwargs)
        # if not 'connection' in self.__dict__:
        self.connection = False
        self.connect_err = ""

    # --------------------------------------------------------------------------
    def __del__(self, *args, **kwargs):
        """
        # --- destructor ---
        close any open connections when destructor is called
        """
        if self.connection:
            self.connection.close()

    # runtime variables ---------------------------------
    # def set_connection(self):
    #     """
    #     set temp connection value for this MailAcct instance
    #     """
    #     self.pop_connect()
    #     # self.connection = self.pop_connect()
    #     if connect_status:
    #         self.connection = connection
    #
    #     return (connect_status, connection)
    # --------------------------------------------------------------------------
    def stats(self) -> dict:
        """
        returns a dict of string values for stats on the account
        """
        serverstats = self.server_stat()
        infodict = {
            "account": str(self),
            "connected": bool(self.get_connection()),
            "uidl": self.current_uidl,
            "remote_emails": serverstats['num_total'],
            "unread": self.stat_unread(),
            "saved_threads": len(self.get_threads()),
            "saved_emails": len(self.get_related_emails()),
            "error_emails": EmailObj.objects.filter(user=self, error=True),
        }

        return infodict
    #
    @property
    def attr_stats(self) -> dict:
        return self.stats()

    # --------------------------------------------------------------------------
    def get_connection(self) -> object:
        """
        get temp connection value for this MailAcct instance

        self.connection will be set to False if unable to connect
        """
        # if not 'connection' in self.__dict__:
        # if not self.connection:
        #     self.set_connection()
        # else:
        #     self.test_connection()

        # --- update connection status ---
        if self.connection:
            try:
                self.connection.noop()
            except:
                self.pop_connect()
        else:
            self.pop_connect()

        # self.test_connection()

        return self.connection
    #
    @property
    def attr_get_connection(self) -> bool:
        return bool(self.get_connection())

    # ---------------------------------------------------
    def __str__(self):
        return self.address

    # --------------------------------------------------------------------------
    def reset_uidl(self):
        """
        reset temp uidl
        """
        self.current_uidl = None
        self.save()

    # --------------------------------------------------------------------------
    def grab_eml(self) -> object:
        '''
        get a single email from server, return email object or None
        '''
        # --- get next email from server ---
        connection = self.get_connection()
        #
        if not connection:
            return None
        # unread = self.stat_unread()
        pos = self.check_uidl()

        if pos > 0:
            # --- parse for headers, convert to email.message ---
            try:
                aaa = connection.retr(pos)
                if not self.autoremove:
                    connection.rset()

                orig_content = aaa[1]
                server_id = connection.uidl(pos).split()[2].decode('utf-8')
                eml = b'\n'.join(orig_content)
                email_message = email.message_from_bytes(eml, policy=email.policy.default)

                # --- UIDL and MSG-ID are custom headers we use to help later on ---
                email_message['UIDL'] = server_id

                if not email_message['Message-ID'] or '@' not in email_message['Message-ID']:
                    email_message['MSG-ID'] = email_message['UIDL']

                else:
                    message_id = parse_email(email_message['Message-ID'])[0]
                    email_message['MSG-ID'] = message_id

                self.current_uidl = server_id
                self.save()
            except Exception as e:
                raise Exception(e)
        else:
            email_message = None

        return email_message
    #
    # --------------------------------------------------------------------------
    def check_uidl(self):
        """
        compare last_uidl with server to find position to start popping from
        default position is 1,

        *** WILL RETURN 0 IF NO NEW MAIL ***

        NOTE: will return one position past the current uidl, so if we ended at pos
        7 last time this will return 8
        """
        ulist = [item.split()[1].decode('utf-8') for item in self.connection.uidl()[1]]
        # go up two spaces, will be out of bounds if current_uidl is last item
        # (server indexing starts at "1" vs the response here which starts at "0"
        # hence adding "2")
        if self.current_uidl in ulist:
            pos = ulist.index(self.current_uidl) + 2
            if pos > self.connection.stat()[0]:
                pos = 0 # no new mail
        else:
            # current_uidl not on server (all mail is new)
            pos = 1

        return pos
    #
    # --------------------------------------------------------------------------
    def clear_all_mail(self, skip_trash=False) -> bool:
        """
        delete all related email objects
        """
        try:
            # --- first check for threads and delete those ---
            for thread in Thread.objects.filter(user=self):
                thread.remove(skip_trash)
            # --- second pass to delete any remaining emails ---
            for email in self.get_related_emails():
                email.remove(skip_trash)
            #
            self.current_uidl = None
            self.save()
            return True
        #
        except Exception as e:
            customlog.writelog('errorlog', 'clear_all_mail - ' + str(e))
            return False

    #
    # --------------------------------------------------------------------------
    def clear_new_mail(self, uidl):
        '''
        clears all mail back to provided uidl
        '''
        pass

    # --- not in use by controller Jan 11, 2020 ---
    # def clear_deleted(self):
    #     """
    #     removes the 'deleted' directory. and recreates new empty dir when done
    #     - shutil.rmtree will remove a directory and any of it's contents
    #     - os.remove gets rid of a file
    #     - os.rmdir will delete a non-empty directory
    #     returns 'True' if successful
    #     """
    #     try:
    #         dirpath = os.path.join(mailfunc.MAILDIR, self.address, mailfunc.RMDIR)
    #         shutil.rmtree(dirpath)
    #         os.makedirs(dirpath, exist_ok=True)
    #         return True
    #     except:
    #         return False
    #
    # --------------------------------------------------------------------------
    def reset_mailbox(self):
        """
        will reset mailbox by deleting it's sub directory inside of the MAILDIR
        returns 'True' if successful.

        Note: this also deletes the Trash directory inside the mailbox
        """
        try:
            self.clear_all_mail(skip_trash=True)
            # self.clear_deleted()
            dirpath = os.path.join(MAILDIR, self.address)
            if os.path.exists(dirpath):
                shutil.rmtree(dirpath)
            return True

        except Exception as e:
            customlog.writelog('errorlog', 'reset_mailbox - ' + str(e))
            return False

    # --------------------------------------------------------------------------
    def get_threads(self):
        return Thread.objects.filter(user=self)
    #
    # --------------------------------------------------------------------------
    def get_related_emails(self):
        """ return QuerySet of all email objects with user in ForeignKey """
        return EmailObj.objects.filter(user=self)
    #
    # --------------------------------------------------------------------------
    def search_emails(self, searchstr, exact_match=False):
        """
        return a list of emails that match the given search string
        checks subject and body

        queryset of EmailObjs
        """
        results = self.get_related_emails()
        searchstr = searchstr.lower()
        if not exact_match:
            # --- run through each item in search string ---
            searchstr = searchstr.split()
            for arg in searchstr:
                results = results.filter(cleantext__icontains=arg)
        else:
            # --- search once for the string passed in
            results = results.filter(cleantext__icontains=searchstr)
        #
        return results
    #
    # --------------------------------------------------------------------------
    def search_threads(self, searchstr, exact_match=False):
        """
        first searches for emails matching searchstr, then returns a list of threads
        that contain the emails

        returns a set of threads
        """
        email_list = self.search_emails(searchstr, exact_match)
        return list(set(eml.thread for eml in email_list))
    #
    # --------------------------------------------------------------------------
    def pop_connect(self):
        """
        connect to server and return connection info
        COMMON PORTS: (try to make connection without specifying port #)
            gmail - pop.gmail.com - 995
            aircom - office.aircomusa.com - 1100

        signal_handler will timeout after 5 seconds

        sets the self.connection variable
            - if unable to connect, puts reason into self.connect_err
        """
        def signal_handler(signum, frame):
            sys.exit(1)
        #
        signal.signal(signal.SIGALRM, signal_handler)
        try:
            signal.alarm(5) #timeout 5 seconds
            try:
                M = poplib.POP3_SSL(self.server)
            except:
                signal.alarm(3) #timeout 3 seconds
                M = poplib.POP3(self.server, self.portno_in)
                M.stls(context=None)

            # --- no timeout, deactivate alarm ---
            signal.alarm(0)
            M.user(self.user)
            M.pass_(self.password)

            self.connection = M

        except Exception as e:
            self.connection = False
            self.connect_err = str(e)

    #
    # --------------------------------------------------------------------------
    def stat_unread(self) -> int:
        '''
        returns number of unread messages on server

        if unable to connect will return error message
        '''
        # --- double check for connection ---
        connection = self.get_connection()
        if not connection:
            return "ERR can't connect: " + self.connect_err

        # note: pos is index of next email to be popped
        pos = self.check_uidl()

        if pos == 0:
            # --- no new messages ---
            num_unread = 0
        #
        else:
            # --- current_uidl found on server, get everything after that ---
            num_unread = connection.stat()[0] - (pos - 1) # from last popped email (not next)

        return num_unread
    #

    @property
    def attr_stat_unread(self) -> int:
        return self.stat_unread()

    # --------------------------------------------------------------------------
    def server_stat(self) -> dict:
        '''
        returns dictionary of stats on server
        '''
        connection = self.get_connection()
        if not connection:
            stat_dict = {
                "pos": 0,
                "num_total": 0,
                "connection": f"ERR can't connect: {self.connect_err}",
            }
        else:
            stat_dict = {
                "pos": self.check_uidl(),
                "num_total": connection.stat()[0],
            }
        return stat_dict
    #
    # --------------------------------------------------------------------------
    def send_email(self, last_email, email_form) -> bool:
        # send email with name of us flag file to bdurney1@gmail.com
        error_status = False
        thread = last_email.thread
        try:
            host = re.findall('@(\\w+)\\.', self.address)[0]
            msg = MIMEMultipart()
            msg['Message-ID'] = '<'+ str(random.randint(1,1001)) + "-"
            msg['Message-ID'] += datetime.datetime.now().strftime("%m%d%y%H%M%S")
            msg['Message-ID'] += '@' + host + '.com>'
            msg['In-Reply-To'] = last_email.message_id
            msg['From'] = email_form["sender"]
            msg['To'] = email_form["recipient"]
            msg['Date'] = formatdate(localtime=True)
            msg['Subject'] = email_form["subject"]
            msg['Cc'] = ", ".join(email_form['cc'])
            bcc = email_form['bcc']

            if self.address not in bcc:
                bcc.append(self.address)

            msg['bcc'] = ", ".join(bcc)

            if last_email.references:
                refstr = ''
                for item in last_email.references.split():
                    refstr += '<'+item+'> '
                refstr += '<'+ last_email.message_id +'>'
                msg['References'] = refstr
            else:
                msg['References'] = '<'+ last_email.message_id +'>'
            thread.thread_id = msg['References']
            thread.save()

            if type(email_form['email_body']) == list:
                html_text = " ".join(email_form['email_body'])
            else:
                html_text = email_form['email_body']

            plain_text = html2text.html2text(html_text)

            msg.attach(MIMEText(plain_text, 'plain'))
            msg.attach(MIMEText(html_text, 'html'))
            # with open(os.path.join('flags/us-lgflag.gif'), 'rb') as fil:
            #     part = MIMEApplication(fil.read(), Name=basename)
            # part['Content-Disposition'] = 'attachment: filename = "%s"' % basename
            # msg.attach(part)
        except Exception as e:
            error_status = True
            error_msg = "error in handling outbound email data: " + str(e)
            customlog.writelog('errorlog', error_msg)
        if not error_status:
            server = smtplib.SMTP(self.server, self.portno_out)
            if settings.DEBUG:
                customlog.writelog(
                    'debuglog',
                    f"msg set up and ready to send:\n{pprint.pformat(dict(msg))}"
                )
            try:
                # server.send_message(msg)
                server.quit()
            except:
                try:
                    # not sure if any of this will work
                    server.ehlo()
                    server.starttls()
                    # server.login(self.self, self.password)
                    # server.sendmail(self.address, msg['From'], msg.as_string())
                    server.close()
                except Exception as e:
                    error_msg = "couldn't make connection to outbound server: " + str(e)
                    customlog.writelog('errorlog', error_msg)

        return error_status
    #
    # --------------------------------------------------------------------------

# ------------------------------------------------------------------------------
