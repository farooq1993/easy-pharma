from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from easypharma.models import User
from django.contrib import messages
# Create your views here.


def home_view(request):
    return render(request, "home.html")

def create_user(request):
    if request.method =='POST':
        username = request.POST.get('username')
        user_type = request.POST.get('user_type')
        password = request.POST.get('password')

        user = User.objects.create(username=username, user_type=user_type, password=password)
        messages.success(request, 'User has created successfully!')
        return redirect('/createuser')
    return render(request, 'accounts/createuser.html')

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("home")
        else:
            return render(request, "accounts/login.html")
    return render(request, "accounts/login.html")

def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
        return redirect('login')
