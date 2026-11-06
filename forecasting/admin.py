from django.contrib import admin

from .models import EnergySite, ForecastPoint, ForecastRun


class ForecastPointInline(admin.TabularInline):
    model = ForecastPoint
    extra = 0
    readonly_fields = [field.name for field in ForecastPoint._meta.fields if field.name != "id"]
    can_delete = False


@admin.register(EnergySite)
class EnergySiteAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "location", "status", "total_capacity_kw")
    list_filter = ("status",)
    search_fields = ("name", "location", "owner__username")


@admin.register(ForecastRun)
class ForecastRunAdmin(admin.ModelAdmin):
    list_display = ("site", "horizon_hours", "total_energy_kwh", "created_at")
    list_filter = ("horizon_hours", "created_at")
    inlines = [ForecastPointInline]
