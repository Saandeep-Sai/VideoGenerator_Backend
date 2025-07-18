from django.urls import path
from .views import GenerateVideoView

urlpatterns = [
    path("generate/", GenerateVideoView.as_view(), name="generate-video"),
]
