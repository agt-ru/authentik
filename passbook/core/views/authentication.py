"""Core views"""
from logging import getLogger
from typing import Dict

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render, reverse
from django.utils.translation import ugettext as _
from django.views.generic import FormView

from passbook.core.forms.authentication import LoginForm
from passbook.core.models import User
from passbook.lib.config import CONFIG

LOGGER = getLogger(__name__)

class LoginView(UserPassesTestMixin, FormView):
    """Allow users to sign in"""

    template_name = 'login/form.html'
    form_class = LoginForm
    success_url = '.'

    # Allow only not authenticated users to login
    def test_func(self):
        return not self.request.user.is_authenticated

    def get_context_data(self, **kwargs):
        kwargs['config'] = CONFIG.get('passbook')
        kwargs['is_login'] = True
        return super().get_context_data(**kwargs)

    def get_user(self, uid_value) -> User:
        """Find user instance. Returns None if no user was found."""
        for search_field in CONFIG.y('passbook.uid_fields'):
            users = User.objects.filter(**{search_field: uid_value})
            if users.exists():
                return users.first()
        return None

    def form_valid(self, form: LoginForm) -> HttpResponse:
        """Form data is valid"""
        pre_user = self.get_user(form.cleaned_data.get('uid_field'))
        if not pre_user:
            # No user found
            return LoginView.invalid_login(self.request)
        user = authenticate(
            email=pre_user.email,
            username=pre_user.username,
            password=form.cleaned_data.get('password'),
            request=self.request)
        if user:
            # User authenticated successfully
            return LoginView.login(self.request, user, form.cleaned_data)
        # User was found but couldn't authenticate
        return LoginView.invalid_login(self.request, disabled_user=pre_user)

    @staticmethod
    def login(request: HttpRequest, user: User, cleaned_data: Dict) -> HttpResponse:
        """Handle actual login

        Actually logs user in, sets session expiry and redirects to ?next parameter

        Args:
            request: The current request
            user: The user to be logged in.

        Returns:
            Either redirect to ?next or if not present to overview
        """
        if user is None:
            raise ValueError("User cannot be None")
        login(request, user)

        if cleaned_data.get('remember') is True:
            request.session.set_expiry(CONFIG.get('passbook').get('session').get('remember_age'))
        else:
            request.session.set_expiry(0)  # Expires when browser is closed
        messages.success(request, _("Successfully logged in!"))
        LOGGER.debug("Successfully logged in %s", user.username)
        # Check if there is a next GET parameter and redirect to that
        if 'next' in request.GET:
            return redirect(request.GET.get('next'))
        # Otherwise just index
        return redirect(reverse('overview'))

    @staticmethod
    def invalid_login(request: HttpRequest, disabled_user: User = None) -> HttpResponse:
        """Handle login for disabled users/invalid login attempts"""
        if disabled_user:
            context = {
                'reason': 'disabled',
                'user': disabled_user
            }
        else:
            context = {
                'reason': 'invalid',
            }
        return render(request, 'login/invalid.html', context)
