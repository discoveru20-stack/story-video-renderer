import os
import json
import uuid
import urllib.parse
import asyncio
import requests
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

async def generate_voiceover(text: str, voice: str, output_path: str):
    """Generates free neural voiceover using Edge-TTS."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

def download_image(prompt: str, output_path: str):
    """Downloads HD image from Pollinations.ai (zero API key needed)."""
    encoded_prompt = urllib.parse.quote(prompt)
    seed = os.urandom(4).hex()
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true&seed={seed}"
    
    response = requests.get(url, timeout=30)
    if response.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(response.content)
    else:
        raise Exception(f"Failed to download image from Pollinations. Code: {response.status_code}")

def upload_to_free_storage(file_path: str) -> str:
    """Uploads rendered video to Litterbox for immediate viewing."""
    with open(file_path, "rb") as f:
        response = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "24h"},
            files={"fileToUpload": f}
        )
    if response.status_code == 200:
        return response.text.strip()
    else:
        raise Exception("Failed to upload video to temporary storage.")

def main():
    payload_raw = os.environ.get("PAYLOAD_DATA", "{}")
    data = json.loads(payload_raw)
    
    scenes = data.get("scenes", [])
    voice = data.get("voice", "en-US-ChristopherNeural")
    row_index = data.get("row_index")
    webhook_url = data.get("webhook_url")
    
    job_id = str(uuid.uuid4())[:8]
    temp_files = []
    video_clips = []
    
    try:
        print("Starting video rendering pipeline...")
        for idx, scene in enumerate(scenes):
            audio_text = scene.get("audio_narration")
            image_prompt = scene.get("image_prompt")
            
            audio_path = f"temp_{job_id}_scene_{idx}.mp3"
            image_path = f"temp_{job_id}_scene_{idx}.jpg"
            temp_files.extend([audio_path, image_path])
            
            # 1. Voiceover
            asyncio.run(generate_voiceover(audio_text, voice, audio_path))
            
            # 2. Image Download
            download_image(image_prompt, image_path)
            
            # 3. Assemble Clip
            audio_clip = AudioFileClip(audio_path)
            image_clip = ImageClip(image_path).set_duration(audio_clip.duration)
            video_clip = image_clip.set_audio(audio_clip)
            video_clips.append(video_clip)
        
        # Stitch all scenes into single vertical MP4
        final_video = concatenate_videoclips(video_clips, method="compose")
        output_filename = f"video_{job_id}.mp4"
        
        final_video.write_videofile(
            output_filename,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast"
        )
        
        for clip in video_clips:
            clip.close()
        final_video.close()
        
        # Upload video to free storage for preview
        video_url = upload_to_free_storage(output_filename)
        print(f"Rendered video URL: {video_url}")
        
        # Post status back to Google Apps Script Webhook
        if webhook_url and row_index:
            requests.post(webhook_url, json={
                "row_index": row_index,
                "video_url": video_url
            })
            
    except Exception as e:
        print(f"Error rendering video: {str(e)}")
        if webhook_url and row_index:
            requests.post(webhook_url, json={
                "row_index": row_index,
                "video_url": f"Error: {str(e)}"
            })
    finally:
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

if __name__ == "__main__":
    main()
