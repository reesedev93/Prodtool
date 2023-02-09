from django import forms
from .widgets import InputAndChoiceWidget

class InputAndChoiceField(forms.MultiValueField):
    # widget = InputAndChoiceWidget

    def __init__(self,*args,**kwargs):
        # you could also use some fn to return the choices;
        # the point is, they get set dynamically 
        myChoices = kwargs.pop("choices",[("default","default choice")])
        fields = (
            forms.ChoiceField(choices=myChoices),
            forms.CharField(),
        )
        super(InputAndChoiceField,self).__init__(fields, *args, **kwargs)
        # here's where the choices get set:
        self.widget = InputAndChoiceWidget(choices=myChoices)

    def compress(self, data_list):
        print(f"Compress: {data_list}")
        return "~".join(data_list)
