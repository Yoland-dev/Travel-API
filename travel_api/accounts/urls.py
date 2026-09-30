from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.login, name="login"),
    path("logout/", views.logout, name="logout"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("password/change/", views.change_password, name="password-change"),
    path("password/reset/", views.password_reset_request, name="password-reset"),
    path("password/reset/confirm/", views.password_reset_confirm, name="password-reset-confirm"),
    path("profile/", views.UserProfileView.as_view(), name="profile"),
]
