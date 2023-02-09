from django.forms import model_to_dict

class InitialsMixin(object):
    """
    Saves all initial model field values in '._initial' dictionary.

    Useful for doing comparison checks later (for example: in .save())

    NB: This only handles simple cases. If you need fancy stuff like
    support for m2m (which may not work with this?) or refreshing
    you might want to use something else. On the plus side this
    is super simple, easy to understand has minimal perf impact
    and is unlikely to have upgrade issues.

    If you are looking for alternatives take a look at:
    https://stackoverflow.com/questions/1355150/django-when-saving-how-can-you-check-if-a-field-has-changed
    https://github.com/romgar/django-dirtyfields
    https://github.com/jazzband/django-model-utils/blob/master/model_utils/tracker.py
    """
    def __init__(self, *args, **kwargs):
        super(InitialsMixin, self).__init__(*args, **kwargs)
        self._initials = model_to_dict(self)

    def changed_fields(self):
        """Returns list of the field names that changed since instantiation."""
        diff = list()
        current = model_to_dict(self)
        for name in self._initials.keys():
            if current[name] != self._initials[name]:
                diff.append(name)

        return diff
