from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render
from django.shortcuts import redirect
from django.urls import reverse_lazy
from accounts.decorators import role_required
from accounts.models import User
from .models import DummyData

@role_required(User.ROLE_OWNER_OR_ADMIN)
def delete(request):
    if request.method == 'POST':
        DummyData.objects.delete_data(request.user.customer)
        messages.success(request, f"Sample data deleted.")
        feedback_inbox_url = reverse_lazy('feedback-inbox-list', kwargs={'state': 'active'})
        return_url = request.GET.get('return', feedback_inbox_url)
        return redirect(return_url)
    return HttpResponse("Only POST accepted", status=400)

@role_required(User.ROLE_OWNER_OR_ADMIN)
def create(request):
    if request.method == 'POST':
        DummyData.objects.load_data(request.user.customer)
        messages.success(request, f"Sample data created.")
        feedback_inbox_url = reverse_lazy('feedback-inbox-list', kwargs={'state': 'active'})
        return_url = request.GET.get('return', feedback_inbox_url)
        return redirect(return_url)
    else:
        return render(request, 'create_dummy_data.html')
    return HttpResponse("Only POST accepted", status=400)