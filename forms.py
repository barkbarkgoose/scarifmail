from django.core.validators import validate_email
from django import forms
from scarifmail import models

# ------------------------------------------------------------------------------
class EmailForm(forms.ModelForm):
    """
    EmailForm used for validation in views but doesn't actually create an email
    object.

    for EmailObj creation the regular process is followed where contents will be
    written to and read from a .eml file
    """
    subject = forms.CharField()
    # cc = MultiEmailField(required=False)
    # bcc = MultiEmailField(required=False)
    cc = forms.EmailField(required=False)
    bcc = forms.EmailField(required=False)

    class Meta:
        model = models.EmailObj
        fields = [
            'recipient',
            'sender',
        ]
        labels = {
            "recipient": "to",
            "sender": "from",
        }
# ------------------------------------------------------------------------------
