import streamlit as st
import json
import os
import numpy as np
from moviepy.editor import VideoClip, AudioFileClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont
import math

# === CONFIGURAÇÃO DA PÁGINA ===
st.set_page_config(page_title="Render Farm - TikTok Studio", layout="wide")

# Diretório onde o GAS salva os arquivos (Local ou Sync com Drive)
# Se estiver usando Google Drive API, você precisará baixar a pasta 'TikTok_Render_Queue' aqui.
RENDER_QUEUE_DIR = "TikTok_Render_Queue" 

st.title("🎬 Render Farm - Liturgia TikTok")
st.markdown("Renderizador Server-Side usando MoviePy + Pillow.")

# === HELPER: DESENHAR RETÂNGULO ARREDONDADO ===
def rounded_rectangle(draw, xy, corner_radius, fill=None, outline=None):
    upper_left_point = xy[0]
    bottom_right_point = xy[1]
    draw.rectangle(
        [(upper_left_point[0], upper_left_point[1] + corner_radius),
         (bottom_right_point[0], bottom_right_point[1] - corner_radius)],
        fill=fill, outline=outline
    )
    draw.rectangle(
        [(upper_left_point[0] + corner_radius, upper_left_point[1]),
         (bottom_right_point[0] - corner_radius, bottom_right_point[1])],
        fill=fill, outline=outline
    )
    draw.pieslice([upper_left_point[0], upper_left_point[1], upper_left_point[0] + corner_radius * 2, upper_left_point[1] + corner_radius * 2], 180, 270, fill=fill, outline=outline)
    draw.pieslice([bottom_right_point[0] - corner_radius * 2, bottom_right_point[1] - corner_radius * 2, bottom_right_point[0], bottom_right_point[1]], 0, 90, fill=fill, outline=outline)
    draw.pieslice([upper_left_point[0], bottom_right_point[1] - corner_radius * 2, upper_left_point[0] + corner_radius * 2, bottom_right_point[1]], 90, 180, fill=fill, outline=outline)
    draw.pieslice([bottom_right_point[0] - corner_radius * 2, upper_left_point[1], bottom_right_point[0], upper_left_point[1] + corner_radius * 2], 270, 360, fill=fill, outline=outline)

# === CORE: GERADOR DE FRAMES ===
def create_frame(t, img_pil, settings, audio_duration, block_index, liturgy_info, gospel_ref, date_str):
    W, H = 1080, 1920
    
    # 1. Zoom (Ken Burns)
    motion_speed = float(settings['visuals'].get('motionSpeed', 2))
    scale = 1.0 + (t * (motion_speed * 0.003)) if settings['visuals'].get('motionEnabled', True) else 1.0
    
    new_w = int(W * scale)
    new_h = int(H * scale)
    img_resized = img_pil.resize((new_w, new_h), Image.LANCZOS)
    
    left = (new_w - W) // 2
    top = (new_h - H) // 2
    bg = img_resized.crop((left, top, left + W, top + H))
    
    canvas = bg.convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    
    # 2. Partículas Douradas
    if settings['visuals'].get('particlesEnabled', True):
        for _ in range(int(settings['visuals'].get('particlesCount', 50))):
            x = np.random.randint(0, W)
            y = np.random.randint(0, H)
            r = np.random.randint(1, 4)
            alpha = np.random.randint(100, 200)
            draw.ellipse([x, y, x+r, y+r], fill=(255, 223, 128, alpha))

    # 3. Textos e Fade
    center_x = W // 2
    y_pos = int(settings['visuals'].get('textYPos', 100))
    
    fade_dur = 1.0
    slide_dur = float(settings['visuals'].get('slideDuration', 10))
    alpha_text = 255
    y_offset = 0
    
    if t < fade_dur:
        prog = t / fade_dur
        alpha_text = int(255 * prog)
        y_offset = (1 - prog) * 50
    elif settings['visuals'].get('slideEnabled', True) and t > slide_dur:
        prog = (t - slide_dur) / 1.0
        if prog > 1: prog = 1
        alpha_text = int(255 * (1 - prog))
        y_offset = prog * 50

    # Título do Bloco
    title_titles = ["EVANGELHO", "REFLEXÃO", "APLICAÇÃO", "ORAÇÃO"]
    curr_title = title_titles[block_index] if block_index < 4 else ""
    
    # Carregar Fontes
    try:
        font_title = ImageFont.truetype("AlegreyaSans-Bold.ttf", int(settings['visuals'].get('titleSize', 150)))
        font_sub = ImageFont.truetype("AlegreyaSans-Regular.ttf", int(settings['visuals'].get('subtitleSize', 80)))
        font_sub_sm = ImageFont.truetype("AlegreyaSans-Italic.ttf", int(settings['visuals'].get('subtitleSize', 80)) * 0.8)
    except:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_sub_sm = ImageFont.load_default()

    # Desenhar Título Principal (Persistente)
    persist_alpha = 255 if t >= fade_dur else int(255 * (t/fade_dur))
    if persist_alpha > 0:
        t_bbox = draw.textbbox((0,0), curr_title, font=font_title)
        t_w = t_bbox[2] - t_bbox[0] + 80
        t_h = int(settings['visuals'].get('titleSize', 150)) * 1.4
        
        rect_color = (85, 85, 85, int(128 * (persist_alpha/255)))
        rounded_rectangle(draw, [(center_x - t_w/2, y_pos), (center_x + t_w/2, y_pos + t_h)], 20, fill=rect_color)
        draw.text((center_x, y_pos + t_h/2), curr_title, font=font_title, fill=(255,255,255,persist_alpha), anchor="mm")

    # Desenhar Subtítulos (Transientes)
    if alpha_text > 0:
        curr_y = y_pos + y_offset + (int(settings['visuals'].get('titleSize', 150)) * 1.4) + 15
        sub_h = int(settings['visuals'].get('subtitleSize', 80)) * 1.4
        
        # Formatar Data
        date_display = date_str
        try:
            from datetime import datetime
            d = datetime.strptime(date_str, "%Y-%m-%d")
            # Mapeamento simples dias da semana PT
            days = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            day_name = days[d.weekday()]
            date_display = f"{day_name}, {d.day}.{d.month}.{d.year}"
        except: pass

        lit_text = liturgy_info.get('liturgia', 'Tempo Comum')
        # Limpeza básica do texto liturgia
        lit_text = lit_text.replace("Semana do ", "").replace("-feira", "")

        sub_data = [
            (date_display, font_sub),
            (gospel_ref, font_sub),
            (lit_text, font_sub_sm)
        ]
        
        for text, fnt in sub_data:
            s_bbox = draw.textbbox((0,0), str(text), font=fnt)
            s_w = s_bbox[2] - s_bbox[0] + 60
            
            rect_col = (119, 119, 119, int(128 * (alpha_text/255)))
            rounded_rectangle(draw, [(center_x - s_w/2, curr_y), (center_x + s_w/2, curr_y + sub_h)], 10, fill=rect_col)
            draw.text((center_x, curr_y + sub_h/2), str(text), font=fnt, fill=(255,255,255,alpha_text), anchor="mm")
            curr_y += sub_h + 15

    # 4. Waveform
    wave_bars = int(settings['visuals'].get('waveformWidth', 24))
    wave_y = H // 2
    wave_opac = int(float(settings['visuals'].get('waveformOpacity', 60)) * 2.55)
    wave_amp = float(settings['visuals'].get('waveformAmplitude', 0.3))
    
    for i in range(wave_bars):
        val = (math.sin(i * 0.5 + t * 5) + 1) * 30 * wave_amp + 10
        val += np.random.randint(0, 10) # Noise
        bar_w = 15
        gap = 8
        
        xr = center_x + (i * (bar_w + gap)) + gap/2
        draw.rectangle([xr, wave_y - val/2, xr + bar_w, wave_y + val/2], fill=(255,255,255, wave_opac))
        xl = center_x - ((i+1) * (bar_w + gap)) + gap/2
        draw.rectangle([xl, wave_y - val/2, xl + bar_w, wave_y + val/2], fill=(255,255,255, wave_opac))

    out = Image.alpha_composite(canvas, overlay)
    return np.array(out)

# === PROCESSADOR DO PROJETO ===
def render_project(project_path):
    # Carregar Configurações
    manifest_path = os.path.join(project_path, "manifest.json")
    if not os.path.exists(manifest_path):
        st.error("Arquivo manifest.json não encontrado.")
        return None

    with open(manifest_path, 'r') as f:
        settings = json.load(f)
        
    clips = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i in range(4):
        status_text.text(f"Processando Bloco {i+1}/4...")
        img_path = os.path.join(project_path, f"image_{i}.png")
        aud_path = os.path.join(project_path, f"audio_{i}.wav")
        
        if not os.path.exists(img_path) or not os.path.exists(aud_path):
            st.warning(f"Arquivos ausentes para bloco {i}. Pulando.")
            continue
            
        img_pil = Image.open(img_path).convert("RGB")
        audio_clip = AudioFileClip(aud_path)
        duration = audio_clip.duration + 0.5
        
        # Closure para passar argumentos ao frame generator
        def make_frame_wrapper(t):
            return create_frame(
                t, img_pil, settings, duration, i,
                settings['liturgyInfo'], settings['gospelRef'], settings['date']
            )
            
        video_clip = VideoClip(make_frame=make_frame_wrapper, duration=duration)
        video_clip = video_clip.set_audio(audio_clip)
        clips.append(video_clip)
        
        progress_bar.progress((i+1)/4)

    if not clips:
        return None

    status_text.text("Concatenando e codificando MP4 (Isso pode demorar)...")
    final_clip = concatenate_videoclips(clips, method="compose")
    
    output_filename = f"render_{os.path.basename(project_path)}.mp4"
    output_path = os.path.join(project_path, output_filename)
    
    # Renderização Final
    final_clip.write_videofile(
        output_path, 
        fps=24, # FPS reduzido para velocidade
        codec='libx264', 
        audio_codec='aac', 
        bitrate='2500k',
        preset='ultrafast', # Preset rápido para teste
        threads=4
    )
    
    status_text.text("Concluído!")
    return output_path

# === INTERFACE DO STREAMLIT ===

if not os.path.exists(RENDER_QUEUE_DIR):
    os.makedirs(RENDER_QUEUE_DIR)

# Listar pastas de projetos
projects = sorted([f for f in os.listdir(RENDER_QUEUE_DIR) if os.path.isdir(os.path.join(RENDER_QUEUE_DIR, f))], reverse=True)

st.sidebar.header("Fila de Projetos")
if st.sidebar.button("🔄 Atualizar Lista"):
    st.rerun()

if not projects:
    st.info("Nenhum projeto encontrado na fila. Envie dados pelo Frontend.")

for proj in projects:
    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader(f"📁 {proj}")
    with col2:
        if st.button(f"Renderizar", key=f"btn_{proj}"):
            with st.spinner('Renderizando vídeo...'):
                p_path = os.path.join(RENDER_QUEUE_DIR, proj)
                try:
                    out_file = render_project(p_path)
                    if out_file and os.path.exists(out_file):
                        st.success("Sucesso!")
                        st.video(out_file)
                        with open(out_file, 'rb') as f:
                            st.download_button("Baixar MP4", f, file_name=os.path.basename(out_file))
                    else:
                        st.error("Falha na renderização.")
                except Exception as e:
                    st.error(f"Erro: {e}")
