from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase

# from logs_housekeeping import errorlogs
from email import policy, parser
import smtplib, email, pdb, re, random, datetime


# def sendEmail(message_ID, in_reply_to, references, to, cc, from, subject, body):
def custom_email_message(message, attachment_dict):
    '''
    @PARAMS: a dictionary containing keys and values to be sent from email
    CALLED BY: views.py
    PURPOSE:
    LOGIC:
    RETURNS:
    '''
    try:
        # vvv note, capitalization of Headers needs to match the html form vvv
        HEADERS = [
            'Subject',
            'Body', # not really a header but used in context dictionary
            'From',
            'To',
            'Bcc',
            'Cc',
            'Message-ID',
            'In-Reply-To',
            'References',
            'Date', # currently not used 8/29/18
            ]
        msg = MIMEMultipart()
        for item in message:
            # vvv set email headers vvv
            if item != 'body':
                #check if item is a header(part of email) and isn't null
                if item in HEADERS and not not message[item]:
                    msg[item] = message[item]
            else:
                # vvv attach body of email vvv
                msg.attach(MIMEText(message[item]))
        # vvv "attachment_dict" comes in as a dictionary of file objects vvv
        for i in attachment_dict:
            file_att = attachment_dict[i]
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(file_att.read())
            email.encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment; filename="%s"' % file_att.name)
            msg.attach(part)
        # vvv return msg as 'raw_message' email.message as 'message_object' vvv
        email_object = email.message_from_bytes(msg.as_string().encode(), policy=policy.default)
        # pdb.set_trace()
        return {'original': msg, 'message': email_object}

    except Exception as e:
        # vvv if there are any errors log them vvv
        # errorlogs.log_error(e)
        return False


# vvv new send email function vvv
