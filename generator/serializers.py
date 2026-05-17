from rest_framework import serializers

class VideoRequestSerializer(serializers.Serializer):
    topic = serializers.CharField()
    duration = serializers.IntegerField(min_value=1)
    aspect_ratio = serializers.ChoiceField(
        choices=["9:16", "16:9", "1:1", "4:3", "21:9"],
        default="9:16",
        required=False
    )
    video_type = serializers.ChoiceField(
        choices=["regular", "short"],
        default="regular",
        required=False
    )
    use_quality_pipeline = serializers.BooleanField(
        default=True,
        required=False,
        help_text="Use the optimized quality pipeline (default: True)"
    )
