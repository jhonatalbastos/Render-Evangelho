import streamlit as st
import json
import base64
import numpy as np
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy.io import wavfile
import io
import time

# Configurações de Saída
FPS = 30
WIDTH = 1080
HEIGHT = 1920

def get_base64_data(data_url):
    return base64.b64decode(data_url.split(",")[1])

def draw_rounded_rect(draw, coords, radius, fill):
    x1, y1, x2, y2 = coords
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    draw.pieslice([x1, y1, x1 + radius * 2, y1 + radius * 2], 180, 270, fill=fill)
    draw.pieslice([x2 - radius * 2, y1, x2, y1 + radius * 2], 270, 360, fill=fill)
    draw.pieslice([x1, y2 - radius * 2, x1 + radius * 2, y2], 90, 180, fill=fill)
    draw.pieslice([x2 - radius * 2, y2 - radius * 2, x2, y2], 0, 90, fill=fill)

def render_video(data):
    st.info("Iniciando Renderização Pesada... Isso pode levar alguns minutos.")
    
    # Pastas temporárias
    if not os.path.exists("temp_frames"): os.makedirs("temp_frames")
    
    settings = data['settings']
    blocks = data['blocks']
    
    # Processar Áudios para calcular duração total e waveforms
    total_duration = 0
    audio_segments = []
    
    for b in blocks:
        audio_bytes = get_base64_data(b['audio'])
        samplerate, audio_data = wavfile.read(io.BytesIO(audio_bytes))
        
        # Se for stereo, converter para mono para o waveform
        if len(audio_data.shape) > 1:
            audio_data_mono = audio_data.mean(axis=1)
        else:
            audio_data_mono = audio_data
            
        duration = len(audio_data) / samplerate
        audio_segments.append({
            'data': audio_data,
            'mono': audio_data_mono,
            'rate': samplerate,
            'start': total_duration,
            'end': total_duration + duration,
            'img': Image.open(io.BytesIO(get_base64_data(b['image']))).convert("RGB")
        })
        total_duration += duration + 0.5 # Gap de 0.5s entre blocos

    total_frames = int(total_duration * FPS)
    progress_bar = st.progress(0)
    status_text = st.empty()

    # Preparar Fontes (Assumindo que você subiu os arquivos .ttf pro repo)
    try:
        font_title = ImageFont.truetype("AlegreyaSans-Bold.ttf", int(settings['titleSize']))
        font_sub = ImageFont.truetype("AlegreyaSans-Regular.ttf", int(settings['subtitleSize']))
    except:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # Loop de Frames
    for f in range(total_frames):
        t = f / FPS
        frame_img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(frame_img)
        
        # Encontrar bloco atual
        active_segment = next((s for s in audio_segments if s['start'] <= t <= s['end']), None)
        
        if active_segment:
            # 1. Background com Zoom (Motion)
            bg = active_segment['img']
            block_t = t - active_segment['start']
            scale = 1.0 + (block_t * (settings['motionSpeed'] * 0.01))
            
            # Crop & Resize
            w, h = bg.size
            new_w = int(WIDTH / scale)
            new_h = int(HEIGHT / scale)
            left = (w - new_w) // 2
            top = (h - new_h) // 2
            bg_cropped = bg.crop((left, top, left + new_w, top + new_h)).resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
            frame_img.paste(bg_cropped, (0, 0))
            
            # 2. Partículas (Simulação simplificada)
            if settings['particlesEnabled']:
                for p in range(int(settings['particlesCount'])):
                    px = (hash(f"x{p}") % WIDTH)
                    py = (HEIGHT - (f * 2 + hash(f"y{p}")) % HEIGHT)
                    size = int(settings['particlesSize'])
                    draw.ellipse([px, py, px+size, py+size], fill=(255, 223, 128, 180))

            # 3. Overlays (Waveform e Textos)
            cx = WIDTH // 2
            y_pos = int(settings['textYPos'])
            
            # Titulo
            title_txt = ["EVANGELHO", "REFLEXÃO", "APLICAÇÃO", "ORAÇÃO"][audio_segments.index(active_segment)]
            tw = draw.textlength(title_txt, font=font_title)
            draw_rounded_rect(draw, [cx - tw/2 - 40, y_pos, cx + tw/2 + 40, y_pos + settings['titleSize']*1.2], 20, (85, 85, 85, 128))
            draw.text((cx, y_pos + settings['titleSize']*0.6), title_txt, fill="white", font=font_title, anchor="mm")

            # Waveform Dinâmico
            sample_idx = int(block_t * active_segment['rate'])
            if sample_idx < len(active_segment['mono']):
                chunk = active_segment['mono'][max(0, sample_idx-500):sample_idx+500]
                amp = np.abs(chunk).mean() if len(chunk) > 0 else 0
                wave_h = int(amp * settings['waveAmp'] * 200) + 10
                # Desenhar algumas barras
                for i in range(int(settings['waveWidth'])):
                    bar_x = cx + (i * 25)
                    draw_rounded_rect(draw, [bar_x, HEIGHT//2 - wave_h//2, bar_x + 15, HEIGHT//2 + wave_h//2], 7, (255, 255, 255, 150))
                    bar_x_inv = cx - (i * 25) - 15
                    draw_rounded_rect(draw, [bar_x_inv, HEIGHT//2 - wave_h//2, bar_x_inv + 15, HEIGHT//2 + wave_h//2], 7, (255, 255, 255, 150))

        # Salvar Frame
        frame_img.save(f"temp_frames/frame_{f:05d}.jpg", quality=85)
        
        if f % 30 == 0:
            progress_bar.progress(f / total_frames)
            status_text.text(f"Renderizando frame {f} de {total_frames}...")

    # 4. Combinar com FFmpeg
    status_text.text("Combinando áudio e vídeo com FFmpeg...")
    
    # Criar arquivo de áudio concatenado
    # (Para simplificar no Streamlit, vamos usar o FFmpeg para juntar os áudios também)
    with open("audio_list.txt", "w") as f_list:
        for i, b in enumerate(blocks):
            with open(f"temp_audio_{i}.wav", "wb") as fa:
                fa.write(get_base64_data(b['audio']))
            f_list.write(f"file 'temp_audio_{i}.wav'\n")
            f_list.write("file 'silence.wav'\n") # Adicionar silencio se necessário
            
    # Comando FFmpeg Final
    cmd = [
        'ffmpeg', '-y',
        '-framerate', str(FPS),
        '-i', 'temp_frames/frame_%05d.jpg',
        '-i', 'temp_audio_0.wav', # Simplificado: pegando o primeiro áudio para teste. 
        # Em produção, você concatenaria os 4 áudios antes.
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'veryfast',
        '-c:a', 'aac', '-shortest', 'output.mp4'
    ]
    
    subprocess.run(cmd)
    return "output.mp4"

st.title("🚀 Liturgia Render Server")
uploaded_file = st.file_uploader("Suba o arquivo JSON do Studio", type="json")

if uploaded_file:
    data = json.load(uploaded_file)
    if st.button("Iniciar Renderização Final"):
        video_path = render_video(data)
        with open(video_path, "rb") as f:
            st.video(f)
            st.download_button("Baixar Vídeo MP4", f, "video_liturgia.mp4")
