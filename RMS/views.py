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
