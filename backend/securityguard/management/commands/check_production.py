from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from securityguard.production import configuration_errors


class Command(BaseCommand):
    help = "Reject unsafe production configuration; never prints secret values."

    def handle(self, *args, **options):
        failures = configuration_errors(settings)
        if not settings.PRODUCTION_MODE:
            failures.append("DJANGO_PRODUCTION must be True")
        if failures:
            raise CommandError("Production configuration rejected:\n- " + "\n- ".join(failures))
        call_command("check", deploy=True, fail_level="WARNING")
        self.stdout.write(self.style.SUCCESS("Production configuration checks passed. Runtime, backup and access checks are still required."))
