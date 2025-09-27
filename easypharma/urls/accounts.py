from django.urls import path
from easypharma.views.accounts import (
    login_view,
    home_view,
    logout_view,
    create_user
)

urlpatterns = [
    path("", login_view, name="login"),
    path("home", home_view, name="home"),
    path('createuser', create_user, name='create_user'),
    path('logout',logout_view, name='logout'),
    
]