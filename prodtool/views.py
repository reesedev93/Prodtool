class RequestContextMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self, 'request'):
            kwargs.update({'request': self.request})
        return kwargs

class ReturnUrlMixin(RequestContextMixin):
    def get_return_url(self):
        raise NotImplemented()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['return'] = self.get_return_url()
        return context
