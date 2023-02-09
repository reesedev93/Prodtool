from django.conf import settings
from .models import DummyData

def has_dummy_data(request):
    if not request.user.is_anonymous and request.user.customer:
        has_dummy_data = DummyData.objects.filter(customer=request.user.customer).exists()
    else:
        has_dummy_data = False
    return {'has_dummy_data': has_dummy_data}
