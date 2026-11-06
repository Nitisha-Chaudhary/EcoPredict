from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import EnergySite


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class EnergySiteForm(forms.ModelForm):
    class Meta:
        model = EnergySite
        fields = (
            "name",
            "location",
            "latitude",
            "longitude",
            "wind_capacity_kw",
            "solar_capacity_kw",
            "system_loss_percent",
            "status",
        )
        widgets = {
            "latitude": forms.NumberInput(attrs={"step": "0.00001", "min": "-90", "max": "90"}),
            "longitude": forms.NumberInput(attrs={"step": "0.00001", "min": "-180", "max": "180"}),
            "wind_capacity_kw": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "solar_capacity_kw": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "system_loss_percent": forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "100"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        wind_capacity = cleaned_data.get("wind_capacity_kw") or 0
        solar_capacity = cleaned_data.get("solar_capacity_kw") or 0
        if wind_capacity == 0 and solar_capacity == 0:
            raise forms.ValidationError("Enter a positive capacity for wind, solar, or both.")
        return cleaned_data
