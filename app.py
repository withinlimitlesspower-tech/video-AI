from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from celery import Celery
import os
import uuid
import json
from video_generator import generate_video_task

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

socketio = SocketIO(app, cors_allowed_origins="*")

# Celery configuration
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# Store task progress (in-memory for simplicity, use Redis in production)
task_progress = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_video():
    data = request.json
    prompt = data.get('prompt')
    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400
    
    task_id = str(uuid.uuid4())
    task = generate_video_task.apply_async(args=[prompt, task_id])
    task_progress[task_id] = {'status': 'pending', 'progress': 0}
    
    return jsonify({'task_id': task_id, 'status': 'Video generation started'}), 202

@app.route('/status/<task_id>')
def task_status(task_id):
    progress = task_progress.get(task_id, {'status': 'unknown', 'progress': 0})
    return jsonify(progress)

@app.route('/download/<task_id>')
def download_video(task_id):
    video_path = f'output/{task_id}.mp4'
    if os.path.exists(video_path):
        return send_file(video_path, as_attachment=True)
    return jsonify({'error': 'Video not found'}), 404

@socketio.on('connect')
def handle_connect():
    emit('connected', {'data': 'Connected to video maker'})

@socketio.on('progress_update')
def handle_progress_update(data):
    task_id = data.get('task_id')
    progress = data.get('progress')
    if task_id in task_progress:
        task_progress[task_id]['progress'] = progress
        emit('progress', {'task_id': task_id, 'progress': progress}, broadcast=True)

if __name__ == '__main__':
    os.makedirs('output', exist_ok=True)
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)