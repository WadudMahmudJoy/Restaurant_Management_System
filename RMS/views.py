from .models import Order, Waiter, Chef

from django.contrib.auth.decorators import login_required

@login_required
def order_management(request):
	orders = Order.objects.all().order_by('-created_at')
	return render(request, 'RMS/order_management.html', {'orders': orders})
def super_admin_login(request):
	error = None
	if request.method == 'POST':
		username = request.POST.get('username')
		password = request.POST.get('password')
		user = authenticate(request, username=username, password=password)
		if user is not None and user.is_superuser and user.username == 'Bithi':
			login(request, user)
			return redirect('super_admin_dashboard')
		else:
			error = 'Invalid super admin credentials or not Bithi.'
	return render(request, 'RMS/admin_login.html', {'error': error, 'super_admin': True})
from .models import Food
from django.shortcuts import render, redirect
def user_home(request):
	categories = [
		'Breakfast', 'Lunch', 'Dinner', 'Snack', 'Fastfood', 'Juice & Drinks'
	]
	foods_by_category = {cat: Food.objects.filter(category=cat, stock__gt=0) for cat in categories}
	message = None
	if request.method == 'POST':
		food_id = request.POST.get('food_id')
		quantity = int(request.POST.get('quantity', 1))
		customer_name = request.POST.get('customer_name', 'Guest')
		food = Food.objects.get(id=food_id)
		if food.stock >= quantity:
			# Create order
			from .models import Order
			order = Order.objects.create(
				customer_name=customer_name,
				food_items=f"{food.name} x {quantity}",
				status='Pending'
			)
			# Reduce stock
			food.stock -= quantity
			food.save()
			message = f"Order placed for {food.name} x {quantity}!"
		else:
			message = f"Not enough stock for {food.name}."
	return render(request, 'RMS/user_home.html', {'foods_by_category': foods_by_category, 'message': message})
from django.contrib.auth.decorators import login_required
@login_required
def super_admin_dashboard(request):
	from django.contrib.auth.models import User
	is_super_admin = request.user.is_superuser and request.user.username == 'Bithi'
	admins = None
	message = None
	if is_super_admin:
		admins = User.objects.filter(is_staff=True, is_superuser=False)
		if request.method == 'POST' and 'add_admin' in request.POST:
			new_admin_username = request.POST.get('new_admin_username')
			new_admin_password = request.POST.get('new_admin_password')
			if User.objects.filter(username=new_admin_username).exists():
				message = 'Admin username already exists.'
			else:
				new_admin = User.objects.create_user(username=new_admin_username, password=new_admin_password)
				new_admin.is_staff = True
				new_admin.save()
				message = 'Admin added successfully!'
		if request.method == 'POST' and 'delete_admin' in request.POST:
			del_username = request.POST.get('delete_admin')
			User.objects.filter(username=del_username, is_staff=True, is_superuser=False).delete()
			message = f'Admin {del_username} deleted.'
		admins = User.objects.filter(is_staff=True, is_superuser=False)
	else:
		return render(request, 'RMS/super_admin_dashboard.html', {'is_super_admin': False, 'admins': None})
	return render(request, 'RMS/super_admin_dashboard.html', {
		'is_super_admin': is_super_admin,
		'admins': admins,
		'message': message
	})
def admin_dashboard(request):
	# Placeholder for normal admin dashboard
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