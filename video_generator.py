import requests
import json
import os
import uuid
from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
from moviepy.video.fx.all import resize
from celery import Celery
from flask_socketio import SocketIO
import io
from PIL import Image
import base64

# Initialize Celery
celery = Celery('tasks', broker='redis://localhost:6379/0')

# API Keys (set as environment variables in production)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'your-deepseek-key')
PIXABAY_API_KEY = os.getenv('PIXABAY_API_KEY', 'your-pixabay-key')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY', 'your-elevenlabs-key')

# SocketIO for progress updates (imported in app.py, passed via task)
socketio = None  # Will be set from app

def update_progress(task_id, progress):
    """Emit progress update via SocketIO"""
    if socketio:
        socketio.emit('progress_update', {'task_id': task_id, 'progress': progress})

def generate_script(prompt):
    """Use DeepSeek API to generate a video script and scene breakdown"""
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    system_prompt = "You are a video script generator. Given a prompt, create a script with 3-5 scenes. For each scene, provide a description and a search query for Pixabay videos/images. Output as JSON: {'script': 'full narration text', 'scenes': [{'description': '...', 'query': '...'}]}"
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1000
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        result = response.json()
        script_data = json.loads(result['choices'][0]['message']['content'])
        return script_data
    else:
        raise Exception(f"DeepSeek API error: {response.status_code}")

def fetch_pixabay_media(query, media_type='video'):
    """Fetch a video or image from Pixabay based on query"""
    url = "https://pixabay.com/api/videos/" if media_type == 'video' else "https://pixabay.com/api/"
    params = {
        'key': PIXABAY_API_KEY,
        'q': query,
        'per_page': 3,
        'video_type': 'film' if media_type == 'video' else None
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data['hits']:
            # Return the first hit's video URL or image URL
            hit = data['hits'][0]
            if media_type == 'video':
                return hit['videos']['medium']['url']
            else:
                return hit['webformatURL']
    # Fallback to a placeholder if no results
    return "https://cdn.pixabay.com/video/2020/01/01/placeholder.mp4" if media_type == 'video' else "https://cdn.pixabay.com/photo/2020/01/01/placeholder.jpg"

def generate_voiceover(text, task_id):
    """Use ElevenLabs API to generate voiceover from text"""
    url = "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM"  # Default voice ID
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    data = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5
        }
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        audio_path = f'temp/{task_id}_voiceover.mp3'
        with open(audio_path, 'wb') as f:
            f.write(response.content)
        return audio_path
    else:
        raise Exception(f"ElevenLabs API error: {response.status_code}")

def create_video_clip(media_url, duration=5):
    """Download media and create a video clip with MoviePy"""
    if media_url.endswith('.mp4'):
        clip = VideoFileClip(media_url)
        clip = clip.subclip(0, min(duration, clip.duration))
    else:
        # For images, download and create an image clip
        response = requests.get(media_url)
        img = Image.open(io.BytesIO(response.content))
        img_path = f'temp/{uuid.uuid4()}.jpg'
        img.save(img_path)
        clip = ImageClip(img_path, duration=duration)
    return clip.resize(height=720)  # Resize to 720p

@celery.task(bind=True)
def generate_video_task(self, prompt, task_id):
    """Main video generation pipeline"""
    try:
        update_progress(task_id, 10)
        
        # Step 1: Generate script with DeepSeek
        script_data = generate_script(prompt)
        update_progress(task_id, 30)
        
        # Step 2: Fetch media from Pixabay for each scene
        scenes = script_data['scenes']
        clips = []
        for i, scene in enumerate(scenes):
            media_url = fetch_pixabay_media(scene['query'], media_type='video')
            clip = create_video_clip(media_url, duration=5)  # 5 seconds per scene
            clips.append(clip)
        update_progress(task_id, 60)
        
        # Step 3: Generate voiceover with ElevenLabs
        audio_path = generate_voiceover(script_data['script'], task_id)
        update_progress(task_id, 80)
        
        # Step 4: Combine clips and audio with MoviePy
        final_clip = concatenate_videoclips(clips)
        audio_clip = AudioFileClip(audio_path)
        final_clip = final_clip.set_audio(audio_clip)
        
        output_path = f'output/{task_id}.mp4'
        final_clip.write_videofile(output_path, fps=24, codec='libx264')
        
        # Cleanup temp files
        for clip in clips:
            clip.close()
        if os.path.exists(audio_path):
            os.remove(audio_path)
        
        update_progress(task_id, 100)
        return {'status': 'completed', 'video_path': output_path}
    except Exception as e:
        update_progress(task_id, -1)  # Error indicator
        return {'status': 'failed', 'error': str(e)}