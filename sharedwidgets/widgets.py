from dal import autocomplete
from django import forms
from django.forms import Select


class NoRenderWidget(forms.Widget):
    @property
    def is_hidden(self):
        return True

    def render(self, name, value, attrs=None, renderer=None):
        return ""


class MarkdownWidget(forms.Textarea):
    template_name = "widgets/markdown.html"

    def __init__(self, attrs=None):
        # Use slightly better defaults than HTML's 20x2 box
        default_attrs = {"cols": "40", "rows": "10"}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    @property
    def media(self):
        return forms.Media(
            js=("https://unpkg.com/easymde/dist/easymde.min.js",),
            css={"screen": ("https://unpkg.com/easymde/dist/easymde.min.css",),},
        )


class InputAndChoiceWidget(forms.MultiWidget):
    template_name = "widgets/input_and_choice.html"

    def __init__(self, *args, **kwargs):
        myChoices = kwargs.pop("choices")
        widgets = (
            forms.Select(choices=myChoices),
            forms.TextInput(),
        )
        super(InputAndChoiceWidget, self).__init__(widgets, *args, **kwargs)

    def decompress(self, value):
        print(f"Decompress: {value}")
        return value.split("~")

    def adds_own_form_group_div(self):
        return True


class SelectWidget(Select):
    """
    Subclass of Django's select widget that allows disabling options.
    """

    def __init__(self, *args, **kwargs):
        self._disabled_choices = []
        super(SelectWidget, self).__init__(*args, **kwargs)

    @property
    def disabled_choices(self):
        return self._disabled_choices

    @disabled_choices.setter
    def disabled_choices(self, other):
        self._disabled_choices = other

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option_dict = super(SelectWidget, self).create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        if value in self.disabled_choices:
            option_dict["attrs"]["disabled"] = "disabled"
        return option_dict


class SavioAutocomplete(autocomplete.Select2QuerySetView):
    paginate_by = 100

    def get_create_option(self, context, q):
        # Stolen from the base impl in dal_select2.
        # NB: You also need to set "'data-html': True" on the widget.

        """Form the correct create_option to append to results."""
        create_option = []
        display_create_option = False
        if self.create_field and q:
            page_obj = context.get("page_obj", None)
            if page_obj is None or page_obj.number == 1:
                display_create_option = True

            # Don't offer to create a new option if a
            # case-insensitive) identical one already exists
            existing_options = (
                self.get_result_label_without_formating(result).lower()
                for result in context["object_list"]
            )
            if q.lower() in existing_options:
                display_create_option = False
        if display_create_option and self.has_add_permission(self.request):
            create_option = [
                {
                    "id": q,
                    "text": f"{self.get_create_result_label(q)}",
                    "create_id": True,
                }
            ]
        return create_option

    def get_create_result_label(self, new_value):
        return f"<strong>New: {new_value}</strong>"

    def get_result_label_without_formating(self, result):
        # If you add some fancy formating to your items
        # you should overide this b/c get_create_option()
        # uses it and it will screw up matching if the
        # result label has formating it in. E.g
        # if the result_label is "foo <br><span>theme</span>"
        # when someone type "foo" it won't match and you'll
        # be able to create dups.
        return self.get_result_label(result)
