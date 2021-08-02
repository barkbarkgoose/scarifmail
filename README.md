# scarifmail
POP3 email models and process to be used in django projects

all the models inside of models.py are self contained and this directory can be copied into an existing django project as a new app.

# usage
in order to make this work first add a mail account inside of django admin.  As of 08/2021 this is only set up for POP3 and is intended to work along side any other mail clients (it stores and tracks files locally).

Once a mail account is added to the db you can call the main process with controller.main() which takes a single mail account instance as an optional parameter, if no parameters are given all accounts that are currently active will be processed.

# To Do
I started creating groups to separate user permissions, that is a work in progress and should not be used as is.
