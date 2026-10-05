from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from notifications.services import (
    create_upcoming_appointment_reminders,
)


class Command(BaseCommand):
    help = "Create reminders for upcoming confirmed appointments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Reminder window in hours. Default: 24.",
        )

    def handle(self, *args, **options):
        hours = options["hours"]

        if hours <= 0:
            raise CommandError(
                "--hours must be greater than zero."
            )

        created_count = create_upcoming_appointment_reminders(
            now=timezone.now(),
            window=timedelta(hours=hours),
        )

        suffix = "" if created_count == 1 else "s"

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created_count} appointment "
                f"reminder{suffix}."
            )
        )
