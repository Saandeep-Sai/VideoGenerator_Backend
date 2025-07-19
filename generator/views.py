from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import VideoRequestSerializer
from .firebase_utils import create_job, get_job_by_id
import asyncio
import threading
import os
from .video_generator.optimized_video_generator import OptimizedVideoGenerationPipeline, VideoGenerationConfig

def background_generation(doc_id, topic, duration):
    """
    This function runs in a background thread to generate the video.
    """
    # Create a new asyncio event loop for the new thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    config = VideoGenerationConfig(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        groq_api_key=os.getenv("GROQ_API_KEY")
    )
    pipeline = OptimizedVideoGenerationPipeline(config)

    try:
        final_video_path = loop.run_until_complete(
            pipeline.generate_video_full_parallel(topic, duration)
        )
        # Handle the result, e.g., by updating Firestore with the video path or content
        # For simplicity, we'll just print it here. You'll want to add your
        # own logic to save the result.
        print(f"Video generated in background: {final_video_path}")
    except Exception as e:
        print(f"Error in background generation: {e}")
    finally:
        loop.close()

class GenerateVideoView(APIView):
    def post(self, request):
        serializer = VideoRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        topic = serializer.validated_data["topic"]
        duration = serializer.validated_data["duration"]

        doc_id = create_job(topic, duration)

        # Start video generation in a background thread
        thread = threading.Thread(
            target=background_generation,
            args=(doc_id, topic, duration)
        )
        thread.start()

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