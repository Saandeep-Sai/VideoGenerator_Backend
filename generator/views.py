from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime
from .serializers import VideoRequestSerializer
from .firebase_utils import create_job, get_job_by_id

class HealthCheckView(APIView):
    """
    Health check endpoint for Render monitoring.
    Returns 200 OK if the service is running.
    """
    def get(self, request):
        return Response({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "service": "video-generator"
        }, status=status.HTTP_200_OK)

class GenerateVideoView(APIView):
    def post(self, request):
        serializer = VideoRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        topic = serializer.validated_data["topic"]
        duration = serializer.validated_data["duration"]

        doc_id = create_job(topic, duration)

        return Response({
            "status": "queued",
            "message": "Video job has been queued.",
            "job_id": doc_id
        }, status=status.HTTP_202_ACCEPTED)

class JobStatusView(APIView):
    def get(self, request, job_id):
        job = get_job_by_id(job_id)
        if not job:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(job, status=status.HTTP_200_OK)
