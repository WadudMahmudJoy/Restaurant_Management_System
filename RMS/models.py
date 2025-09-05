
from django.db import models
from django.contrib.auth.models import User

class Food(models.Model):
	CATEGORY_CHOICES = [
		('Breakfast', 'Breakfast'),
		('Lunch', 'Lunch'),
		('Dinner', 'Dinner'),
		('Snack', 'Snack'),
		('Fastfood', 'Fastfood'),
		('Juice & Drinks', 'Juice & Drinks'),
	]
	name = models.CharField(max_length=100)
	category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
	stock = models.PositiveIntegerField(default=0)
	def __str__(self):
		return f"{self.name} ({self.category})"

class Waiter(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE)
	name = models.CharField(max_length=100)
	def __str__(self):
		return self.name

class Chef(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE)
	name = models.CharField(max_length=100)
	def __str__(self):
		return self.name

class Order(models.Model):
	FOOD_STATUS = [
		('Pending', 'Pending'),
		('Preparing', 'Preparing'),
		('Ready', 'Ready'),
		('Served', 'Served'),
	]
	customer_name = models.CharField(max_length=100)
	food_items = models.TextField()
	status = models.CharField(max_length=20, choices=FOOD_STATUS, default='Pending')
	assigned_waiter = models.ForeignKey(Waiter, on_delete=models.SET_NULL, null=True, blank=True)
	assigned_chef = models.ForeignKey(Chef, on_delete=models.SET_NULL, null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	def __str__(self):
		return f"Order #{self.id} - {self.customer_name}"
