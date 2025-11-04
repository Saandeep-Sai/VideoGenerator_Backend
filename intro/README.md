# Intro Video Folder

Place your intro video in this folder to have it automatically prepended to all generated videos.

## Supported Formats
- `.mp4` (recommended)
- `.mov`
- `.avi`
- `.mkv`

## Instructions
1. Place your intro video file in this folder
2. The system will automatically detect and use it
3. Only the first video found will be used
4. The intro will be added at the start of the final video during concatenation

## Example
```
intro/
  ├── my_intro.mp4  ← Your intro video
  └── README.md     ← This file
```

## Notes
- The intro video should match your desired aspect ratio for best results
- If no intro video is found, the system will proceed without it
- The intro is added using FFmpeg concat, so it should have compatible encoding
