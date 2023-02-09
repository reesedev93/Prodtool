from django.core.management.base import BaseCommand, CommandError
from feedback.models import CustomerFeedbackImporterSettings

class Command(BaseCommand):
    help = 'Imports feedback from the specified source system'

    def add_arguments(self, parser):
        parser.add_argument('customer_names', nargs='?', type=str)
        parser.add_argument('--importers', dest='importers', action='store')
        parser.add_argument('--all-data', dest='all_data', action='store_true', default=False)

    def handle(self, *args, **options):
        if options['customer_names']:
            customer_names = options['customer_names'].split(",")
            cfis_for_customers = CustomerFeedbackImporterSettings.objects.filter(
                customer__name__in=customer_names)
        else:
            cfis_for_customers = CustomerFeedbackImporterSettings.objects.all()
        for cfis in cfis_for_customers:
            if self.wanted_importer(cfis.importer.name, options['importers']):
                try:
                    cfis.do_import(all_data=options['all_data'])
                except Exception as e:
                    print(f"ERROR: failed to import {cfis.customer.name}: {e}")
                    raise
            else:
                print(f"Skipping {cfis.importer.name} for {cfis.customer.name}")

    def wanted_importer(self, importer_name, wanted_importer_names):
        if wanted_importer_names:
            wanted = importer_name in wanted_importer_names.split(',')
            return wanted
        else:
            return True