from rest_framework import serializers

class VideoRequestSerializer(serializers.Serializer):
    topic = serializers.CharField()
    duration = serializers.IntegerField(min_value=1)
