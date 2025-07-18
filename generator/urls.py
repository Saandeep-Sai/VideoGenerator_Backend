from django.urls import path
from .views import GenerateVideoView, JobStatusView

urlpatterns = [
    path("generate/", GenerateVideoView.as_view(), name="generate-video"),
    path("status/<str:job_id>/", JobStatusView.as_view(), name="job-status"),
]
