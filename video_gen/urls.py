from django.urls import path, include
from django.http import HttpResponse

def health_check(request):
    return HttpResponse("OK")


urlpatterns = [
    path("", health_check),  # So HEAD / returns 200 OK
    path('api/', include('generator.urls')),
]
