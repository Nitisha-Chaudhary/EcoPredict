import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import EnergySite, ForecastPoint, ForecastRun
from .services import (
    WeatherServiceError,
    calculate_solar_power,
    calculate_wind_power,
    get_hourly_weather,
)


class PowerModelTests(TestCase):
    def test_wind_power_respects_cut_in_rated_and_cut_out_speeds(self):
        capacity = Decimal("100")
        self.assertEqual(calculate_wind_power(2.9, capacity), 0)
        self.assertEqual(calculate_wind_power(12, capacity), capacity)
        self.assertEqual(calculate_wind_power(25, capacity), 0)
        self.assertGreater(calculate_wind_power(8, capacity), 0)
        self.assertLess(calculate_wind_power(8, capacity), capacity)

    def test_solar_power_applies_radiation_capacity_and_losses(self):
        output = calculate_solar_power(1000, 25, 100, 10)
        self.assertEqual(output, Decimal("90.0"))
        self.assertEqual(calculate_solar_power(0, 25, 100, 0), 0)


class WeatherServiceTests(TestCase):
    @patch("forecasting.services.urlopen")
    def test_parses_hourly_weather_response(self, mocked_urlopen):
        payload = {
            "hourly": {
                "time": ["2026-01-01T00:00", "2026-01-01T01:00"],
                "temperature_2m": [12, 11],
                "wind_speed_10m": [5, 6],
                "wind_direction_10m": [90, 100],
                "relative_humidity_2m": [70, 72],
                "cloud_cover": [10, 20],
                "precipitation_probability": [5, 10],
                "shortwave_radiation": [0, 100],
            },
            "daily": {
                "time": ["2026-01-01"],
                "sunrise": ["2026-01-01T06:00"],
                "sunset": ["2026-01-01T18:00"],
            },
        }
        response = mocked_urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps(payload).encode()

        points = get_hourly_weather(10, 20, 2)

        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["timestamp"], datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(points[1]["irradiance_wm2"], Decimal("100"))
        self.assertEqual(points[1]["relative_humidity_percent"], 72)
        self.assertEqual(points[0]["sunrise"], datetime(2026, 1, 1, 6, tzinfo=timezone.utc))

    @patch("forecasting.services.urlopen")
    def test_rejects_incomplete_hourly_response(self, mocked_urlopen):
        response = mocked_urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps({"hourly": {"time": []}}).encode()
        with self.assertRaises(WeatherServiceError):
            get_hourly_weather(10, 20, 24)

    @patch("forecasting.services.urlopen")
    def test_rejects_non_object_response(self, mocked_urlopen):
        response = mocked_urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps([]).encode()
        with self.assertRaises(WeatherServiceError):
            get_hourly_weather(10, 20, 24)


class ForecastViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="valid-password-123")
        self.site = EnergySite.objects.create(
            owner=self.user,
            name="Coastal test site",
            location="Coast",
            latitude=Decimal("10"),
            longitude=Decimal("20"),
            wind_capacity_kw=Decimal("50"),
            solar_capacity_kw=Decimal("100"),
        )

    def test_dashboard_requires_login_and_displays_owned_site(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Coastal test site")

    def test_user_cannot_access_another_users_site(self):
        other_user = User.objects.create_user(username="other", password="valid-password-123")
        other_site = EnergySite.objects.create(
            owner=other_user,
            name="Private site",
            location="Elsewhere",
            latitude=0,
            longitude=0,
            wind_capacity_kw=10,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("site_detail", args=[other_site.pk]))
        self.assertEqual(response.status_code, 404)

    def test_site_form_and_forecast_history_pages_render(self):
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(reverse("site_edit", args=[self.site.pk])).status_code,
            200,
        )
        forecast = ForecastRun.objects.create(
            site=self.site,
            horizon_hours=24,
            total_energy_kwh=Decimal("10"),
        )
        ForecastPoint.objects.create(
            forecast=forecast,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            temperature_c=20,
            wind_speed_ms=5,
            wind_direction_deg=90,
            cloud_cover_percent=10,
            irradiance_wm2=100,
            wind_power_kw=5,
            solar_power_kw=8,
            total_power_kw=13,
        )
        response = self.client.get(reverse("forecast_detail", args=[forecast.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hourly breakdown")
        self.assertContains(response, "13.00 kW")

    def test_site_can_be_created_and_deleted(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("site_create"),
            {
                "name": "Inland array",
                "location": "Central region",
                "latitude": "35.12345",
                "longitude": "-117.12345",
                "wind_capacity_kw": "0",
                "solar_capacity_kw": "25.5",
                "system_loss_percent": "14",
                "status": "active",
            },
        )
        site = EnergySite.objects.get(name="Inland array")
        self.assertRedirects(response, reverse("site_detail", args=[site.pk]))

        response = self.client.post(reverse("site_delete", args=[site.pk]))
        self.assertRedirects(response, reverse("site_list"))
        self.assertFalse(EnergySite.objects.filter(pk=site.pk).exists())

    def test_signup_creates_and_authenticates_user(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "newmember",
                "email": "newmember@example.com",
                "password1": "Rainy-Day-Power-528!",
                "password2": "Rainy-Day-Power-528!",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(User.objects.filter(username="newmember").exists())

    def test_dashboard_shows_saved_forecast_and_weather_analytics(self):
        forecast = ForecastRun.objects.create(
            site=self.site,
            horizon_hours=24,
            total_energy_kwh=Decimal("13"),
        )
        ForecastPoint.objects.create(
            forecast=forecast,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            temperature_c=20,
            wind_speed_ms=5,
            wind_direction_deg=90,
            cloud_cover_percent=10,
            irradiance_wm2=100,
            wind_power_kw=5,
            solar_power_kw=8,
            total_power_kw=13,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wind, solar &amp; combined generation")
        self.assertContains(response, "5.0")
        self.assertContains(response, "100")
        self.assertContains(response, "Requires measured output for validation")
        self.assertEqual(response.context["wind_forecast_energy"], Decimal("5"))
        self.assertEqual(response.context["solar_forecast_energy"], Decimal("8"))
        self.assertEqual(
            sum(response.context["total_data"]),
            float(response.context["total_forecast_energy"]),
        )

    def test_dashboard_24_hour_chart_spans_midnight_and_matches_energy_kpi(self):
        forecast = ForecastRun.objects.create(site=self.site, horizon_hours=24)
        for timestamp, total in (
            (datetime(2026, 1, 1, 23, tzinfo=timezone.utc), Decimal("6")),
            (datetime(2026, 1, 2, 0, tzinfo=timezone.utc), Decimal("9")),
        ):
            ForecastPoint.objects.create(
                forecast=forecast,
                timestamp=timestamp,
                temperature_c=20,
                wind_speed_ms=5,
                wind_direction_deg=90,
                cloud_cover_percent=10,
                irradiance_wm2=100,
                wind_power_kw=total,
                solar_power_kw=0,
                total_power_kw=total,
            )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dashboard"),
            {"period": "24h", "date": "2026-01-01"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["chart_hour_count"], 2)
        self.assertEqual(response.context["chart_labels"], ["23:00", "00:00"])
        self.assertEqual(response.context["total_forecast_energy"], Decimal("15.0"))
        self.assertEqual(
            sum(response.context["total_data"]),
            float(response.context["total_forecast_energy"]),
        )

    def test_site_search_and_capacity_sort_only_show_owned_sites(self):
        larger_site = EnergySite.objects.create(
            owner=self.user,
            name="Large solar site",
            location="Inland",
            latitude=10,
            longitude=20,
            wind_capacity_kw=0,
            solar_capacity_kw=500,
            status=EnergySite.Status.MAINTENANCE,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("site_list"), {"location": "inland"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, larger_site.name)
        self.assertNotContains(response, self.site.name)

        response = self.client.get(reverse("site_list"), {"sort": "capacity"})

        self.assertEqual(response.context["sites"][0], larger_site)

    def test_forecast_history_filters_and_delete_are_user_scoped(self):
        forecast = ForecastRun.objects.create(
            site=self.site,
            horizon_hours=24,
            total_energy_kwh=Decimal("10"),
        )
        ForecastPoint.objects.create(
            forecast=forecast,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            temperature_c=20,
            wind_speed_ms=5,
            wind_direction_deg=90,
            cloud_cover_percent=10,
            irradiance_wm2=100,
            wind_power_kw=5,
            solar_power_kw=8,
            total_power_kw=13,
        )
        other_user = User.objects.create_user(
            username="other",
            password="another-test-password",
        )
        other_site = EnergySite.objects.create(
            owner=other_user,
            name="Private site",
            location="Elsewhere",
            latitude=0,
            longitude=0,
            wind_capacity_kw=10,
        )
        private_forecast = ForecastRun.objects.create(site=other_site, horizon_hours=24)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("forecast_list"),
            {"site": "Coastal", "technology": "combined", "horizon": "24"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["forecasts"]), [forecast])
        self.assertNotContains(response, "Private site")

        response = self.client.post(reverse("forecast_delete", args=[private_forecast.pk]))
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse("forecast_delete", args=[forecast.pk]))
        self.assertRedirects(response, reverse("forecast_list"))
        self.assertFalse(ForecastRun.objects.filter(pk=forecast.pk).exists())
        self.assertTrue(ForecastRun.objects.filter(pk=private_forecast.pk).exists())

    def test_analytics_and_csv_report_include_only_owned_forecast_data(self):
        forecast = ForecastRun.objects.create(
            site=self.site,
            horizon_hours=24,
            total_energy_kwh=Decimal("13"),
        )
        ForecastPoint.objects.create(
            forecast=forecast,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            temperature_c=20,
            wind_speed_ms=5,
            wind_direction_deg=90,
            cloud_cover_percent=10,
            irradiance_wm2=100,
            wind_power_kw=5,
            solar_power_kw=8,
            total_power_kw=13,
        )
        other_user = User.objects.create_user(username="other", password="test-password")
        other_site = EnergySite.objects.create(
            owner=other_user,
            name="Other user's private site",
            location="Elsewhere",
            latitude=0,
            longitude=0,
            wind_capacity_kw=10,
        )
        ForecastRun.objects.create(site=other_site, horizon_hours=24)
        self.client.force_login(self.user)

        analytics_response = self.client.get(reverse("analytics"))
        report_response = self.client.get(reverse("report_csv"))

        self.assertEqual(analytics_response.status_code, 200)
        self.assertContains(analytics_response, "Coastal test site")
        self.assertEqual(report_response.status_code, 200)
        self.assertEqual(report_response["Content-Type"], "text/csv; charset=utf-8")
        self.assertContains(report_response, "Solar irradiance (W/m2)")
        self.assertContains(report_response, "Coastal test site")
        self.assertNotContains(report_response, "Other user's private site")

    @patch("forecasting.views.get_hourly_weather")
    def test_creates_and_saves_hourly_forecast(self, mocked_weather):
        mocked_weather.return_value = [
            {
                "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "temperature_c": Decimal("25"),
                "wind_speed_ms": Decimal("12"),
                "wind_direction_deg": Decimal("90"),
                "relative_humidity_percent": 60,
                "cloud_cover_percent": 0,
                "precipitation_probability_percent": 5,
                "irradiance_wm2": Decimal("500"),
                "sunrise": datetime(2026, 1, 1, 6, tzinfo=timezone.utc),
                "sunset": datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
            }
        ]
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("forecast_create", args=[self.site.pk]),
            {"horizon_hours": "24"},
        )

        forecast = ForecastRun.objects.get(site=self.site)
        self.assertRedirects(response, reverse("forecast_detail", args=[forecast.pk]))
        point = ForecastPoint.objects.get(forecast=forecast)
        self.assertEqual(point.wind_power_kw, Decimal("50.00"))
        self.assertEqual(point.solar_power_kw, Decimal("43.00"))
        self.assertEqual(point.relative_humidity_percent, 60)
        self.assertEqual(point.precipitation_probability_percent, 5)
        self.assertEqual(point.sunrise, datetime(2026, 1, 1, 6, tzinfo=timezone.utc))
        self.assertEqual(forecast.total_energy_kwh, Decimal("93.00"))

    @patch("forecasting.views.get_hourly_weather")
    def test_run_total_matches_rounded_persisted_hourly_outputs(self, mocked_weather):
        site = EnergySite.objects.create(
            owner=self.user,
            name="Small wind test",
            location="Test",
            latitude=0,
            longitude=0,
            wind_capacity_kw=Decimal("0.30"),
        )
        mocked_weather.return_value = [
            {
                "timestamp": datetime(2026, 1, 1, hour, tzinfo=timezone.utc),
                "temperature_c": Decimal("25"),
                "wind_speed_ms": Decimal("4"),
                "wind_direction_deg": Decimal("90"),
                "cloud_cover_percent": 0,
                "irradiance_wm2": Decimal("0"),
            }
            for hour in (0, 1)
        ]
        self.client.force_login(self.user)

        self.client.post(
            reverse("forecast_create", args=[site.pk]),
            {"horizon_hours": "24"},
        )

        forecast = ForecastRun.objects.get(site=site)
        persisted_total = sum(
            forecast.points.values_list("total_power_kw", flat=True),
            Decimal("0"),
        )
        self.assertEqual(forecast.total_energy_kwh, persisted_total)
        self.assertEqual(forecast.total_energy_kwh, Decimal("0.02"))

    @patch("forecasting.views.get_hourly_weather")
    def test_weather_failure_is_reported_without_creating_forecast(self, mocked_weather):
        mocked_weather.side_effect = WeatherServiceError("Weather unavailable.")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("forecast_create", args=[self.site.pk]),
            {"horizon_hours": "24"},
            follow=True,
        )

        self.assertEqual(ForecastRun.objects.count(), 0)
        self.assertContains(response, "Weather unavailable.")
