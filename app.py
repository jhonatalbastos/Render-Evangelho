import streamlit as st
import json
import os
import numpy as np
from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip, TextClip, ColorClip, concatenate_videoclips
from moviepy.video.fx.all import resize, crop
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math
import tempfile
import glob

# === CONFIGURAÇÃO ===
st.set_page_config(page_title="Render Farm - TikTok Studio", layout="wide")
RENDER_QUEUE_DIR = "TikTok_Render_Queue" # Se rodar local. Na nuvem, usaria Google Drive API.

# --- SIMULAÇÃO DE GOOGLE DRIVE (PARA DEMONSTRAÇÃO) ---
# Em produção real no Streamlit Cloud, você usaria:
# from google.oauth2 import service_account
# from googleapiclient.discovery import build
# E baixaria os arquivos do Drive para um temp dir.
# Aqui, assumimos que você baixou a pasta do Drive para local ou está sincronizado.

st.title("🎬 Render Farm - Liturgia TikTok")
st.markdown("Renderizador Server-Side usando MoviePy + Pillow para replicar o Canvas HTML5.")

# === RENDERER ENGINE (CORE) ===

def rounded_rectangle(draw, xy, corner_radius, fill=None, outline=None):
    upper_left_point = xy[0]
    bottom_right_point = xy[1]
    draw.rectangle(
        [
            (upper_left_point[0], upper_left_point[1] + corner_radius),
            (bottom_right_point[0], bottom_right_point[1] - corner_radius)
        ],
        fill=fill, outline=outline
    )
    draw.rectangle(
        [
            (upper_left_point[0] + corner_radius, upper_left_point[1]),
            (bottom_right_point[0] - corner_radius, bottom_right_point[1])
        ],
        fill=fill, outline=outline
    )
    draw.pieslice([upper_left_point[0], upper_left_point[1], upper_left_point[0] + corner_radius * 2, upper_left_point[1] + corner_radius * 2], 180, 270, fill=fill, outline=outline)
    draw.pieslice([bottom_right_point[0] - corner_radius * 2, bottom_right_point[1] - corner_radius * 2, bottom_right_point[0], bottom_right_point[1]], 0, 90, fill=fill, outline=outline)
    draw.pieslice([upper_left_point[0], bottom_right_point[1] - corner_radius * 2, upper_left_point[0] + corner_radius * 2, bottom_right_point[1]], 90, 180, fill=fill, outline=outline)
    draw.pieslice([bottom_right_point[0] - corner_radius * 2, upper_left_point[1], bottom_right_point[0], upper_left_point[1] + corner_radius * 2], 270, 360, fill=fill, outline=outline)

def create_frame(t, img_pil, settings, audio_duration, block_index, liturgy_info, gospel_ref, date_str):
    # Dimensões
    W, H = 1080, 1920
    
    # === 1. FUNDO & ZOOM (Ken Burns) ===
    # Simula o zoom contínuo do JS
    motion_speed = float(settings['visuals']['motionSpeed'])
    scale = 1.0 + (t * (motion_speed * 0.003)) if settings['visuals']['motionEnabled'] else 1.0
    
    # Redimensiona imagem baseada na escala
    new_w = int(W * scale)
    new_h = int(H * scale)
    # Garante aspect ratio cover
    img_resized = img_pil.resize((new_w, new_h), Image.LANCZOS)
    
    # Crop central
    left = (new_w - W) // 2
    top = (new_h - H) // 2
    bg = img_resized.crop((left, top, left + W, top + H))
    
    # Converte para RGBA para overlays
    canvas = bg.convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    
    # === 2. PARTÍCULAS (Simplificado) ===
    if settings['visuals']['particlesEnabled']:
        # Partículas estáticas randômicas por frame para simular cintilação
        # Para performance real em python, não rastreamos estado, apenas noise dourado
        for _ in range(int(settings['visuals'].get('particlesCount', 50))):
            x = np.random.randint(0, W)
            y = np.random.randint(0, H)
            r = np.random.randint(1, int(settings['visuals'].get('particlesSize', 3)) + 1)
            alpha = np.random.randint(100, 200)
            draw.ellipse([x, y, x+r, y+r], fill=(255, 223, 128, alpha))

    # === 3. OVERLAYS DE TEXTO ===
    center_x = W // 2
    y_pos = int(settings['visuals']['textYPos'])
    
    # Configurações de Fade/Slide
    fade_dur = 1.0
    slide_dur = float(settings['visuals']['slideDuration'])
    alpha_text = 255
    y_offset = 0
    
    # Entrada (Fade In + Slide Up)
    if t < fade_dur:
        prog = t / fade_dur
        alpha_text = int(255 * prog)
        y_offset = (1 - prog) * 50
    # Saída (Fade Out + Slide Down)
    elif settings['visuals']['slideEnabled'] and t > slide_dur:
        prog = (t - slide_dur) / 1.0 # 1s fade out
        if prog > 1: prog = 1
        alpha_text = int(255 * (1 - prog))
        y_offset = prog * 50

    # Títulos fixos (Entrada apenas)
    title_titles = ["EVANGELHO", "REFLEXÃO", "APLICAÇÃO", "ORAÇÃO"]
    curr_title = title_titles[block_index] if block_index < 4 else ""
    
    # Carregar Fontes (Fallback se não tiver arquivo)
    try:
        font_title = ImageFont.truetype("AlegreyaSans-Bold.ttf", int(settings['visuals']['titleSize']))
        font_sub = ImageFont.truetype("AlegreyaSans-Regular.ttf", int(settings['visuals']['subtitleSize']))
        font_sub_sm = ImageFont.truetype("AlegreyaSans-Italic.ttf", int(settings['visuals']['subtitleSize']) * 0.8)
    except:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_sub_sm = ImageFont.load_default()

    # --- Render Título Principal (Persistente) ---
    # Fica visível sempre (exceto entrada)
    persist_alpha = 255 if t >= fade_dur else int(255 * (t/fade_dur))
    if persist_alpha > 0:
        # Fundo Título
        t_bbox = draw.textbbox((0,0), curr_title, font=font_title)
        t_w = t_bbox[2] - t_bbox[0] + 80
        t_h = int(settings['visuals']['titleSize']) * 1.4
        
        rect_color = (85, 85, 85, int(128 * (persist_alpha/255))) # 0.5 opacity
        rounded_rectangle(draw, [(center_x - t_w/2, y_pos), (center_x + t_w/2, y_pos + t_h)], 20, fill=rect_color)
        
        # Texto Título
        draw.text((center_x, y_pos + t_h/2), curr_title, font=font_title, fill=(255,255,255,persist_alpha), anchor="mm")

    # --- Render Subtítulos (Transientes) ---
    if alpha_text > 0:
        curr_y = y_pos + y_offset + (int(settings['visuals']['titleSize']) * 1.4) + 15
        sub_h = int(settings['visuals']['subtitleSize']) * 1.4
        
        sub_data = [
            (date_str, font_sub),
            (gospel_ref, font_sub),
            (liturgy_info['liturgia'], font_sub_sm)
        ]
        
        for text, fnt in sub_data:
            s_bbox = draw.textbbox((0,0), text, font=fnt)
            s_w = s_bbox[2] - s_bbox[0] + 60
            
            rect_col = (119, 119, 119, int(128 * (alpha_text/255)))
            rounded_rectangle(draw, [(center_x - s_w/2, curr_y), (center_x + s_w/2, curr_y + sub_h)], 10, fill=rect_col)
            draw.text((center_x, curr_y + sub_h/2), text, font=fnt, fill=(255,255,255,alpha_text), anchor="mm")
            
            curr_y += sub_h + 15

    # === 4. WAVEFORM ===
    # Simulado visualmente
    wave_bars = int(settings['visuals']['waveformWidth'])
    wave_y = H // 2
    wave_opac = int(float(settings['visuals']['waveformOpacity']) * 2.55)
    wave_amp = float(settings['visuals']['waveformAmplitude'])
    
    # Animação baseada no tempo
    for i in range(wave_bars):
        # Simula movimento com senoide
        val = (math.sin(i * 0.5 + t * 5) + 1) * 30 * wave_amp + 10
        # Randomness para parecer voz
        val += np.random.randint(0, 10)
        
        bar_w = 15
        gap = 8
        
        # Lado Direito
        xr = center_x + (i * (bar_w + gap)) + gap/2
        draw.rectangle([xr, wave_y - val/2, xr + bar_w, wave_y + val/2], fill=(255,255,255, wave_opac))
        
        # Lado Esquerdo
        xl = center_x - ((i+1) * (bar_w + gap)) + gap/2
        draw.rectangle([xl, wave_y - val/2, xl + bar_w, wave_y + val/2], fill=(255,255,255, wave_opac))

    # Compor
    out = Image.alpha_composite(canvas, overlay)
    return np.array(out)

def render_project(project_path):
    st.info(f"Iniciando renderização de: {project_path}")
    
    # Carregar Configurações
    with open(os.path.join(project_path, "manifest.json"), 'r') as f:
        settings = json.load(f)
        
    clips = []
    
    # Processar 4 blocos
    for i in range(4):
        # Assets
        img_path = os.path.join(project_path, f"image_{i}.png")
        aud_path = os.path.join(project_path, f"audio_{i}.wav")
        
        if not os.path.exists(img_path) or not os.path.exists(aud_path):
            st.error(f"Faltando arquivos para o bloco {i}")
            continue
            
        # Carregar Imagem Base
        img_pil = Image.open(img_path).convert("RGB")
        
        # Áudio Clip
        audio_clip = AudioFileClip(aud_path)
        duration = audio_clip.duration + 0.5 # Pequeno padding
        
        # Vídeo Clip Customizado (Frame Generator)
        # Passamos parâmetros para evitar closures errados
        def make_frame_wrapper(t):
            return create_frame(
                t, img_pil, settings, duration, i,
                settings['liturgyInfo'], settings['gospelRef'], settings['date']
            )
            
        video_clip =  VideoClip(make_frame=make_frame_wrapper, duration=duration)
        video_clip = video_clip.set_audio(audio_clip)
        
        clips.append(video_clip)
        st.write(f"Bloco {i+1} preparado ({duration:.1f}s)")

    # Concatenar
    final_clip = concatenate_videoclips(clips, method="compose")
    
    # Exportar
    output_filename = f"render_{settings['date'].replace('-','.')}.mp4"
    output_path = os.path.join(project_path, output_filename)
    
    # Configuração TikTok (H.264, AAC, bitrate otimizado)
    final_clip.write_videofile(
        output_path, 
        fps=30, 
        codec='libx264', 
        audio_codec='aac', 
        bitrate='2500k',
        preset='medium',
        threads=4
    )
    
    return output_path

# === UI DO RENDER QUEUE ===

# Simulação de listar pastas (Na prática seria Drive API list_folders)
if not os.path.exists(RENDER_QUEUE_DIR):
    os.makedirs(RENDER_QUEUE_DIR)

projects = [f for f in os.listdir(RENDER_QUEUE_DIR) if os.path.isdir(os.path.join(RENDER_QUEUE_DIR, f))]

st.subheader(f"Fila de Renderização ({len(projects)})")

if st.button("🔄 Atualizar Lista"):
    st.rerun()

for proj in projects:
    with st.expander(f"📁 Projeto: {proj}", expanded=False):
        p_path = os.path.join(RENDER_QUEUE_DIR, proj)
        if os.path.exists(os.path.join(p_path, "manifest.json")):
            with open(os.path.join(p_path, "manifest.json")) as f:
                s = json.load(f)
            st.json(s['visuals'], expanded=False)
            
            if st.button(f"🚀 Renderizar {proj}", key=proj):
                try:
                    out_file = render_project(p_path)
                    st.success("Vídeo Renderizado!")
                    st.video(out_file)
                    with open(out_file, 'rb') as v:
                        st.download_button("Baixar MP4", v, file_name=os.path.basename(out_file))
                except Exception as e:
                    st.error(f"Erro na renderização: {e}")
