"""
Dynamic Content Generator for YouTube Shorts
Generates trending topics, titles, and tags using OpenRouter AI
"""

import logging
import random
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Set
from openai import OpenAI
from .openrouter_key_manager import OpenRouterKeyManager

logger = logging.getLogger(__name__)

class DynamicContentGenerator:
    """Generate trending topics and metadata for YouTube Shorts using OpenRouter AI"""
    
    def __init__(self, openrouter_api_key: str = None, openrouter_api_keys: List[str] = None, history_file: str = "youtube_shorts_history.json"):
        """
        Initialize content generator with key rotation support.
        
        Args:
            openrouter_api_key: Single API key (for backward compatibility)
            openrouter_api_keys: List of API keys for rotation (preferred)
            history_file: Path to topic history JSON file
        """
        self.history_file = Path(history_file)
        self.model_name = "meta-llama/llama-3.3-70b-instruct:free"
        
        # Initialize key manager with rotation support
        if openrouter_api_keys:
            self.key_manager = OpenRouterKeyManager(api_keys=openrouter_api_keys)
        elif openrouter_api_key:
            self.key_manager = OpenRouterKeyManager(api_keys=[openrouter_api_key])
        else:
            # Load from environment
            self.key_manager = OpenRouterKeyManager()
        
        logger.info(f"✅ Dynamic Content Generator initialized with {self.key_manager.get_stats()['total_keys']} API key(s)")
        logger.info(f"📝 Topic Generation Model: {self.model_name}")
    
    def load_topic_history(self) -> Dict[str, str]:
        """Load topic history from file"""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning("⚠️ Corrupted history file, starting fresh")
                return {}
        return {}
    
    def get_used_topics(self, days: int = 30) -> Set[str]:
        """Get set of topics used in the last N days (normalized for comparison)"""
        history = self.load_topic_history()
        cutoff = datetime.now() - timedelta(days=days)
        
        used_topics = set()
        for topic, last_used_str in history.items():
            try:
                last_used = datetime.fromisoformat(last_used_str)
                if last_used > cutoff:
                    # Normalize topic for comparison (lowercase, strip)
                    used_topics.add(self._normalize_topic(topic))
            except (ValueError, TypeError):
                pass
        
        logger.info(f"📊 Found {len(used_topics)} topics used in last {days} days")
        return used_topics
    
    def _normalize_topic(self, topic: str) -> str:
        """Normalize topic string for comparison"""
        return topic.lower().strip().replace('"', '').replace("'", "")
    
    def _is_topic_similar(self, new_topic: str, used_topics: Set[str], threshold: float = 0.7) -> bool:
        """Check if new topic is too similar to any used topic"""
        normalized_new = self._normalize_topic(new_topic)
        
        # Exact match check
        if normalized_new in used_topics:
            return True
        
        # Check for significant word overlap
        new_words = set(normalized_new.split())
        
        for used_topic in used_topics:
            used_words = set(used_topic.split())
            
            # Calculate Jaccard similarity
            if new_words and used_words:
                intersection = len(new_words & used_words)
                union = len(new_words | used_words)
                similarity = intersection / union if union > 0 else 0
                
                if similarity >= threshold:
                    logger.debug(f"🔍 Topic '{new_topic}' too similar to '{used_topic}' (similarity: {similarity:.2f})")
                    return True
        
        return False
    
    def generate_trending_topic(self, used_topics: Optional[Set[str]] = None) -> str:
        """Generate a trending technical topic with high YouTube potential, avoiding repeats"""
        
        # Get used topics if not provided
        if used_topics is None:
            used_topics = self.get_used_topics(days=30)
        
        # Create exclusion list for the prompt
        recent_topics_list = list(used_topics)[:20]  # Limit to 20 for prompt size
        exclusion_text = ""
        if recent_topics_list:
            exclusion_text = f"""
IMPORTANT - DO NOT generate any topic similar to these recently used topics:
{chr(10).join(f'- {t}' for t in recent_topics_list)}

Generate something COMPLETELY DIFFERENT from the above list!
"""
        
        prompt = f"""Generate ONE trending technical topic that would perform well on YouTube Shorts.

REQUIREMENTS:
- Must be technical/programming related
- Should be searchable and have high demand
- Perfect for 45-60 second explanation
- Trending in 2024/2025
- Beginner to intermediate level
- MUST BE UNIQUE - not a repeat of common topics
{exclusion_text}
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
- New frameworks and tools
- Programming tips and tricks
- Code optimization
- Developer productivity

OUTPUT FORMAT:
Just return the topic title, nothing else. Make it specific and unique!

GOOD UNIQUE EXAMPLES:
"Why Senior Devs Love TypeScript Enums"
"The One Python Trick Nobody Teaches"
"How Netflix Handles Millions of Users"
"Why Your API is Slower Than It Should Be"
"The CSS Property That Changed My Life"

Generate ONE unique topic now:"""

        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                def call_openrouter(client):
                    response = client.chat.completions.create(
                        model=self.model_name,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.7,
                        max_tokens=1000,
                    )
                    return response.choices[0].message.content
                
                response_text = self.key_manager.execute_with_rotation(
                    call_openrouter,
                    model=self.model_name
                )
                topic = response_text.strip().replace('"', '').replace("'", "")
                
                # Check if topic is too similar to used topics
                if not self._is_topic_similar(topic, used_topics):
                    logger.info(f"🎯 Generated unique topic: {topic}")
                    return topic
                else:
                    logger.warning(f"⚠️ Attempt {attempt + 1}: Topic '{topic}' too similar to recent topics, retrying...")
                    
            except Exception as e:
                logger.error(f"❌ Attempt {attempt + 1} failed: {e}")
        
        # Fallback to curated list (excluding used ones)
        logger.warning("⚠️ AI generation failed, using fallback topics")
        return self._get_unique_fallback_topic(used_topics)
    
    def _get_unique_fallback_topic(self, used_topics: Set[str]) -> str:
        """Get a unique fallback topic that hasn't been used"""
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
            "Cybersecurity Basics for Developers",
            "Why TypeScript is Taking Over",
            "Redis Cache Explained Simply",
            "GraphQL vs REST API",
            "Microservices Architecture Basics",
            "CI/CD Pipeline Explained",
            "Kubernetes for Beginners",
            "MongoDB vs PostgreSQL",
            "WebSockets Explained Simply",
            "OAuth 2.0 How It Works",
            "Clean Code Principles",
            "SOLID Principles Explained",
            "Design Patterns Every Dev Needs",
            "Async Await in JavaScript",
            "Python Decorators Explained",
            "React Hooks vs Class Components",
            "Next.js vs Create React App",
            "Tailwind CSS Why Developers Love It",
            "VS Code Tips and Tricks",
            "Linux Commands for Developers",
            "How HTTPS Works Simply"
        ]
        
        # Filter out used topics
        available = [t for t in fallback_topics if not self._is_topic_similar(t, used_topics)]
        
        if available:
            topic = random.choice(available)
            logger.info(f"📌 Selected unique fallback topic: {topic}")
            return topic
        else:
            # All fallbacks used, generate a variation
            base_topic = random.choice(fallback_topics)
            variation = f"{base_topic} - {datetime.now().strftime('%B %Y')} Update"
            logger.warning(f"⚠️ All topics used, creating variation: {variation}")
            return variation
    
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
            def call_openrouter(client):
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=1000,
                )
                return response.choices[0].message.content
            
            response_text = self.key_manager.execute_with_rotation(
                call_openrouter,
                model=self.model_name
            )
            content = response_text.strip()
            
            # Parse the response
            metadata = self._parse_metadata_response(content, topic)
            logger.info(f"✅ Generated metadata for: {topic}")
            return metadata
            
        except Exception as e:
            logger.error(f"❌ Failed to generate metadata: {e}")
            # Fallback metadata
            return self._generate_fallback_metadata(topic, duration)
    
    def _parse_metadata_response(self, content: str, topic: str) -> Dict[str, str]:
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
            def call_openrouter(client):
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=2000,
                )
                return response.choices[0].message.content
            
            response_text = self.key_manager.execute_with_rotation(
                call_openrouter,
                model=self.model_name
            )
            content = response_text.strip()
            
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