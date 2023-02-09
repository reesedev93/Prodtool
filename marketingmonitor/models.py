from django.db import models


class Source(models.Model):
    name = models.CharField(max_length=255)
    last_checked = models.IntegerField()

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    def __str__(self):
        return self.last_checked
