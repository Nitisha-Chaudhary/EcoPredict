# EcoPredict — Wind & Solar Energy Forecasting

EcoPredict is a Django application for managing renewable energy sites and estimating their next 24, 48, or 72 hours of wind and solar generation. It uses hourly weather forecasts from [Open-Meteo](https://open-meteo.com/) and stores forecast runs so they can be reviewed and compared later.

## Features

- Account signup, sign-in, and user-owned workspaces.
- Create, view, update, and delete wind/solar energy sites.
- Site coordinates, installed capacities, and configurable system-loss assumptions.
- Site status, search, location filters, and installed-capacity sorting.
- Hourly weather-backed forecasts for up to 72 hours, with wind, solar, and combined output.
- Operations dashboard with capacity, today's forecast generation, capacity factor, and transparent confidence status.
- Interactive hourly/daily portfolio charts with date and 24-hour/7-day/30-day selectors; chart KPIs sum the same displayed forecast values.
- Weather monitoring for temperature, wind speed and direction, humidity, cloud cover, precipitation probability, irradiance, sunrise, and sunset.
- Saved forecast history with search, technology, date, and duration filters; detailed run inputs and hourly prediction results.
- Rule-based weather insights, run-date analytics, and site wind/solar comparisons.
- Downloadable CSV reports for the signed-in user's forecast data.
- Responsive layouts for desktop, tablet, and mobile screens.
- Django admin interface for application data.
- SQLite for a simple local setup.

The forecast calculations are intentionally transparent estimates, not a trained machine-learning model or a substitute for turbine-specific power curves, panel specifications, or operational telemetry. Wind output uses a simplified 3/12/25 m/s cut-in/rated/cut-out curve. Solar output uses shortwave irradiance, site capacity, a temperature adjustment, and configured system losses. Forecast confidence and metrics such as MAE, RMSE, and R² are not reported because the application does not yet collect measured generation data for validation. The 7-day and 30-day chart selectors only display saved forecast points within the available weather forecast horizon; missing days are left blank rather than filled with invented estimates. Open-Meteo is a third-party service; a working internet connection is needed to generate forecasts.

## Run locally

Requirements: Python 3.10+ and pip.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000/` and create an account; there is no default username or password. Add an energy site with its coordinates and capacity, then generate a forecast from the site page. The dashboard, analytics, prediction history, and CSV export use data belonging to the signed-in account.

To access Django admin, create an administrator with `python manage.py createsuperuser` and visit `/admin/`.

## Configuration

The local defaults use SQLite, UTC, and `DEBUG=1`. Before deployment, set:

- `DJANGO_SECRET_KEY` to a unique, private secret.
- `DJANGO_DEBUG=0`.
- `DJANGO_ALLOWED_HOSTS` to a comma-separated list of valid host names.

For production, also configure an appropriate database, HTTPS, static-file serving, and secure cookie settings for your hosting environment.
