# -*- coding: utf-8 -*-
from django.db.models import F
from django.http import QueryDict

ORDER_VAR = 'o'
ORDER_TYPE_VAR = 'ot'

class SortHeaders:
    """
    Handles generation of an argument for the Django ORM's
    ``order_by`` method and generation of table headers which reflect
    the currently selected sort, based on defined table headers with
    matching sort criteria.

    Based in part on the Django Admin application's ``ChangeList``
    functionality.
    """
    def __init__(self, request, headers, default_order_field=None,
            default_order_type='asc'):
        """
        request
            The request currently being processed - the current sort
            order field and type are determined based on GET
            parameters.

        headers
            A list of three-tuples of header text, matching ordering
            criteria for use with the Django ORM's ``order_by``
            method. A criterion of ``None`` indicates that a header
            is not sortable. And a dictionary of extra attributes
            to dump out on the ``<th>`` tag to add in tweaking
            formating on a per column basis.

        default_order_field
            The index of the header definition to be used for default
            ordering and when an invalid or non-sortable header is
            specified in GET parameters. If not specified, the index
            of the first sortable header will be used.

        default_order_type
            The default type of ordering used - must be one of
            ``'asc`` or ``'desc'``.

        """
        if default_order_field is None:
            for i, (header, query_lookup) in enumerate(headers):
                if query_lookup is not None:
                    default_order_field = i
                    break
        if default_order_field is None:
            raise AttributeError('No default_order_field was specified and none of the header definitions given were sortable.')
        if default_order_type not in ('asc', 'desc'):
            raise AttributeError('If given, default_order_type must be one of \'asc\' or \'desc\'.')
        # self.query_dict = QueryDict('')
        self.query_dict = request.GET.copy()

        self.header_defs = headers
        self.order_field, self.order_type = default_order_field, default_order_type

        # Determine order field and order type for the current request
        params = dict(request.GET.items())
        if ORDER_VAR in params:
            try:
                new_order_field = int(params[ORDER_VAR])
                if headers[new_order_field][1] is not None:
                    self.order_field = new_order_field
            except (IndexError, ValueError):
                pass # Use the default
        if ORDER_TYPE_VAR in params and params[ORDER_TYPE_VAR] in ('asc', 'desc'):
            self.order_type = params[ORDER_TYPE_VAR]

    def headers(self):
        """
        Generates dicts containing header and sort link details for
        all defined headers.
        """
        for i, (header, order_criterion, attrs) in enumerate(self.header_defs):
            sorting_classes = []
            new_order_type = 'asc'

            if order_criterion:
                sorting_classes.append('fas fa-lg')

            if i == self.order_field:
                sorting_classes.append({'asc': 'fa-sort-up', 'desc': 'fa-sort-down'}[self.order_type])
                new_order_type = {'asc': 'desc', 'desc': 'asc'}[self.order_type]
            #else:
            #    sorting_classes.append('fa-sort')

            yield {
                'text': header,
                'sortable': order_criterion is not None,
                'url': self.get_query_string({ORDER_VAR: i, ORDER_TYPE_VAR: new_order_type}),
                'sorting_classes': " ".join(sorting_classes),
                'attrs': attrs,
            }

    def get_query_string(self, params):
        """
        Creates a query string from the given dictionary of
        parameters.
        """
        query_dict = self.query_dict.copy()
        for param, value in params.items():
            query_dict[param]  = value
        return "?%s" % query_dict.urlencode()


    def get_order_by(self):
        """
        Creates an ordering criterion based on the current order
        field and order type, for use with the Django ORM's
        ``order_by`` method.
        """
        return '%s%s' % (
            self.order_type == 'desc' and '-' or '',
            self.get_order_by_field_name(),
        )

    def get_order_by_expression(self):
        """
        Creates an ordering criterion F EXPRESION based on the current order
        field and order type, for use with the Django ORM's
        ``order_by`` method.

        This fanciness let's us sort NULLs in the right way.
        """
        order_by_expression = F(self.get_order_by_field_name())
        if self.order_type == 'desc':
            order_by_expression = order_by_expression.desc(nulls_last=True)
        else:
            order_by_expression = order_by_expression.asc(nulls_first=True)
        return order_by_expression

    def get_order_by_field_name(self):
        """
        Gets the name of the field we should be ordering on.
        """
        return self.header_defs[self.order_field][1]

    def get_order_by_for_list(self):
        """
        Creates an ordering criterion based on the current order
        field and order type, for use with the sorted method for lists.
        """
        return (self.order_type == 'desc', self.header_defs[self.order_field][1],)
