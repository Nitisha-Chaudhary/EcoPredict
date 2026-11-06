import json
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = (
    "temperature_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "relative_humidity_2m",
    "cloud_cover",
    "precipitation_probability",
    "shortwave_radiation",
)


class WeatherServiceError(Exception):
    pass


def get_hourly_weather(latitude, longitude, hours):
    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(HOURLY_VARIABLES),
            "daily": "sunrise,sunset",
            "forecast_hours": hours,
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        }
    )
    try:
        with urlopen(f"{OPEN_METEO_URL}?{query}", timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise WeatherServiceError(
            "Weather data is temporarily unavailable. Please try again in a moment."
        ) from exc

    if not isinstance(payload, dict):
        raise WeatherServiceError("The weather service returned an invalid forecast.")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise WeatherServiceError("The weather service returned an invalid forecast.")
    daily = payload.get("daily")
    if not isinstance(daily, dict) or any(
        not isinstance(daily.get(key), list) for key in ("time", "sunrise", "sunset")
    ):
        raise WeatherServiceError("The weather service returned incomplete daily data.")
    required_keys = ("time", *HOURLY_VARIABLES)
    if any(not isinstance(hourly.get(key), list) for key in required_keys):
        raise WeatherServiceError("The weather service returned incomplete hourly data.")
    if any(len(hourly[key]) < hours for key in required_keys):
        raise WeatherServiceError("The weather service returned fewer hours than requested.")

    solar_times = {}
    try:
        for day, sunrise_value, sunset_value in zip(
            daily["time"], daily["sunrise"], daily["sunset"], strict=True
        ):
            if not all(isinstance(value, str) for value in (day, sunrise_value, sunset_value)):
                raise TypeError("Daily solar timestamps must be text.")
            sunrise = datetime.fromisoformat(sunrise_value.replace("Z", "+00:00"))
            sunset = datetime.fromisoformat(sunset_value.replace("Z", "+00:00"))
            solar_times[day] = (
                sunrise.replace(tzinfo=timezone.utc) if sunrise.tzinfo is None else sunrise,
                sunset.replace(tzinfo=timezone.utc) if sunset.tzinfo is None else sunset,
            )

        points = []
        for index in range(hours):
            time_value = hourly["time"][index]
            if not isinstance(time_value, str):
                raise TypeError("Forecast timestamp must be text.")
            timestamp = datetime.fromisoformat(time_value.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            humidity = int(hourly["relative_humidity_2m"][index])
            precipitation_probability = int(hourly["precipitation_probability"][index])
            sunrise, sunset = solar_times.get(timestamp.date().isoformat(), (None, None))
            point = {
                "timestamp": timestamp,
                "temperature_c": Decimal(str(hourly["temperature_2m"][index])),
                "wind_speed_ms": Decimal(str(hourly["wind_speed_10m"][index])),
                "wind_direction_deg": Decimal(str(hourly["wind_direction_10m"][index])),
                "relative_humidity_percent": humidity,
                "cloud_cover_percent": int(hourly["cloud_cover"][index]),
                "precipitation_probability_percent": precipitation_probability,
                "irradiance_wm2": Decimal(str(hourly["shortwave_radiation"][index])),
                "sunrise": sunrise,
                "sunset": sunset,
            }
            decimal_values = (
                point["temperature_c"],
                point["wind_speed_ms"],
                point["wind_direction_deg"],
                point["irradiance_wm2"],
            )
            if (
                not all(value.is_finite() for value in decimal_values)
                or point["wind_speed_ms"] < 0
                or not Decimal(0) <= point["wind_direction_deg"] <= Decimal(360)
                or not 0 <= humidity <= 100
                or not 0 <= point["cloud_cover_percent"] <= 100
                or not 0 <= precipitation_probability <= 100
                or point["irradiance_wm2"] < 0
            ):
                raise ValueError("Weather values are outside the expected range.")
            points.append(point)
    except (TypeError, ValueError, ArithmeticError, IndexError) as exc:
        raise WeatherServiceError("The weather service returned invalid hourly values.") from exc
    return points


def calculate_wind_power(wind_speed_ms, capacity_kw):
    speed = Decimal(str(wind_speed_ms))
    capacity = Decimal(str(capacity_kw))
    if capacity <= 0 or speed < 3 or speed >= 25:
        return Decimal("0")
    if speed >= 12:
        return capacity
    cubic_output = (speed**3 - Decimal(3) ** 3) / (Decimal(12) ** 3 - Decimal(3) ** 3)
    return max(Decimal("0"), min(capacity, capacity * cubic_output))


def calculate_solar_power(irradiance_wm2, temperature_c, capacity_kw, loss_percent):
    irradiance = max(Decimal("0"), Decimal(str(irradiance_wm2)))
    capacity = Decimal(str(capacity_kw))
    temperature = Decimal(str(temperature_c))
    losses = Decimal(str(loss_percent)) / Decimal(100)
    temperature_factor = min(
        Decimal("1.15"),
        max(Decimal("0.5"), Decimal(1) - Decimal("0.004") * (temperature - Decimal(25))),
    )
    output = capacity * irradiance / Decimal(1000) * temperature_factor * (Decimal(1) - losses)
    return max(Decimal("0"), min(capacity, output))
