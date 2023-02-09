from django.contrib import admin
from .models import AppCompany, AppUser, FilterableAttribute

class FilterableAttributeAdmin(admin.ModelAdmin):
    list_display = ('name', 'source', 'customer', 'related_object_type', 'attribute_type', 'is_custom', 'show_in_filters')
    list_filter = ('customer', 'source')

class AppCompanyAdmin(admin.ModelAdmin):
    search_fields = ('name',)
    list_display = ('name', 'remote_id')
    list_filter = ('customer',)

class AppUserAdmin(admin.ModelAdmin):
    search_fields = ('name', 'email',)
    list_display = ('name', 'email', 'remote_id', 'company', 'plan', 'monthly_spend')
    list_display_links = ('name', 'email')
    list_filter = ('customer',)
    autocomplete_fields = ('company',)

    def plan(self, obj):
             return obj.company.plan if obj.company and obj.company.plan else '-'

    def monthly_spend(self, obj):
             return obj.company.monthly_spend if obj.company and obj.company.monthly_spend else '-'

    def get_queryset(self, request):
        return super(AppUserAdmin,self).get_queryset(request).select_related('company')

admin.site.register(AppCompany, AppCompanyAdmin)
admin.site.register(AppUser, AppUserAdmin)
admin.site.register(FilterableAttribute, FilterableAttributeAdmin)
