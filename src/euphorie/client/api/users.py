from z3c.saconfig import Session
from five import grok
from euphorie.client.authentication import authenticate
from euphorie.client.api.authentication import generate_token
from euphorie.client.survey import PathGhost
from euphorie.client.api import JsonView
from euphorie.client.model import Account
from euphorie.client.api.account import login_available
from euphorie.client.api.account import View as AccountView


def user_info(account, request):
    view = AccountView(account, request)
    return view.GET()


class Users(PathGhost):
    """Virtual container for all user data."""

    def __getitem__(self, key):
        try:
            userid = int(key)
        except ValueError:
            raise KeyError(key)

        account = Session.query(Account).get(userid)
        if account is None:
            raise KeyError(key)
        # Give an account full control over itself
#        account.__ac_local_roles__ = { account.loginname: ['Manager'] }
        account.getId = lambda: key
        return account.__of__(self)


class View(JsonView):
    grok.context(Users)
    grok.name('index_html')
    grok.require('zope2.Public')

    def POST(self):
        try:
            login = self.input['login'].strip().lower()
            if not login_available(login):
                return {'type': 'error',
                        'message': 'Loginname already in use.'}
            password = self.input.get('password', '\x00')
        except KeyError:
            return {'type': 'error',
                    'message': 'Required data missing'}

        account = Account(loginname=login, password=password)
        session = Session()
        session.add(account)
        session.flush()

        info = user_info(account, self.request)
        info['token'] = generate_token(self.context, account)
        return info


class Authenticate(JsonView):
    grok.context(Users)
    grok.name('authenticate')
    grok.require('zope2.Public')

    def POST(self):
        """Try to authenticate a user.
        """
        try:
            login = self.input['login']
            password = self.input['password']
        except (KeyError, TypeError):
            self.request.response.setStatus(403)
            return {'type': 'error',
                    'message': 'Required data missing'}

        account = authenticate(login, password)
        if account is None:
            self.request.response.setStatus(403)
            return {'type': 'error',
                    'message': 'Invalid credentials'}

        info = user_info(account, self.request)
        info['token'] = generate_token(self.context, account)
        return info
