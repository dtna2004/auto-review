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

app = Flask(__name__)

# Cấu hình đường dẫn cho PythonAnywhere
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['STATIC_FOLDER'] = os.path.join(BASE_DIR, 'static')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # Tăng lên 100MB max-limit

# Đảm bảo thư mục uploads và static tồn tại
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['STATIC_FOLDER'], 'videos'), exist_ok=True)

# Đảm bảo quyền ghi cho các thư mục
try:
    os.chmod(app.config['UPLOAD_FOLDER'], 0o777)
    os.chmod(os.path.join(app.config['STATIC_FOLDER'], 'videos'), 0o777)
except:
    pass

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
                filename = secure_filename(file.filename)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], f'image_{i}_{filename}')
                file.save(image_path)
                
                # Chuẩn hóa kích thước ảnh
                with Image.open(image_path) as img:
                    # Giữ tỷ lệ khung hình 16:9
                    target_width = 1920
                    target_height = 1080
                    img = img.convert('RGB')
                    
                    # Tính toán kích thước mới giữ nguyên tỷ lệ
                    ratio = min(target_width/img.width, target_height/img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)
                    
                    # Tạo ảnh nền đen
                    background = Image.new('RGB', (target_width, target_height), (0, 0, 0))
                    
                    # Paste ảnh vào giữa
                    offset = ((target_width - new_size[0]) // 2,
                             (target_height - new_size[1]) // 2)
                    background.paste(img, offset)
                    background.save(image_path)
                
                image_paths.append(image_path)
                
                # Tạo audio từ review text
                audio_path = os.path.join(app.config['UPLOAD_FOLDER'], f'audio_{i}.mp3')
                tts = gTTS(text=review, lang='vi')
                tts.save(audio_path)
                audio_paths.append(audio_path)
        
        # Tạo video
        video_path = create_video(image_paths, audio_paths)
        
        # Chuyển đường dẫn tương đối cho client
        relative_path = os.path.relpath(video_path, app.config['STATIC_FOLDER'])
        return jsonify({'video_path': f'/static/{relative_path}'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def create_video(image_paths, audio_paths):
    try:
        clips = []
        transition_duration = 1.0  # Thời gian chuyển cảnh (giây)
        
        for i, (img_path, audio_path) in enumerate(zip(image_paths, audio_paths)):
            # Đọc audio để lấy thời lượng
            audio = AudioFileClip(audio_path)
            duration = audio.duration
            
            # Tạo video clip từ ảnh với thời lượng dài hơn để có chỗ cho transition
            image = ImageClip(img_path).set_duration(duration + transition_duration)
            
            # Thêm audio vào clip
            video_clip = image.set_audio(audio)
            
            # Thêm hiệu ứng fade in/out
            if i > 0:  # Từ clip thứ 2 trở đi
                video_clip = video_clip.fx(vfx.fadein, transition_duration)
            if i < len(image_paths) - 1:  # Tất cả clip trừ clip cuối
                video_clip = video_clip.fx(vfx.fadeout, transition_duration)
            
            clips.append(video_clip)
        
        # Ghép các clip lại với nhau
        final_clip = concatenate_videoclips(clips, 
                                          method="compose",
                                          padding=-transition_duration)
        
        # Tạo tên file video duy nhất
        timestamp = int(time.time())
        output_path = os.path.join(app.config['STATIC_FOLDER'], 'videos', f'review_{timestamp}.mp4')
        
        # Xuất video với cấu hình phù hợp cho web
        final_clip.write_videofile(output_path, 
                                 fps=24,  # Giảm fps để giảm kích thước
                                 codec='libx264',
                                 audio_codec='aac',
                                 bitrate='4000k',  # Giảm bitrate
                                 audio_bitrate='128k',
                                 threads=2,  # Giảm số thread
                                 preset='faster')  # Sử dụng preset nhanh hơn
        
        # Đóng các clip để giải phóng bộ nhớ
        final_clip.close()
        for clip in clips:
            clip.close()
            
        # Xóa các file tạm
        for path in image_paths + audio_paths:
            try:
                os.remove(path)
            except:
                pass
        
        return output_path
        
    except Exception as e:
        # Đảm bảo dọn dẹp trong trường hợp lỗi
        try:
            final_clip.close()
            for clip in clips:
                clip.close()
        except:
            pass
            
        # Xóa các file tạm
        for path in image_paths + audio_paths:
            try:
                os.remove(path)
            except:
                pass
                
        raise e

if __name__ == '__main__':
    app.run(debug=True) 