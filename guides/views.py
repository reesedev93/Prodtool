from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from accounts.models import User
from accounts.decorators import role_required
from .models import GuideActivity

@csrf_exempt
@role_required(User.ROLE_ANY)
def dismiss_for_user(request):
    data = dict()

    guide = request.POST.get('guide')
    if request.method == 'POST':
        activity, created = GuideActivity.objects.get_or_create(
            customer=request.user.customer,
            user=request.user,
            guide=guide,
        )
        data = {'success': True}
    else:
        data = {'success': False}

    return JsonResponse(data)
