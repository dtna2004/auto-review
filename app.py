import os
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
from PIL import Image
from gtts import gTTS
from moviepy.editor import (
    ImageClip, 
    AudioFileClip, 
    concatenate_videoclips,
    vfx
)
import time
import logging
import tempfile
import shutil

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cấu hình đường dẫn cho Render
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = tempfile.mkdtemp()  # Tạo thư mục tạm thời
app.config['UPLOAD_FOLDER'] = os.path.join(TEMP_DIR, 'uploads')
app.config['STATIC_FOLDER'] = os.path.join(TEMP_DIR, 'static')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# Đảm bảo thư mục uploads và static tồn tại
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['STATIC_FOLDER'], 'videos'), exist_ok=True)

# Đảm bảo quyền ghi cho các thư mục
try:
    os.chmod(app.config['UPLOAD_FOLDER'], 0o777)
    os.chmod(os.path.join(app.config['STATIC_FOLDER'], 'videos'), 0o777)
except Exception as e:
    logger.error(f"Error setting permissions: {str(e)}")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'images[]' not in request.files:
        return jsonify({'error': 'No files uploaded'}), 400
    
    files = request.files.getlist('images[]')
    reviews = request.form.getlist('reviews[]')
    
    if not files or not reviews:
        return jsonify({'error': 'Missing files or reviews'}), 400

    try:
        # Lưu ảnh và tạo audio từ text
        image_paths = []
        audio_paths = []
        
        for i, (file, review) in enumerate(zip(files, reviews)):
            if file and allowed_file(file.filename):
                try:
                    filename = secure_filename(file.filename)
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], f'image_{i}_{filename}')
                    file.save(image_path)
                    logger.info(f"Saved image to {image_path}")
                    
                    # Chuẩn hóa kích thước ảnh
                    with Image.open(image_path) as img:
                        # Giữ tỷ lệ khung hình 16:9
                        target_width = 1280  # Giảm kích thước xuống để xử lý nhanh hơn
                        target_height = 720
                        img = img.convert('RGB')
                        
                        ratio = min(target_width/img.width, target_height/img.height)
                        new_size = (int(img.width * ratio), int(img.height * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                        
                        background = Image.new('RGB', (target_width, target_height), (0, 0, 0))
                        offset = ((target_width - new_size[0]) // 2,
                                 (target_height - new_size[1]) // 2)
                        background.paste(img, offset)
                        background.save(image_path)
                    
                    image_paths.append(image_path)
                    
                    # Tạo audio từ review text
                    audio_path = os.path.join(app.config['UPLOAD_FOLDER'], f'audio_{i}.mp3')
                    tts = gTTS(text=review, lang='vi')
                    tts.save(audio_path)
                    logger.info(f"Saved audio to {audio_path}")
                    audio_paths.append(audio_path)
                
                except Exception as e:
                    logger.error(f"Error processing file {filename}: {str(e)}")
                    raise
        
        # Tạo video
        video_path = create_video(image_paths, audio_paths)
        logger.info(f"Created video at {video_path}")
        
        # Copy video to static folder
        static_video_dir = os.path.join(BASE_DIR, 'static', 'videos')
        os.makedirs(static_video_dir, exist_ok=True)
        final_video_path = os.path.join(static_video_dir, os.path.basename(video_path))
        shutil.copy2(video_path, final_video_path)
        
        # Chuyển đường dẫn tương đối cho client
        relative_path = os.path.join('videos', os.path.basename(video_path))
        return jsonify({'video_path': f'/static/{relative_path}'})
    
    except Exception as e:
        logger.error(f"Error in upload_files: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        # Dọn dẹp files
        try:
            for path in image_paths + audio_paths:
                if os.path.exists(path):
                    os.remove(path)
        except Exception as e:
            logger.error(f"Error cleaning up files: {str(e)}")

def create_video(image_paths, audio_paths):
    clips = []
    try:
        transition_duration = 1.0
        
        for i, (img_path, audio_path) in enumerate(zip(image_paths, audio_paths)):
            try:
                # Đọc audio để lấy thời lượng
                audio = AudioFileClip(audio_path)
                duration = audio.duration
                
                # Tạo video clip từ ảnh
                image = ImageClip(img_path).set_duration(duration + transition_duration)
                video_clip = image.set_audio(audio)
                
                # Thêm hiệu ứng fade in/out
                if i > 0:
                    video_clip = video_clip.fx(vfx.fadein, transition_duration)
                if i < len(image_paths) - 1:
                    video_clip = video_clip.fx(vfx.fadeout, transition_duration)
                
                clips.append(video_clip)
                logger.info(f"Processed clip {i+1}/{len(image_paths)}")
                
            except Exception as e:
                logger.error(f"Error processing clip {i}: {str(e)}")
                raise
        
        # Ghép các clip lại với nhau
        final_clip = concatenate_videoclips(clips, 
                                          method="compose",
                                          padding=-transition_duration)
        
        # Tạo tên file video duy nhất
        timestamp = int(time.time())
        output_path = os.path.join(app.config['STATIC_FOLDER'], 'videos', f'review_{timestamp}.mp4')
        
        # Xuất video với cấu hình phù hợp cho web
        final_clip.write_videofile(output_path, 
                                 fps=24,
                                 codec='libx264',
                                 audio_codec='aac',
                                 bitrate='2000k',
                                 audio_bitrate='128k',
                                 threads=2,
                                 preset='ultrafast')  # Sử dụng preset nhanh nhất
        
        return output_path
        
    except Exception as e:
        logger.error(f"Error in create_video: {str(e)}")
        raise
    finally:
        # Đóng các clip để giải phóng bộ nhớ
        try:
            for clip in clips:
                clip.close()
        except Exception as e:
            logger.error(f"Error closing clips: {str(e)}")

if __name__ == '__main__':
    app.run(debug=True) 