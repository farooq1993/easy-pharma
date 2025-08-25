from django.urls import path
from .views import home_view, login_view,logout_view

urlpatterns = [
    path("", login_view, name="login"),
    path("home", home_view, name="home"),
    path('logout',logout_view, name='logout')
    
]