import time
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from mobile_api.push import dispatch_pushes


class Command(BaseCommand):
    help="Send pending generic mobile alerts after configuring Expo credentials."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")

    def handle(self, *args, **options):
        if not settings.MOBILE_PUSH_ENABLED or not settings.EXPO_ACCESS_TOKEN:
            raise CommandError("Set MOBILE_PUSH_ENABLED=True and EXPO_ACCESS_TOKEN before enabling the push worker.")
        while True:
            count=dispatch_pushes()
            self.stdout.write(f"Processed {count} push attempts.")
            if not options["watch"]:return
            time.sleep(15)
