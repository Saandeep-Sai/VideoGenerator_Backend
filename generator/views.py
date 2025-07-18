import os
import asyncio
import base64
import shutil

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import VideoRequestSerializer
from .firebase_utils import save_base64_segments_to_firestore
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
            os.makedirs(folder)  # recreate empty for next run

class GenerateVideoView(APIView):
    def post(self, request):
        serializer = VideoRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        topic = serializer.validated_data["topic"]
        duration = serializer.validated_data["duration"]

        config = VideoGenerationConfig(
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            groq_api_key=os.getenv("GROQ_API_KEY")
        )
        pipeline = OptimizedVideoGenerationPipeline(config)

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            video_path = loop.run_until_complete(
                pipeline.generate_video_full_parallel(topic, duration)
            )

            # Convert to Base64
            with open(video_path, "rb") as video_file:
                video_data = video_file.read()
                encoded_video = base64.b64encode(video_data).decode('utf-8')

            # Save to Firestore
            doc_id =save_base64_segments_to_firestore(encoded_video, topic, duration)

            # 🧹 Cleanup
            clean_directories()

            return Response({
                "status": "success",
                "firestore_doc_id": doc_id
            })

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
