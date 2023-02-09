from django.contrib import admin
from .models import GuideActivity

class GuideActivityAdmin(admin.ModelAdmin):
    list_search = ('user__email')
    list_display = ('guide', 'user')
    list_filter = ('customer',)

admin.site.register(GuideActivity, GuideActivityAdmin)


