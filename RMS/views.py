from django.contrib.auth.models import User
def admin_register(request):
	error = None
	success = None
	if request.method == 'POST':
		superuser_username = request.POST.get('superuser_username')
		superuser_password = request.POST.get('superuser_password')
		new_admin_username = request.POST.get('new_admin_username')
		new_admin_password = request.POST.get('new_admin_password')
		superuser = authenticate(request, username=superuser_username, password=superuser_password)
		if superuser is not None and superuser.is_superuser:
			if User.objects.filter(username=new_admin_username).exists():
				error = 'Admin username already exists.'
			else:
				new_admin = User.objects.create_user(username=new_admin_username, password=new_admin_password)
				new_admin.is_staff = True
				new_admin.save()
				success = 'Admin registered successfully!'
		else:
			error = 'Invalid superuser credentials.'
	return render(request, 'RMS/admin_register.html', {'error': error, 'success': success})
def user_home(request):
	return render(request, 'RMS/homepage.html')  # Placeholder, can be updated later
from django.contrib.auth.decorators import login_required, user_passes_test
@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_dashboard(request):
	return render(request, 'RMS/admin_dashboard.html')
from django.contrib.auth import authenticate, login
from django.shortcuts import redirect
def admin_login(request):
	error = None
	if request.method == 'POST':
		username = request.POST.get('username')
		password = request.POST.get('password')
		user = authenticate(request, username=username, password=password)
		if user is not None and user.is_staff:
			login(request, user)
			return redirect('admin_dashboard')
		else:
			error = 'Invalid credentials or not an admin.'
	return render(request, 'RMS/admin_login.html', {'error': error})

from django.shortcuts import render

def homepage(request):
	return render(request, 'RMS/homepage.html')