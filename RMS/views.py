
from django.shortcuts import render

def homepage(request):
	return render(request, 'RMS/homepage.html')
