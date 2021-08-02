from django.contrib import admin
from scarifmail import models
from scarifmail import forms

# Register your models here.
# class MailAcctAdmin(admin.ModelAdmin):
#     form = forms.MailAcctForm

admin.site.register(models.MailAcct)
admin.site.register(models.MailGroup)
admin.site.register(models.FilterTag)
admin.site.register(models.Filter)
# admin.site.register(models.EmailObj)
