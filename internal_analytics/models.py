from django.contrib.postgres.fields import JSONField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

class Event(models.Model):
    # This field isn't very thoughtfully indexed but it will likely
    # need to be. Indexing a jsonb field is a little tricky. I think we need
    # to do two things:
    # 1. Create a GIN index for this field (done - but maybe there is more to do?)
    # 2. Have the index support jsonb_path_ops.
    # See:
    # - https://stackoverflow.com/questions/26499266/whats-the-proper-index-for-querying-structures-in-arrays-in-postgres-jsonb/27708358#27708358
    # - https://vxlabs.com/2018/01/31/creating-a-django-migration-for-a-gist-gin-index-with-a-special-index-operator/

    data = JSONField()

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        indexes = [
            GinIndex(
                fields=['data'],
                name='data_gin',
            ),
        ]