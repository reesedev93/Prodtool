import csv
from datetime import date

from django.contrib import admin
from django.http import HttpResponse


class CSVExportMixin(admin.ModelAdmin):
    """
    Adds an option for CSV export to the derived model.

    Can also include evaluation results of instance methods.
    Supports dot-notation for method-object traversal.
    Special fieldname '*' will be expanded to all model fields.
    """

    export_filename_template = None  # 'yadda-yadda %s.csv'
    export_fields = (
        None  # OrderedDict({'fieldname or methodname': "Column Name" or None})
    )

    def __init__(self, *args, **kwargs):
        super(CSVExportMixin, self).__init__(*args, **kwargs)
        actions = getattr(self, "actions", list())
        actions.append("export_to_csv")

    def export_to_csv(self, request, queryset):
        export_filename_template = (
            self.export_filename_template
            or "%s List" % self.model._meta.verbose_name.title() + " %s.csv"
        )
        response = HttpResponse(content_type="text/csv")
        filename = export_filename_template % date.today()
        response["Content-Disposition"] = "attachment; filename=%s" % filename

        writer = csv.writer(response)
        export_fields = self.export_fields or dict()

        # If no fieldnames provided, just export all of them
        fieldnames_to_export = list(export_fields.keys()) or [
            f.name for f in self.model._meta.fields
        ]

        if "*" in fieldnames_to_export:  # expand asterisk to all model fields
            index = fieldnames_to_export.index("*")
            fieldnames_to_export = (
                fieldnames_to_export[:index]
                + [f.name for f in self.model._meta.fields]
                + fieldnames_to_export[index + 1 :]
            )

        # If no verbose name for column provided, use prettified field/method name
        columns = [
            export_fields.get(f, None) or f.replace("_", " ").title()
            for f in fieldnames_to_export
        ]
        writer.writerow(columns)

        for instance in queryset:
            row = list()
            for fname in fieldnames_to_export:
                obj = instance
                path = fname.split(".")
                try:
                    for (
                        attr
                    ) in (
                        path
                    ):  # advance through attribute chain calling methods on the way
                        obj = getattr(obj, attr)
                        if callable(obj):  # looks like a method
                            obj = obj()  # call it to get a value

                    row.append(str(obj))
                except Exception:
                    row.append("")
            writer.writerow(row)

        return response

    export_to_csv.short_description = "Export records to CSV"
