import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "renewables.settings")

application = get_wsgi_application()

# On Vercel without DATABASE_URL, the SQLite file in /tmp starts empty on every
# cold start, so create the tables before serving requests.
if os.environ.get("VERCEL") == "1" and not os.environ.get("DATABASE_URL"):
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)
