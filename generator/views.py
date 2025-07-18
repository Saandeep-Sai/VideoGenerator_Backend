import os
import asyncio
import base64
import shutil
import threading

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import VideoRequestSerializer
from .firebase_utils import save_base64_segments_to_firestore, update_video_status
from .video_generator.optimized_video_generator import (
    VideoGenerationConfig,
    OptimizedVideoGenerationPipeline
)

TEMP_DIR = "temp"
OUTPUT_DIR = "output"

def clean_directories():
    for folder in [TEMP_DIR, OUTPUT_DIR]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            os.makedirs(folder)

class GenerateVideoView(APIView):
    def post(self, request):
        serializer = VideoRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        topic = serializer.validated_data["topic"]
        duration = serializer.validated_data["duration"]

        # First save "processing" state to Firebase and get doc ID
        doc_id = save_base64_segments_to_firestore(None, topic, duration, status="processing")

        # Create video config
        config = VideoGenerationConfig(
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            groq_api_key=os.getenv("GROQ_API_KEY")
        )
        pipeline = OptimizedVideoGenerationPipeline(config)

        def background_generation():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Run the video generation
                video_path = loop.run_until_complete(
                    pipeline.generate_video_full_parallel(topic, duration)
                )

                # Convert video to base64
                with open(video_path, "rb") as video_file:
                    video_data = video_file.read()
                    encoded_video = base64.b64encode(video_data).decode("utf-8")

                # Save segmented base64 back to Firestore and update status
                update_video_status(doc_id, encoded_video, status="completed")

                # Clean temp/output dirs
                clean_directories()

            except Exception as e:
                update_video_status(doc_id, None, status="failed", error=str(e))

        # Run video generation in background thread
        threading.Thread(target=background_generation).start()

        return Response({
            "status": "started",
            "message": "Video generation started in background.",
            "firestore_doc_id": doc_id
        }, status=status.HTTP_202_ACCEPTED)
