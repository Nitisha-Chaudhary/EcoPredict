import csv
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Subquery, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import EnergySiteForm, SignUpForm
from .models import EnergySite, ForecastPoint, ForecastRun
from .services import (
    WeatherServiceError,
    calculate_solar_power,
    calculate_wind_power,
    get_hourly_weather,
)


@login_required
def dashboard(request):
    sites = list(EnergySite.objects.filter(owner=request.user))
    capacity = EnergySite.objects.filter(owner=request.user).aggregate(
        wind=Sum("wind_capacity_kw"),
        solar=Sum("solar_capacity_kw"),
    )
    total_capacity = (capacity["wind"] or Decimal("0")) + (
        capacity["solar"] or Decimal("0")
    )
    forecasts = (
        ForecastRun.objects.filter(site__owner=request.user)
        .select_related("site")
        .order_by("-created_at")[:6]
    )
    latest_run = (
        ForecastRun.objects.filter(site_id=OuterRef("site_id"))
        .order_by("-created_at")
        .values("pk")[:1]
    )
    portfolio_forecasts = list(
        ForecastRun.objects.filter(
            site__owner=request.user,
            pk=Subquery(latest_run),
        )
        .select_related("site")
        .prefetch_related("points")
    )
    latest = max(portfolio_forecasts, key=lambda forecast: forecast.created_at, default=None)
    forecast_points = [
        point
        for forecast in portfolio_forecasts
        for point in forecast.points.all()
    ]
    forecast_points.sort(key=lambda point: point.timestamp)
    hourly_portfolio = {}
    for point in forecast_points:
        hourly = hourly_portfolio.setdefault(
            point.timestamp,
            {"wind": Decimal("0"), "solar": Decimal("0"), "total": Decimal("0")},
        )
        hourly["wind"] += point.wind_power_kw
        hourly["solar"] += point.solar_power_kw
        hourly["total"] += point.total_power_kw

    chart_period = request.GET.get("period", "24h")
    if chart_period not in ("24h", "7d", "30d"):
        chart_period = "24h"
    requested_date = request.GET.get("date", "")
    try:
        selected_date = date.fromisoformat(requested_date) if requested_date else None
    except ValueError:
        selected_date = None
    if selected_date is None and forecast_points:
        selected_date = forecast_points[0].timestamp.date()
    selected_date = selected_date or timezone.localdate()

    selected_hours = [
        (timestamp, values)
        for timestamp, values in sorted(hourly_portfolio.items())
        if timestamp.date() >= selected_date
    ]
    chart_labels = []
    wind_data = []
    solar_data = []
    total_data = []
    chart_hour_count = 0
    if chart_period == "24h":
        selected_hours = selected_hours[:24]
        chart_labels = [timestamp.strftime("%H:%M") for timestamp, _ in selected_hours]
        wind_data = [float(values["wind"]) for _, values in selected_hours]
        solar_data = [float(values["solar"]) for _, values in selected_hours]
        total_data = [float(values["total"]) for _, values in selected_hours]
        chart_hour_count = len(selected_hours)
    else:
        chart_days = 7 if chart_period == "7d" else 30
        for offset in range(chart_days):
            chart_day = selected_date + timedelta(days=offset)
            day_hours = [
                values
                for timestamp, values in selected_hours
                if timestamp.date() == chart_day
            ]
            chart_labels.append(chart_day.strftime("%b %d"))
            if day_hours:
                wind_data.append(float(sum(
                    (hour["wind"] for hour in day_hours), Decimal("0")
                )))
                solar_data.append(float(sum(
                    (hour["solar"] for hour in day_hours), Decimal("0")
                )))
                total_data.append(float(sum(
                    (hour["total"] for hour in day_hours), Decimal("0")
                )))
                chart_hour_count += len(day_hours)
            else:
                wind_data.append(None)
                solar_data.append(None)
                total_data.append(None)

    wind_energy = sum(
        (Decimal(str(value or 0)) for value in wind_data), Decimal("0")
    )
    solar_energy = sum(
        (Decimal(str(value or 0)) for value in solar_data), Decimal("0")
    )
    total_energy = sum(
        (Decimal(str(value or 0)) for value in total_data), Decimal("0")
    )
    latest_weather = forecast_points[0] if forecast_points else None
    today_points = [
        point
        for point in forecast_points
        if point.timestamp.date() == timezone.localdate()
    ]
    today_energy = sum(
        (point.total_power_kw for point in today_points), Decimal("0")
    )
    best_solar_hour = max(
        (point for point in forecast_points if point.solar_power_kw > 0),
        key=lambda point: point.solar_power_kw,
        default=None,
    )
    next_day_points = forecast_points[:24]
    average_wind_speed = (
        sum((point.wind_speed_ms for point in next_day_points), Decimal("0"))
        / len(next_day_points)
        if next_day_points
        else None
    )
    wind_conditions_favorable = bool(
        average_wind_speed is not None
        and Decimal("3") <= average_wind_speed < Decimal("25")
    )
    solar_conditions_favorable = bool(
        next_day_points
        and sum(
            (point.irradiance_wm2 for point in next_day_points), Decimal("0")
        )
        / len(next_day_points)
        >= Decimal("200")
    )
    generation_efficiency = (
        total_energy
        / (total_capacity * chart_hour_count)
        * Decimal("100")
        if total_capacity and chart_hour_count
        else None
    )
    insights = []
    if best_solar_hour:
        insights.append(
            f"Solar output is forecast to peak at {best_solar_hour.timestamp:%H:%M} UTC."
        )
    if average_wind_speed is not None:
        insights.append(
            "Wind speeds are within the model's generating range."
            if wind_conditions_favorable
            else "Wind generation potential is low on average for the next 24 forecast hours."
        )
    if next_day_points:
        insights.append(
            "Solar conditions look favorable over the next 24 forecast hours."
            if solar_conditions_favorable
            else "Solar irradiance is limited over the next 24 forecast hours."
        )
    return render(
        request,
        "forecasting/dashboard.html",
        {
            "sites": sites,
            "forecasts": forecasts,
            "latest": latest,
            "total_forecast_energy": total_energy,
            "wind_forecast_energy": wind_energy,
            "solar_forecast_energy": solar_energy,
            "average_wind_speed": average_wind_speed,
            "average_irradiance": (
                sum((point.irradiance_wm2 for point in next_day_points), Decimal("0"))
                / len(next_day_points)
                if next_day_points
                else None
            ),
            "latest_weather": latest_weather,
            "best_solar_hour": best_solar_hour,
            "wind_conditions_favorable": wind_conditions_favorable,
            "solar_conditions_favorable": solar_conditions_favorable,
            "insights": insights,
            "today_energy": today_energy,
            "generation_efficiency": generation_efficiency,
            "chart_period": chart_period,
            "selected_date": selected_date.isoformat(),
            "chart_labels": chart_labels,
            "wind_data": wind_data,
            "solar_data": solar_data,
            "total_data": total_data,
            "source_energy_data": [float(wind_energy), float(solar_energy)],
            "source_energy_labels": ["Wind", "Solar"],
            "total_capacity": total_capacity,
            "chart_hour_count": chart_hour_count,
            "chart_has_data": chart_hour_count > 0,
        },
    )


@login_required
def analytics(request):
    daily_totals = list(
        ForecastRun.objects.filter(site__owner=request.user)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            wind=Sum("points__wind_power_kw"),
            solar=Sum("points__solar_power_kw"),
            total=Sum("points__total_power_kw"),
        )
        .order_by("-day")[:30]
    )
    daily_totals.reverse()

    site_rows = []
    for site in EnergySite.objects.filter(owner=request.user):
        forecast = site.forecasts.first()
        if forecast is None:
            continue
        energy = forecast.points.aggregate(
            wind=Sum("wind_power_kw"),
            solar=Sum("solar_power_kw"),
        )
        site_rows.append(
            {
                "site": site,
                "forecast": forecast,
                "wind_energy": energy["wind"] or Decimal("0"),
                "solar_energy": energy["solar"] or Decimal("0"),
            }
        )

    return render(
        request,
        "forecasting/analytics.html",
        {
            "site_rows": site_rows,
            "daily_labels": [row["day"].strftime("%b %d") for row in daily_totals],
            "daily_wind": [float(row["wind"] or 0) for row in daily_totals],
            "daily_solar": [float(row["solar"] or 0) for row in daily_totals],
            "daily_total": [float(row["total"] or 0) for row in daily_totals],
            "report_url": "report_csv",
        },
    )


@login_required
def report_csv(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="ecopredict-forecast-report.csv"'
    writer = csv.writer(response)
    writer.writerow(
        (
            "Site",
            "Location",
            "Forecast created (UTC)",
            "Forecast horizon (hours)",
            "Timestamp (UTC)",
            "Temperature (C)",
            "Wind speed (m/s)",
            "Wind direction (degrees)",
            "Relative humidity (%)",
            "Cloud cover (%)",
            "Precipitation probability (%)",
            "Solar irradiance (W/m2)",
            "Sunrise (UTC)",
            "Sunset (UTC)",
            "Wind output (kW)",
            "Solar output (kW)",
            "Combined output (kW)",
        )
    )
    forecasts = (
        ForecastRun.objects.filter(site__owner=request.user)
        .select_related("site")
        .prefetch_related("points")
        .order_by("-created_at")
    )
    for forecast in forecasts:
        for point in forecast.points.all():
            writer.writerow(
                (
                    forecast.site.name,
                    forecast.site.location,
                    forecast.created_at.isoformat(),
                    forecast.horizon_hours,
                    point.timestamp.isoformat(),
                    point.temperature_c,
                    point.wind_speed_ms,
                    point.wind_direction_deg,
                    point.relative_humidity_percent,
                    point.cloud_cover_percent,
                    point.precipitation_probability_percent,
                    point.irradiance_wm2,
                    point.sunrise.isoformat() if point.sunrise else "",
                    point.sunset.isoformat() if point.sunset else "",
                    point.wind_power_kw,
                    point.solar_power_kw,
                    point.total_power_kw,
                )
            )
    return response


@login_required
def site_list(request):
    sites = EnergySite.objects.filter(owner=request.user).annotate(
        forecast_count=Count("forecasts", distinct=True),
        installed_capacity=F("wind_capacity_kw") + F("solar_capacity_kw"),
    )
    name = request.GET.get("name", "").strip()
    location = request.GET.get("location", "").strip()
    status = request.GET.get("status", "")
    sort = request.GET.get("sort", "name")
    if name:
        sites = sites.filter(name__icontains=name)
    if location:
        sites = sites.filter(location__icontains=location)
    if status in EnergySite.Status.values:
        sites = sites.filter(status=status)
    if sort == "capacity":
        sites = sites.order_by("-installed_capacity", "name")
    else:
        sort = "name"
        sites = sites.order_by("name")
    return render(
        request,
        "forecasting/site_list.html",
        {
            "sites": sites,
            "filters": {"name": name, "location": location, "status": status, "sort": sort},
            "has_filters": bool(name or location or status),
        },
    )


@login_required
def site_create(request):
    form = EnergySiteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        site = form.save(commit=False)
        site.owner = request.user
        site.save()
        messages.success(request, "Energy site created.")
        return redirect("site_detail", pk=site.pk)
    return render(request, "forecasting/site_form.html", {"form": form, "title": "Add energy site"})


@login_required
def site_detail(request, pk):
    site = get_object_or_404(EnergySite, pk=pk, owner=request.user)
    forecasts = site.forecasts.all()[:10]
    return render(request, "forecasting/site_detail.html", {"site": site, "forecasts": forecasts})


@login_required
def site_edit(request, pk):
    site = get_object_or_404(EnergySite, pk=pk, owner=request.user)
    form = EnergySiteForm(request.POST or None, instance=site)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Energy site updated.")
        return redirect("site_detail", pk=site.pk)
    return render(
        request,
        "forecasting/site_form.html",
        {"form": form, "site": site, "title": "Edit energy site"},
    )


@login_required
@require_POST
def site_delete(request, pk):
    site = get_object_or_404(EnergySite, pk=pk, owner=request.user)
    site.delete()
    messages.success(request, "Energy site and its forecasts were deleted.")
    return redirect("site_list")


@login_required
@require_POST
def forecast_create(request, pk):
    site = get_object_or_404(EnergySite, pk=pk, owner=request.user)
    try:
        hours = int(request.POST.get("horizon_hours", "24"))
    except (TypeError, ValueError):
        messages.error(request, "Choose a valid forecast horizon.")
        return redirect("site_detail", pk=site.pk)
    if hours not in (24, 48, 72):
        messages.error(request, "Forecast horizon must be 24, 48, or 72 hours.")
        return redirect("site_detail", pk=site.pk)
    try:
        weather_points = get_hourly_weather(site.latitude, site.longitude, hours)
    except WeatherServiceError as exc:
        messages.error(request, str(exc))
        return redirect("site_detail", pk=site.pk)

    with transaction.atomic():
        forecast = ForecastRun.objects.create(site=site, horizon_hours=hours)
        loss_percent = site.system_loss_percent
        points = []
        for weather in weather_points:
            wind_power = calculate_wind_power(weather["wind_speed_ms"], site.wind_capacity_kw)
            solar_power = calculate_solar_power(
                weather["irradiance_wm2"],
                weather["temperature_c"],
                site.solar_capacity_kw,
                loss_percent,
            )
            points.append(
                ForecastPoint(
                    forecast=forecast,
                    **weather,
                    wind_power_kw=wind_power,
                    solar_power_kw=solar_power,
                    total_power_kw=wind_power + solar_power,
                )
            )
        ForecastPoint.objects.bulk_create(points)
        forecast.total_energy_kwh = sum(
            ForecastPoint.objects.filter(forecast=forecast).values_list(
                "total_power_kw", flat=True
            ),
            Decimal("0"),
        )
        forecast.save(update_fields=["total_energy_kwh"])
    messages.success(request, f"{hours}-hour forecast created.")
    return redirect("forecast_detail", pk=forecast.pk)


@login_required
def forecast_detail(request, pk):
    forecast = get_object_or_404(
        ForecastRun.objects.select_related("site"),
        pk=pk,
        site__owner=request.user,
    )
    points = list(forecast.points.all())
    return render(
        request,
        "forecasting/forecast_detail.html",
        {
            "forecast": forecast,
            "points": points,
            "chart_labels": [point.timestamp.strftime("%b %d, %H:%M") for point in points],
            "wind_data": [float(point.wind_power_kw) for point in points],
            "solar_data": [float(point.solar_power_kw) for point in points],
            "total_data": [float(point.total_power_kw) for point in points],
            "average_power_kw": (
                forecast.total_energy_kwh / forecast.horizon_hours
                if forecast.horizon_hours
                else Decimal("0")
            ),
        },
    )


@login_required
def forecast_list(request):
    forecasts = ForecastRun.objects.filter(site__owner=request.user).select_related("site")
    site_name = request.GET.get("site", "").strip()
    technology = request.GET.get("technology", "")
    horizon = request.GET.get("horizon", "")
    date_from = parse_date(request.GET.get("from", ""))
    date_to = parse_date(request.GET.get("to", ""))
    if site_name:
        forecasts = forecasts.filter(site__name__icontains=site_name)
    if horizon in ("24", "48", "72"):
        forecasts = forecasts.filter(horizon_hours=int(horizon))
    else:
        horizon = ""
    if date_from:
        forecasts = forecasts.filter(created_at__date__gte=date_from)
    if date_to:
        forecasts = forecasts.filter(created_at__date__lte=date_to)
    if technology == "wind":
        forecasts = forecasts.annotate(
            has_output=Exists(
                ForecastPoint.objects.filter(
                    forecast_id=OuterRef("pk"),
                    wind_power_kw__gt=0,
                )
            )
        ).filter(has_output=True)
    elif technology == "solar":
        forecasts = forecasts.annotate(
            has_output=Exists(
                ForecastPoint.objects.filter(
                    forecast_id=OuterRef("pk"),
                    solar_power_kw__gt=0,
                )
            )
        ).filter(has_output=True)
    elif technology == "combined":
        forecasts = forecasts.annotate(
            has_output=Exists(
                ForecastPoint.objects.filter(
                    forecast_id=OuterRef("pk"),
                    total_power_kw__gt=0,
                )
            )
        ).filter(has_output=True)
    else:
        technology = ""
    return render(
        request,
        "forecasting/forecast_list.html",
        {
            "forecasts": forecasts,
            "filters": {
                "site": site_name,
                "technology": technology,
                "horizon": horizon,
                "from": date_from.isoformat() if date_from else "",
                "to": date_to.isoformat() if date_to else "",
            },
            "has_filters": bool(site_name or technology or horizon or date_from or date_to),
        },
    )


@login_required
@require_POST
def forecast_delete(request, pk):
    forecast = get_object_or_404(
        ForecastRun.objects.select_related("site"),
        pk=pk,
        site__owner=request.user,
    )
    forecast.delete()
    messages.success(request, "Forecast and its hourly data were deleted.")
    return redirect("forecast_list")


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Your account is ready. Add a site to get started.")
        return redirect("dashboard")
    return render(request, "registration/signup.html", {"form": form})
