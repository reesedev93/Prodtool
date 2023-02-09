from django.db import models
from accounts.models import Customer, User

class GuideActivity(models.Model):
    LOAD_FEEDBACK = 'LOAD_FEEDBACK'

    GUIDE_KEYS = (
        LOAD_FEEDBACK,
    )
    GUIDE_CHOICES = (
        (LOAD_FEEDBACK, 'Load feedback'),
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    guide = models.CharField(choices=GUIDE_CHOICES, max_length=30)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        unique_together = (("customer", "user", "guide"),)
