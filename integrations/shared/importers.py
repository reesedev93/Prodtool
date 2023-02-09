import logging
from django import forms
from appaccounts.models import FilterableAttribute

class BaseImporter(object):
    logger = logging.getLogger(__name__)

    def execute(self, all_data=False):
        raise NotImplemented()
    
    def handle_webhook(self, json, secret=None, event=None):
        raise NotImplemented()

class AttributeMapping(object):
    def __init__(self, name, attribute_type, widget, is_custom, is_mrr=False, is_plan=False):
        self.name = name
        self.attribute_type = attribute_type
        self.widget = widget
        self.is_custom = is_custom
        self.is_mrr = is_mrr
        self.is_plan = is_plan

class AttributeMapper(object):
    EXCLUSIONS = list()

    def __init__(self, customer, obj, source):
        self.customer = customer
        self.obj = obj
        self.source = source

    def create_filterable_attributes(self):
        for mapping in self.get_filterable_attribute_mappings():
            attribute, created = FilterableAttribute.objects.update_or_create(
                customer=self.customer,
                source=self.source,
                related_object_type=self.get_object_type(),
                is_custom=mapping.is_custom,
                name=mapping.name,
                attribute_type=mapping.attribute_type,
            )

            if created:
                attribute.friendly_name = forms.utils.pretty_name(mapping.name)
                attribute.widget = mapping.widget
                attribute.is_mrr = mapping.is_mrr
                attribute.is_plan = mapping.is_plan
                attribute.show_in_filters = not mapping.is_custom
                attribute.save()

    def get_exclusions(self):
        return self.EXCLUSIONS

    def get_stock_attribute_mappings(self):
        return self.STOCK_ATTRIBUTE_MAPPINGS

    def get_filterable_attribute_mappings(self):
        mappings = []
        stock_names = {}
        for mapping in self.get_stock_attribute_mappings():
            stock_names[mapping.name] = mapping.name
            mappings.append(mapping)

        for name, value in self.get_filterable_attributes_as_dict().items():
            if name in stock_names:
                continue
            attribute_type = FilterableAttribute.get_filtered_attribute_type_from_value(value)
            mapping = AttributeMapping(name, attribute_type, FilterableAttribute.WIDGET_TYPE_SELECT, True)
            mappings.append(mapping)
        return mappings

    def get_object_type(self):
        return self.OBJECT_TYPE

    def get_filterable_attributes_as_dict(self):
        raise NotImplemented