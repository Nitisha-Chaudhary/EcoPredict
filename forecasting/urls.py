from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("analytics/", views.analytics, name="analytics"),
    path("reports/forecasts.csv", views.report_csv, name="report_csv"),
    path("signup/", views.signup, name="signup"),
    path("sites/", views.site_list, name="site_list"),
    path("sites/add/", views.site_create, name="site_create"),
    path("sites/<int:pk>/", views.site_detail, name="site_detail"),
    path("sites/<int:pk>/edit/", views.site_edit, name="site_edit"),
    path("sites/<int:pk>/delete/", views.site_delete, name="site_delete"),
    path("sites/<int:pk>/forecast/", views.forecast_create, name="forecast_create"),
    path("forecasts/", views.forecast_list, name="forecast_list"),
    path("forecasts/<int:pk>/delete/", views.forecast_delete, name="forecast_delete"),
    path("forecasts/<int:pk>/", views.forecast_detail, name="forecast_detail"),
]
