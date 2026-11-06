from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class EnergySite(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        MAINTENANCE = "maintenance", "Maintenance"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="energy_sites",
    )
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=160)
    latitude = models.DecimalField(
        max_digits=8,
        decimal_places=5,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=8,
        decimal_places=5,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    wind_capacity_kw = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    solar_capacity_kw = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    system_loss_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=14,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def total_capacity_kw(self):
        return self.wind_capacity_kw + self.solar_capacity_kw


class ForecastRun(models.Model):
    site = models.ForeignKey(
        EnergySite,
        on_delete=models.CASCADE,
        related_name="forecasts",
    )
    horizon_hours = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    total_energy_kwh = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.site.name} forecast ({self.created_at:%Y-%m-%d %H:%M})"


class ForecastPoint(models.Model):
    forecast = models.ForeignKey(
        ForecastRun,
        on_delete=models.CASCADE,
        related_name="points",
    )
    timestamp = models.DateTimeField()
    temperature_c = models.DecimalField(max_digits=6, decimal_places=2)
    wind_speed_ms = models.DecimalField(max_digits=6, decimal_places=2)
    wind_direction_deg = models.DecimalField(max_digits=6, decimal_places=2)
    relative_humidity_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    cloud_cover_percent = models.PositiveSmallIntegerField()
    precipitation_probability_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    irradiance_wm2 = models.DecimalField(max_digits=8, decimal_places=2)
    sunrise = models.DateTimeField(null=True, blank=True)
    sunset = models.DateTimeField(null=True, blank=True)
    wind_power_kw = models.DecimalField(max_digits=10, decimal_places=2)
    solar_power_kw = models.DecimalField(max_digits=10, decimal_places=2)
    total_power_kw = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["timestamp"]
        constraints = [
            models.UniqueConstraint(
                fields=["forecast", "timestamp"],
                name="unique_forecast_timestamp",
            )
        ]
