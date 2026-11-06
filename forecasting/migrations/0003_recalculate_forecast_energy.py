from decimal import Decimal

from django.db import migrations


def recalculate_forecast_energy(apps, schema_editor):
    ForecastRun = apps.get_model("forecasting", "ForecastRun")
    ForecastPoint = apps.get_model("forecasting", "ForecastPoint")
    database = schema_editor.connection.alias

    for forecast in ForecastRun.objects.using(database).iterator():
        forecast.total_energy_kwh = sum(
            ForecastPoint.objects.using(database)
            .filter(forecast_id=forecast.pk)
            .values_list("total_power_kw", flat=True),
            Decimal("0"),
        )
        forecast.save(using=database, update_fields=["total_energy_kwh"])


class Migration(migrations.Migration):

    dependencies = [
        ("forecasting", "0002_energysite_status_and_more"),
    ]

    operations = [
        migrations.RunPython(recalculate_forecast_energy, migrations.RunPython.noop),
    ]
