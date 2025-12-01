"""
Dynamic Content Generator for YouTube Shorts
Generates trending topics, titles, and tags using Gemini AI
"""

import logging
import random
from typing import Dict, List, Tuple
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)

class DynamicContentGenerator:
    """Generate trending topics and metadata for YouTube Shorts using Gemini AI"""
    
    def __init__(self, gemini_api_key: str):
        self.gemini_api_key = gemini_api_key
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        logger.info("✅ Dynamic Content Generator initialized")
    
    def generate_trending_topic(self) -> str:
        """Generate a trending technical topic with high YouTube potential"""
        
        prompt = """Generate ONE trending technical topic that would perform well on YouTube Shorts.

REQUIREMENTS:
- Must be technical/programming related
- Should be searchable and have high demand
- Perfect for 45-60 second explanation
- Trending in 2024/2025
- Beginner to intermediate level

FOCUS AREAS (pick one):
- AI/Machine Learning basics
- Web Development trends
- Programming languages
- Cloud computing
- Cybersecurity
- Data Science
- Mobile development
- DevOps tools
- Software engineering concepts
- Tech career advice

OUTPUT FORMAT:
Just return the topic title, nothing else.

EXAMPLES:
"What is ChatGPT API and How to Use It"
"Docker vs Kubernetes Explained"
"Python vs JavaScript for Beginners"
"How to Get Your First Tech Job in 2025"

Generate ONE topic now:"""

        try:
            response = self.model.generate_content(prompt)
            topic = response.text.strip().replace('"', '').replace("'", "")
            logger.info(f"🎯 Generated trending topic: {topic}")
            return topic
        except Exception as e:
            logger.error(f"❌ Failed to generate topic: {e}")
            # Fallback to curated list
            fallback_topics = [
                "What is ChatGPT API and How to Use It",
                "Docker Containers Explained Simply",
                "Python vs JavaScript for Beginners",
                "Git Commands Every Developer Needs",
                "What is Cloud Computing in 2025",
                "How APIs Work in 60 Seconds",
                "React vs Vue.js Comparison",
                "SQL vs NoSQL Databases",
                "What is Machine Learning",
                "Cybersecurity Basics for Developers"
            ]
            topic = random.choice(fallback_topics)
            logger.warning(f"⚠️ Using fallback topic: {topic}")
            return topic
    
    def generate_youtube_metadata(self, topic: str, duration: int) -> Dict[str, str]:
        """Generate optimized YouTube title, description, and tags"""
        
        prompt = f"""Generate YouTube Shorts metadata for this topic: "{topic}"

The video is {duration} seconds long and explains {topic} in a fun, friendly way - like a friend teaching a friend!

Generate:
1. TITLE (under 100 chars, catchy, includes #Shorts)
2. DESCRIPTION (fun, engaging, includes hashtags, credits "Code Tapasya")
3. TAGS (10-15 relevant tags for YouTube algorithm)

TITLE REQUIREMENTS:
- Under 100 characters
- Include #Shorts
- Catchy and fun - NOT boring/academic
- Use casual language when possible
- Good examples: "Wait, THIS is How APIs Work?! 🤯 #Shorts", "I Learned {topic} in 60 Seconds! #Shorts"
- Bad examples: "Introduction to {topic}" (boring), "Understanding {topic}" (too formal)

DESCRIPTION REQUIREMENTS:
- Friendly, conversational tone
- Include relevant hashtags
- Credit "Code Tapasya" with a fun shoutout
- Encourage comments/engagement
- Use emojis for visual appeal

Example good description:
"Ever wondered how {topic} actually works? I got you! 💡 This quick breakdown makes it SO much easier to understand.

Drop a 🔥 if this helped you!

Huge thanks to Code Tapasya for the awesome content! 🙌

#Programming #Coding #LearnToCode #Developer #TechTips"

TAGS REQUIREMENTS:
- 10-15 tags
- Mix of broad and specific terms
- Include: programming, coding, tutorial, shorts
- Add topic-specific tags

OUTPUT FORMAT:
TITLE: [your title here]
DESCRIPTION: [your description here]
TAGS: tag1,tag2,tag3,tag4,tag5,tag6,tag7,tag8,tag9,tag10

Generate the metadata now:"""

        try:
            response = self.model.generate_content(prompt)
            content = response.text.strip()
            
            # Parse the response
            metadata = self._parse_metadata_response(content)
            logger.info(f"✅ Generated metadata for: {topic}")
            return metadata
            
        except Exception as e:
            logger.error(f"❌ Failed to generate metadata: {e}")
            # Fallback metadata
            return self._generate_fallback_metadata(topic, duration)
    
    def _parse_metadata_response(self, content: str) -> Dict[str, str]:
        """Parse Gemini response into structured metadata"""
        
        lines = content.split('\n')
        metadata = {
            'title': '',
            'description': '',
            'tags': []
        }
        
        current_section = None
        
        for line in lines:
            line = line.strip()
            
            if line.startswith('TITLE:'):
                metadata['title'] = line.replace('TITLE:', '').strip()
                current_section = 'title'
            elif line.startswith('DESCRIPTION:'):
                metadata['description'] = line.replace('DESCRIPTION:', '').strip()
                current_section = 'description'
            elif line.startswith('TAGS:'):
                tags_str = line.replace('TAGS:', '').strip()
                metadata['tags'] = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
                current_section = 'tags'
            elif current_section == 'description' and line and not line.startswith(('TITLE:', 'TAGS:')):
                # Multi-line description
                metadata['description'] += ' ' + line
        
        # Validate and clean
        if not metadata['title']:
            metadata['title'] = f"Learn {topic} in 60 Seconds! #Shorts"
        
        if not metadata['description']:
            metadata['description'] = f"Quick tutorial on {topic}! Perfect for developers on the go. Thanks to Code Tapasya! #Programming #Coding #Tutorial"
        
        if not metadata['tags']:
            metadata['tags'] = ['programming', 'coding', 'tutorial', 'shorts', 'education', 'tech', 'developer']
        
        # Ensure title is under 100 chars
        if len(metadata['title']) > 100:
            metadata['title'] = metadata['title'][:97] + "..."
        
        logger.info(f"📋 Parsed metadata - Title: {metadata['title'][:50]}...")
        return metadata
    
    def _generate_fallback_metadata(self, topic: str, duration: int) -> Dict[str, str]:
        """Generate fallback metadata if Gemini fails"""
        
        # Clean topic for title
        clean_topic = topic.replace('"', '').replace("'", "")
        
        # Friendly title variations
        title_templates = [
            f"Wait, THIS is {clean_topic}?! 🤯 #Shorts",
            f"I Learned {clean_topic} in {duration}s! #Shorts",
            f"{clean_topic} Made SO Simple! 💡 #Shorts",
            f"POV: You Finally Get {clean_topic} 😮 #Shorts",
            f"Why Nobody Explained {clean_topic} Like THIS #Shorts"
        ]
        
        import random
        title = random.choice(title_templates)
        if len(title) > 100:
            title = f"{clean_topic} Explained! 🔥 #Shorts"
        
        description = f"""Okay so I tried to explain {clean_topic} like I'm telling a friend... and honestly? It's way simpler than it sounds! 💡

If this actually made sense to you, drop a 🔥 in the comments!

Wanna learn more cool stuff like this? Hit that subscribe button - we're making coding actually fun here 😄

Huge shoutout to Code Tapasya for the amazing content! 🙌

#Programming #Coding #Tutorial #LearnToCode #Developer #TechTips #Shorts"""

        tags = [
            'programming', 'coding', 'tutorial', 'shorts', 'education',
            'tech', 'developer', 'learntocode', 'techtips', 'programming101',
            'codinglife', 'softwareengineering', 'webdevelopment', 'python', 'javascript'
        ]
        
        return {
            'title': title,
            'description': description,
            'tags': tags
        }
    
    def get_high_demand_topics(self, count: int = 5) -> List[str]:
        """Get multiple high-demand topics for batch generation"""
        
        prompt = f"""Generate {count} trending technical topics that would perform extremely well on YouTube Shorts in 2025.

REQUIREMENTS:
- High search volume and demand
- Technical/programming related
- Perfect for 45-60 second explanations
- Trending and relevant in 2025
- Mix of different tech areas

FOCUS ON HIGH-DEMAND AREAS:
- AI/ChatGPT/Machine Learning
- Web Development (React, Next.js, etc.)
- Python programming
- Cloud computing (AWS, Docker)
- Cybersecurity
- Data Science
- Mobile development
- DevOps and automation
- Programming career advice
- Latest tech trends

OUTPUT FORMAT:
1. [Topic 1]
2. [Topic 2]
3. [Topic 3]
etc.

Generate {count} high-demand topics:"""

        try:
            response = self.model.generate_content(prompt)
            content = response.text.strip()
            
            # Parse numbered list
            topics = []
            for line in content.split('\n'):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith('-')):
                    # Remove numbering and clean
                    topic = line.split('.', 1)[-1].strip()
                    topic = topic.replace('"', '').replace("'", "")
                    if topic:
                        topics.append(topic)
            
            if len(topics) >= count:
                logger.info(f"✅ Generated {len(topics)} high-demand topics")
                return topics[:count]
            else:
                logger.warning(f"⚠️ Only got {len(topics)} topics, padding with fallbacks")
                return topics + self._get_fallback_topics(count - len(topics))
                
        except Exception as e:
            logger.error(f"❌ Failed to generate high-demand topics: {e}")
            return self._get_fallback_topics(count)
    
    def _get_fallback_topics(self, count: int) -> List[str]:
        """Get fallback high-demand topics"""
        
        fallback_topics = [
            "What is ChatGPT API and How to Use It",
            "Docker vs Kubernetes Explained",
            "Python vs JavaScript for Beginners 2025",
            "How to Get Your First Tech Job",
            "React Hooks Explained Simply",
            "What is Machine Learning in 2025",
            "Git Commands Every Developer Needs",
            "AWS vs Google Cloud vs Azure",
            "Cybersecurity Tips for Developers",
            "What is Next.js and Why Use It",
            "Python Data Science in 60 Seconds",
            "How APIs Work Simply Explained",
            "SQL vs NoSQL Which to Choose",
            "What is DevOps in 2025",
            "Mobile App Development Flutter vs React Native"
        ]
        
        return random.sample(fallback_topics, min(count, len(fallback_topics)))