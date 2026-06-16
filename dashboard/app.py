import os
import sqlite3
import hashlib
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ==================== INICIALIZAÇÃO DO BANCO ====================
DB_PATH = "data/cs2_stats.db"
RAW_PATH = "data/raw"

def init_database():
    """Cria e popula o banco se nao existir ou estiver vazio."""
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='metricas_jogador'"
    ).fetchone()
    ja_existe = (row[0] > 0) if row else False

    n_rows = 0
    if ja_existe:
        row2 = cursor.execute("SELECT COUNT(*) FROM metricas_jogador").fetchone()
        n_rows = row2[0] if row2 else 0

    conn.close()
    if ja_existe and n_rows > 0:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS jogadores (
            id INTEGER PRIMARY KEY, nome TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS times (
            id INTEGER PRIMARY KEY, nome TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS partidas (
            id INTEGER PRIMARY KEY, game_id INTEGER, torneio TEXT,
            time1_id INTEGER, time1_nome TEXT, time2_id INTEGER, time2_nome TEXT,
            score1_match INTEGER, score2_match INTEGER,
            score1_game INTEGER, score2_game INTEGER,
            mapa TEXT, data TEXT, time1_venceu INTEGER, tier TEXT
        );
        CREATE TABLE IF NOT EXISTS stats_jogador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partida_id INTEGER, jogador_id INTEGER, jogador_nome TEXT,
            time_id INTEGER, kills INTEGER, deaths INTEGER, assists INTEGER,
            adr REAL, kast REAL, kd_diff INTEGER
        );
        CREATE TABLE IF NOT EXISTS metricas_jogador (
            jogador_id INTEGER, jogador_nome TEXT, partidas INTEGER,
            kills_total INTEGER, deaths_total INTEGER, assists_total INTEGER,
            kd_ratio REAL, adr_medio REAL, kast_medio REAL,
            kd_diff_total INTEGER, vitorias INTEGER, taxa_vitoria REAL
        );
    """)
    conn.commit()
    conn.close()

    # Carregar jogadores e times
    for arquivo, tabela, cols_orig, cols_dest in [
        ('players.csv', 'jogadores', ['player_id','player_name'], ['id','nome']),
        ('teams.csv',   'times',     ['team_id','team_name'],     ['id','nome']),
    ]:
        path = f"{RAW_PATH}/{arquivo}"
        if os.path.exists(path):
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_csv(path)[cols_orig].drop_duplicates()
            df.columns = cols_dest
            df.to_sql(tabela, conn, if_exists='replace', index=False)
            conn.close()

    # Carregar partidas e stats
    for arquivo, tier in [
        ('cs2_tier1_games.csv','tier1'),
        ('cs2_tier2_games.csv','tier2'),
        ('cs2_tier3_games.csv','tier3'),
    ]:
        path = f"{RAW_PATH}/{arquivo}"
        if not os.path.exists(path):
            continue
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_csv(path)
        df = df[df['is_total'] == 0].copy()

        partidas = df[['game_id','tournament','team1_id','team1','team2_id','team2',
                        'score1_match','score2_match','score1_game','score2_game',
                        'map_name','datetime','team1_win']].copy()
        partidas.columns = ['id','torneio','time1_id','time1_nome','time2_id','time2_nome',
                            'score1_match','score2_match','score1_game','score2_game',
                            'mapa','data','time1_venceu']
        partidas['tier'] = tier
        partidas = partidas.drop_duplicates(subset='id')
        partidas.to_sql('partidas', conn, if_exists='append', index=False)

        stats_rows = []
        for _, row in df.iterrows():
            for team in ['team1','team2']:
                team_id = row[f'{team}_id']
                for i in range(1, 6):
                    player_id = row.get(f'{team}_player{i}_id')
                    kills     = row.get(f'{team}_player{i}_kills')
                    if pd.notna(player_id) and pd.notna(kills):
                        stats_rows.append({
                            'partida_id':   row['game_id'],
                            'jogador_id':   int(player_id),
                            'jogador_nome': row.get(f'{team}_player{i}'),
                            'time_id':      team_id,
                            'kills':        kills,
                            'deaths':       row.get(f'{team}_player{i}_deaths'),
                            'assists':      row.get(f'{team}_player{i}_assists'),
                            'adr':          row.get(f'{team}_player{i}_adr'),
                            'kast':         row.get(f'{team}_player{i}_kast'),
                            'kd_diff':      row.get(f'{team}_player{i}_kddiff'),
                        })
        pd.DataFrame(stats_rows).to_sql('stats_jogador', conn, if_exists='append', index=False)
        conn.close()

    # Calcular métricas
    conn = sqlite3.connect(DB_PATH)
    df_all = pd.read_sql("""
        SELECT s.jogador_id, s.jogador_nome, s.kills, s.deaths, s.assists,
               s.adr, s.kast, s.kd_diff, p.time1_venceu,
               CASE WHEN s.time_id = p.time1_id THEN 1 ELSE 0 END as jogou_no_time1
        FROM stats_jogador s JOIN partidas p ON s.partida_id = p.id
    """, conn)

    def limpar_nome(n):
        return n.split('(')[0].strip().rstrip(',').strip() if pd.notna(n) else n

    df_all['jogador_nome'] = df_all['jogador_nome'].apply(limpar_nome)
    df_all['venceu'] = (
        (df_all['jogou_no_time1']==1) & (df_all['time1_venceu']==1) |
        (df_all['jogou_no_time1']==0) & (df_all['time1_venceu']==0)
    ).astype(int)
    df_all['kd_ratio'] = df_all['kills'] / df_all['deaths'].replace(0,1)

    metricas = df_all.groupby(['jogador_id','jogador_nome']).agg(
        partidas=('kills','count'),
        kills_total=('kills','sum'),
        deaths_total=('deaths','sum'),
        assists_total=('assists','sum'),
        kd_ratio=('kd_ratio','mean'),
        adr_medio=('adr','mean'),
        kast_medio=('kast','mean'),
        kd_diff_total=('kd_diff','sum'),
        vitorias=('venceu','sum'),
    ).reset_index()
    metricas['taxa_vitoria'] = (metricas['vitorias'] / metricas['partidas'] * 100).round(1)
    metricas['kd_ratio']  = metricas['kd_ratio'].round(2)
    metricas['adr_medio'] = metricas['adr_medio'].round(1)
    metricas['kast_medio']= metricas['kast_medio'].round(1)
    cursor2 = conn.cursor()
    cursor2.execute("DROP TABLE IF EXISTS metricas_jogador")
    conn.commit()
    metricas.to_sql('metricas_jogador', conn, if_exists='append', index=False)
    conn.close()

# Rodar inicialização antes de qualquer coisa
with st.spinner("Inicializando banco de dados... (apenas na primeira execução)"):
    init_database()

ACCENT = "#00FF87"
ACCENT2 = "#8B5CF6"
BG_DARK = "#0F0F1A"
TEXT_MUTED = "#9CA3AF"

ICONS = {
    "trophy":  '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/></svg>',
    "gun":     '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h14l2-4h2v8h-2l-2-4"/><path d="M7 12v4H5l-2-4"/></svg>',
    "target":  '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>',
    "shield":  '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    "chart":   '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    "map":     '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>',
    "knife":   '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 21.5 3 10V3h7l11.5 11.5a2.121 2.121 0 0 1 0 3L17.5 21.5a2.121 2.121 0 0 1-3 0Z"/><path d="M7 7h.01"/></svg>',
    "users":   '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    "gamepad": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="6" y1="12" x2="10" y2="12"/><line x1="8" y1="10" x2="8" y2="14"/><circle cx="15" cy="12" r=".5" fill="currentColor"/><circle cx="17" cy="10" r=".5" fill="currentColor"/><path d="M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.604 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z"/></svg>',
}

MAP_COLORS = {
    "mirage":   {"bg": "#C8860033", "border": "#C88600", "icon": "🏜️"},
    "dust2":    {"bg": "#D4A01733", "border": "#D4A017", "icon": "🌵"},
    "inferno":  {"bg": "#CC330033", "border": "#CC3300", "icon": "🔥"},
    "nuke":     {"bg": "#00AA5533", "border": "#00AA55", "icon": "☢️"},
    "ancient":  {"bg": "#7B5EA733", "border": "#7B5EA7", "icon": "🏛️"},
    "anubis":   {"bg": "#B8860B33", "border": "#B8860B", "icon": "🐍"},
    "vertigo":  {"bg": "#0066CC33", "border": "#0066CC", "icon": "🏙️"},
    "overpass": {"bg": "#22886633", "border": "#228866", "icon": "🌉"},
    "train":    {"bg": "#88440033", "border": "#884400", "icon": "🚂"},
}

def get_map_style(mapa):
    mapa_lower = str(mapa).lower()
    for key, val in MAP_COLORS.items():
        if key in mapa_lower:
            return val
    return {"bg": "#2D2D4E33", "border": "#2D2D4E", "icon": "🗺️"}

def get_connection():
    return sqlite3.connect(DB_PATH)

def load_metricas():
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM metricas_jogador", conn)
    conn.close()
    return df

def load_historico_jogador(jogador_id):
    conn = get_connection()
    df = pd.read_sql(f"""
        SELECT s.kills, s.deaths, s.assists, s.adr, s.kast, s.kd_diff,
               p.mapa, p.data, p.tier,
               CASE WHEN s.time_id = p.time1_id AND p.time1_venceu = 1 THEN 1
                    WHEN s.time_id != p.time1_id AND p.time1_venceu = 0 THEN 1
                    ELSE 0 END as venceu
        FROM stats_jogador s
        JOIN partidas p ON s.partida_id = p.id
        WHERE s.jogador_id = {jogador_id}
        ORDER BY p.data
    """, conn)
    conn.close()
    return df

def get_avatar_color(nome):
    cores = ["#00FF87","#8B5CF6","#F59E0B","#EF4444","#3B82F6",
             "#10B981","#EC4899","#F97316","#06B6D4","#84CC16"]
    idx = int(hashlib.md5(nome.encode()).hexdigest(), 16) % len(cores)
    return cores[idx]

def hex_to_rgba(hex_color, alpha=0.15):
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

def normalizar(val, minv, maxv):
    if maxv == minv:
        return 50
    return round((val - minv) / (maxv - minv) * 100, 1)

def card_jogador_html(row, rank=None):
    cor = get_avatar_color(row['jogador_nome'])
    iniciais = ''.join([p[0].upper() for p in row['jogador_nome'].split()[:2]])[:2]
    rank_html = f'<span style="color:{ACCENT};font-size:12px;font-weight:700;min-width:24px;">#{rank}</span>' if rank else ''
    return f"""
    <div style="background:linear-gradient(135deg,#1A1A2E,#16213E);
        border:1px solid #2D2D4E;border-left:3px solid {cor};
        border-radius:12px;padding:12px 16px;
        display:flex;align-items:center;gap:12px;margin-bottom:8px;">
        {rank_html}
        <div style="width:40px;height:40px;border-radius:50%;
            background:linear-gradient(135deg,{cor}33,{cor}66);
            border:2px solid {cor};display:flex;align-items:center;
            justify-content:center;font-weight:800;font-size:13px;
            color:{cor};font-family:monospace;flex-shrink:0;">{iniciais}</div>
        <div style="flex:1;min-width:0;">
            <div style="font-weight:700;font-size:14px;color:#F1F5F9;
                white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{row['jogador_nome']}</div>
            <div style="color:{TEXT_MUTED};font-size:11px;">{int(row['partidas'])} partidas</div>
        </div>
        <div style="display:flex;gap:16px;align-items:center;">
            <div style="text-align:center;">
                <div style="color:{ACCENT};font-weight:800;font-size:15px;">{row['kd_ratio']:.2f}</div>
                <div style="color:{TEXT_MUTED};font-size:9px;text-transform:uppercase;">K/D</div>
            </div>
            <div style="text-align:center;">
                <div style="color:#60A5FA;font-weight:700;font-size:15px;">{row['adr_medio']:.0f}</div>
                <div style="color:{TEXT_MUTED};font-size:9px;text-transform:uppercase;">ADR</div>
            </div>
            <div style="text-align:center;">
                <div style="color:{ACCENT2};font-weight:700;font-size:15px;">{row['taxa_vitoria']:.0f}%</div>
                <div style="color:{TEXT_MUTED};font-size:9px;text-transform:uppercase;">WIN</div>
            </div>
        </div>
    </div>"""

# ==================== CONFIG ====================
st.set_page_config(page_title="CS2 Performance Analytics", page_icon="🎯", layout="wide")

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; background-color: {BG_DARK}; }}
    .stApp {{ background-color: {BG_DARK}; }}
    section[data-testid="stSidebar"] {{ background-color: #111122 !important; border-right: 1px solid #2D2D4E; }}
    .metric-card {{ background:linear-gradient(135deg,#1A1A2E,#16213E); border:1px solid #2D2D4E; border-radius:12px; padding:20px 24px; text-align:center; }}
    .metric-value {{ font-size:28px; font-weight:800; color:{ACCENT}; line-height:1.2; }}
    .metric-label {{ font-size:11px; color:{TEXT_MUTED}; text-transform:uppercase; letter-spacing:1px; margin-top:4px; }}
    .section-title {{ font-size:16px; font-weight:700; color:#F1F5F9; margin-bottom:14px; display:flex; align-items:center; gap:8px; }}
    h1, h2, h3 {{ color: #F1F5F9 !important; }}
    hr {{ border-color: #2D2D4E !important; }}
    div[data-testid="stRadio"] label {{ color: #CBD5E1 !important; }}
    .stSelectbox label, .stSlider label {{ color: #CBD5E1 !important; }}
</style>
""", unsafe_allow_html=True)

# ==================== HEADER ====================
st.markdown(f"""
<div style="background:linear-gradient(135deg,#1A1A2E 0%,#0F3460 100%);
    border:1px solid #2D2D4E;border-radius:16px;
    padding:24px 32px;margin-bottom:24px;
    display:flex;align-items:center;gap:20px;">
    <div style="background:linear-gradient(135deg,{ACCENT}22,{ACCENT}44);
        border:2px solid {ACCENT};border-radius:14px;
        padding:14px;display:flex;align-items:center;justify-content:center;">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="{ACCENT}" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <circle cx="12" cy="12" r="6"/>
            <circle cx="12" cy="12" r="2"/>
            <line x1="12" y1="2" x2="12" y2="6"/>
            <line x1="12" y1="18" x2="12" y2="22"/>
            <line x1="2" y1="12" x2="6" y2="12"/>
            <line x1="18" y1="12" x2="22" y2="12"/>
        </svg>
    </div>
    <div>
        <h1 style="margin:0;font-size:26px;font-weight:800;color:#F1F5F9;letter-spacing:-0.5px;">CS2 Performance Analytics</h1>
        <p style="margin:4px 0 0;color:{TEXT_MUTED};font-size:13px;">Análise de desempenho de jogadores profissionais · Tier 1, 2 e 3</p>
    </div>
</div>
""", unsafe_allow_html=True)

df = load_metricas()

# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown(f'<div style="padding:8px 0 16px;font-size:11px;color:{TEXT_MUTED};text-transform:uppercase;letter-spacing:1px;">Navegação</div>', unsafe_allow_html=True)
    pagina = st.radio("Navegação", ["📊 Visão Geral", "👤 Perfil do Jogador", "⚔️ Comparar Jogadores"], label_visibility="collapsed")
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(f"""
    <div style="font-size:12px;color:{TEXT_MUTED};display:flex;flex-direction:column;gap:8px;">
        <div style="display:flex;align-items:center;gap:8px;">{ICONS['users']}<span><b style="color:#CBD5E1;">{len(df):,}</b> jogadores</span></div>
        <div style="display:flex;align-items:center;gap:8px;">{ICONS['gamepad']}<span><b style="color:#CBD5E1;">{df['partidas'].sum():,}</b> partidas</span></div>
        <div style="display:flex;align-items:center;gap:8px;">{ICONS['target']}<span><b style="color:#CBD5E1;">Tier 1 · 2 · 3</b></span></div>
    </div>
    """, unsafe_allow_html=True)

# ==================== VISÃO GERAL ====================
if pagina == "📊 Visão Geral":
    df20 = df[df['partidas'] >= 20]
    col1, col2, col3, col4 = st.columns(4)
    cards = [
        (col1, ICONS['users'],   "Jogadores",          f"{len(df):,}",                ACCENT),
        (col2, ICONS['gamepad'], "Partidas Analisadas", f"{df['partidas'].sum():,}",    "#60A5FA"),
        (col3, ICONS['trophy'],  "Melhor K/D",          f"{df20['kd_ratio'].max():.2f}","#F59E0B"),
        (col4, ICONS['gun'],     "Maior ADR",           f"{df20['adr_medio'].max():.1f}","#EF4444"),
    ]
    for col, icon, label, valor, cor in cards:
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div style="color:{cor};display:flex;justify-content:center;margin-bottom:8px;">{icon}</div>
                <div class="metric-value" style="color:{cor};">{valor}</div>
                <div class="metric-label">{label}</div>
            </div>""", unsafe_allow_html=True)

    # --- FILTROS ---
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1A1A2E,#16213E);
        border:1px solid #2D2D4E;border-radius:12px;padding:18px 24px;margin-bottom:8px;">
        <div style="font-size:12px;color:{TEXT_MUTED};text-transform:uppercase;
            letter-spacing:1px;margin-bottom:14px;">🔧 Filtros</div>
    """, unsafe_allow_html=True)

    col_f1, col_f2, col_f3 = st.columns([3, 1, 1])
    with col_f1:
        min_partidas = st.slider("Mínimo de partidas", 5, 100, 20, label_visibility="visible")
    with col_f2:
        tier_sel = st.selectbox("Tier", ["Todos", "Tier 1", "Tier 2", "Tier 3"])
    with col_f3:
        metrica_rank = st.selectbox("Ranking por", ["K/D Ratio", "ADR Médio", "KAST%", "Taxa Vitória"])
    st.markdown("</div>", unsafe_allow_html=True)

    # Aplicar filtros
    df_f = df[df['partidas'] >= min_partidas].copy()
    tier_map = {"Tier 1": "tier1", "Tier 2": "tier2", "Tier 3": "tier3"}
    if tier_sel != "Todos":
        # Filtrar por tier usando as partidas
        conn = get_connection()
        jogadores_tier = pd.read_sql(f"""
            SELECT DISTINCT s.jogador_id
            FROM stats_jogador s
            JOIN partidas p ON s.partida_id = p.id
            WHERE p.tier = '{tier_map[tier_sel]}'
        """, conn)
        conn.close()
        df_f = df_f[df_f['jogador_id'].isin(jogadores_tier['jogador_id'])]

    metrica_col_map = {
        "K/D Ratio":    "kd_ratio",
        "ADR Médio":    "adr_medio",
        "KAST%":        "kast_medio",
        "Taxa Vitória": "taxa_vitoria",
    }
    col_sort = metrica_col_map[metrica_rank]

    # --- RANKINGS ---
    st.markdown("<br>", unsafe_allow_html=True)

    def card_jogador_v2(row, rank, cor_destaque, max_val, col_val, label_val):
        cor = get_avatar_color(row['jogador_nome'])
        iniciais = ''.join([p[0].upper() for p in row['jogador_nome'].split()[:2]])[:2]
        val = float(row[col_val])
        pct = min(int((val / max_val) * 100), 100) if max_val > 0 else 0
        return f"""
        <div style="background:linear-gradient(135deg,#1A1A2E,#16213E);
            border:1px solid #2D2D4E;border-left:3px solid {cor};
            border-radius:12px;padding:14px 16px;margin-bottom:8px;">
            <div style="display:flex;align-items:center;gap:12px;">
                <span style="color:{ACCENT};font-size:12px;font-weight:700;min-width:24px;">#{rank}</span>
                <div style="width:40px;height:40px;border-radius:50%;
                    background:linear-gradient(135deg,{cor}33,{cor}66);
                    border:2px solid {cor};display:flex;align-items:center;
                    justify-content:center;font-weight:800;font-size:13px;
                    color:{cor};font-family:monospace;flex-shrink:0;">{iniciais}</div>
                <div style="flex:1;min-width:0;">
                    <div style="font-weight:700;font-size:14px;color:#F1F5F9;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{row['jogador_nome']}</div>
                    <div style="color:{TEXT_MUTED};font-size:11px;">{int(row['partidas'])} partidas</div>
                </div>
                <div style="text-align:right;">
                    <div style="color:{cor_destaque};font-weight:800;font-size:18px;">{val:.2f}</div>
                    <div style="color:{TEXT_MUTED};font-size:9px;text-transform:uppercase;">{label_val}</div>
                </div>
            </div>
            <div style="margin-top:10px;background:#2D2D4E;border-radius:4px;height:3px;">
                <div style="background:linear-gradient(90deg,{cor},{cor_destaque});
                    width:{pct}%;height:3px;border-radius:4px;"></div>
            </div>
        </div>"""

    col_left, col_mid, col_right = st.columns(3)

    with col_left:
        st.markdown(f'<div class="section-title">{ICONS["trophy"]} <span style="color:{ACCENT}">Top K/D Ratio</span></div>', unsafe_allow_html=True)
        top_kd = df_f.sort_values('kd_ratio', ascending=False).head(8)
        max_kd = df_f['kd_ratio'].max()
        st.markdown("".join([card_jogador_v2(row, i+1, ACCENT, max_kd, 'kd_ratio', 'K/D')
                              for i, (_, row) in enumerate(top_kd.iterrows())]), unsafe_allow_html=True)

    with col_mid:
        st.markdown(f'<div class="section-title">{ICONS["gun"]} <span style="color:#EF4444">Top ADR Médio</span></div>', unsafe_allow_html=True)
        top_adr = df_f.sort_values('adr_medio', ascending=False).head(8)
        max_adr = df_f['adr_medio'].max()
        st.markdown("".join([card_jogador_v2(row, i+1, '#EF4444', max_adr, 'adr_medio', 'ADR')
                              for i, (_, row) in enumerate(top_adr.iterrows())]), unsafe_allow_html=True)

    with col_right:
        st.markdown(f'<div class="section-title">{ICONS["shield"]} <span style="color:{ACCENT2}">Top KAST%</span></div>', unsafe_allow_html=True)
        top_kast = df_f.sort_values('kast_medio', ascending=False).head(8)
        max_kast = df_f['kast_medio'].max()
        st.markdown("".join([card_jogador_v2(row, i+1, ACCENT2, max_kast, 'kast_medio', 'KAST%')
                              for i, (_, row) in enumerate(top_kast.iterrows())]), unsafe_allow_html=True)

    # --- SCATTER ---
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f"""
    <div class="section-title">{ICONS['target']}
        <span>K/D Ratio vs Taxa de Vitória</span>
        <span style="font-size:12px;color:{TEXT_MUTED};font-weight:400;margin-left:8px;">
            · tamanho = nº de partidas · cor = ADR médio
        </span>
    </div>
    """, unsafe_allow_html=True)
    fig = px.scatter(df_f, x='kd_ratio', y='taxa_vitoria', hover_name='jogador_nome',
                     size='partidas', color='adr_medio', color_continuous_scale='Viridis',
                     labels={'kd_ratio':'K/D Ratio','taxa_vitoria':'Taxa de Vitória (%)','adr_medio':'ADR Médio'})
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(26,26,46,0.8)',
                      font_color='#CBD5E1', height=420,
                      xaxis=dict(gridcolor='#2D2D4E'), yaxis=dict(gridcolor='#2D2D4E'),
                      coloraxis_colorbar=dict(bgcolor='rgba(26,26,46,0.8)', bordercolor='#2D2D4E'))
    st.plotly_chart(fig, width='stretch')

# ==================== PERFIL DO JOGADOR ====================
elif pagina == "👤 Perfil do Jogador":
    jogadores_lista = df.sort_values('partidas', ascending=False)['jogador_nome'].tolist()
    jogador_nome = st.selectbox("🔍 Buscar jogador", jogadores_lista)

    resultado = df[df['jogador_nome'] == jogador_nome]
    if resultado.empty:
        st.warning("Nenhum dado encontrado para este jogador.")
        st.stop()
    jogador = resultado.iloc[0]
    jogador_id = int(jogador['jogador_id'])
    historico = load_historico_jogador(jogador_id)
    cor = get_avatar_color(jogador_nome)
    iniciais = ''.join([p[0].upper() for p in jogador_nome.split()[:2]])[:2]

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1A1A2E,#16213E);
        border:1px solid #2D2D4E;border-left:4px solid {cor};
        border-radius:16px;padding:22px 28px;
        display:flex;align-items:center;gap:20px;margin:16px 0 24px;">
        <div style="width:68px;height:68px;border-radius:50%;
            background:linear-gradient(135deg,{cor}33,{cor}66);
            border:3px solid {cor};display:flex;align-items:center;
            justify-content:center;font-weight:800;font-size:24px;
            color:{cor};font-family:monospace;flex-shrink:0;">{iniciais}</div>
        <div>
            <h2 style="margin:0;font-size:22px;font-weight:800;color:#F1F5F9;">{jogador_nome}</h2>
            <div style="color:{TEXT_MUTED};font-size:12px;margin-top:4px;">{int(jogador['partidas'])} partidas analisadas</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3, col4, col5 = st.columns(5)
    stats = [
        (col1, ICONS['target'], "K/D Ratio",   f"{jogador['kd_ratio']:.2f}",        ACCENT),
        (col2, ICONS['gun'],    "ADR Médio",    f"{jogador['adr_medio']:.1f}",        "#60A5FA"),
        (col3, ICONS['shield'], "KAST%",        f"{jogador['kast_medio']:.1f}%",      ACCENT2),
        (col4, ICONS['trophy'], "Taxa Vitória", f"{jogador['taxa_vitoria']:.1f}%",    "#10B981"),
        (col5, ICONS['knife'],  "Kills Total",  f"{int(jogador['kills_total']):,}",   "#F59E0B"),
    ]
    for col, icon, label, valor, cor_val in stats:
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div style="color:{cor_val};display:flex;justify-content:center;margin-bottom:6px;">{icon}</div>
                <div class="metric-value" style="color:{cor_val};">{valor}</div>
                <div class="metric-label">{label}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f'<div class="section-title">{ICONS["chart"]} Evolução de Desempenho</div>', unsafe_allow_html=True)
        metrica_sel = st.selectbox("Métrica", ["ADR", "K/D Ratio", "KAST%", "Kills"], key="metrica_evolucao")
        historico_plot = historico.reset_index().copy()
        historico_plot['kd_ratio'] = historico_plot['kills'] / historico_plot['deaths'].replace(0, 1)
        metrica_map = {
            "ADR":       ("adr",      ACCENT,    "ADR"),
            "K/D Ratio": ("kd_ratio", "#60A5FA", "K/D Ratio"),
            "KAST%":     ("kast",     ACCENT2,   "KAST%"),
            "Kills":     ("kills",    "#F59E0B",  "Kills"),
        }
        col_key, cor_linha, y_label = metrica_map[metrica_sel]
        historico_plot['media_movel'] = historico_plot[col_key].rolling(window=5, min_periods=1).mean()
        media_geral = historico_plot[col_key].mean()

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=historico_plot.index, y=historico_plot[col_key],
            mode='lines', name=metrica_sel,
            line=dict(color=cor_linha, width=1.5),
            fill='tozeroy', fillcolor=hex_to_rgba(cor_linha, alpha=0.08), opacity=0.6
        ))
        fig.add_trace(go.Scatter(
            x=historico_plot.index, y=historico_plot['media_movel'],
            mode='lines', name='Média móvel (5)',
            line=dict(color=cor_linha, width=2.5),
        ))
        fig.add_hline(y=media_geral, line_dash='dash', line_color='#EF4444',
                      annotation_text=f"Média: {media_geral:.2f}",
                      annotation_font_color='#EF4444', annotation_position="top left")
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(26,26,46,0.8)',
            font_color='#CBD5E1', height=300,
            xaxis=dict(gridcolor='#2D2D4E', title='Partida'),
            yaxis=dict(gridcolor='#2D2D4E', title=y_label),
            legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(size=11)),
            margin=dict(t=20)
        )
        st.plotly_chart(fig, width='stretch')

    with col2:
        st.markdown(f'<div class="section-title">{ICONS["map"]} ADR por Mapa</div>', unsafe_allow_html=True)
        mapa_stats = historico.groupby('mapa').agg(
            partidas=('kills', 'count'),
            adr_medio=('adr', 'mean')
        ).reset_index().sort_values('adr_medio', ascending=False)

        mapa_html = ""
        for _, row in mapa_stats.iterrows():
            ms = get_map_style(row['mapa'])
            pct = min(int((row['adr_medio'] / 120) * 100), 100)
            mapa_html += f"""
            <div style="background:{ms['bg']};border:1px solid {ms['border']};
                border-radius:8px;padding:10px 14px;margin-bottom:6px;
                display:flex;align-items:center;gap:12px;">
                <span style="font-size:18px;">{ms['icon']}</span>
                <div style="flex:1;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                        <span style="color:#F1F5F9;font-size:13px;font-weight:600;">{row['mapa']}</span>
                        <span style="color:{ms['border']};font-size:13px;font-weight:700;">{row['adr_medio']:.0f} ADR</span>
                    </div>
                    <div style="background:#2D2D4E;border-radius:4px;height:4px;">
                        <div style="background:{ms['border']};width:{pct}%;height:4px;border-radius:4px;"></div>
                    </div>
                </div>
            </div>"""
        st.markdown(mapa_html, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f'<div class="section-title">{ICONS["chart"]} Distribuição de Kills por Partida</div>', unsafe_allow_html=True)
    fig = px.histogram(historico, x='kills', nbins=25, color_discrete_sequence=[ACCENT2],
                       labels={'kills':'Kills por Partida','count':'Frequência'})
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(26,26,46,0.8)',
                      font_color='#CBD5E1', height=260,
                      xaxis=dict(gridcolor='#2D2D4E'), yaxis=dict(gridcolor='#2D2D4E'), bargap=0.1)
    st.plotly_chart(fig, width='stretch')

# ==================== COMPARAR JOGADORES ====================
elif pagina == "⚔️ Comparar Jogadores":
    jogadores_lista = df.sort_values('partidas', ascending=False)['jogador_nome'].tolist()

    col1, col2 = st.columns(2)
    with col1:
        j1_nome = st.selectbox("Jogador 1", jogadores_lista, index=0)
    with col2:
        j2_nome = st.selectbox("Jogador 2", jogadores_lista, index=1)

    r1 = df[df['jogador_nome'] == j1_nome]
    r2 = df[df['jogador_nome'] == j2_nome]
    if r1.empty or r2.empty:
        st.warning("Dados insuficientes para comparação.")
        st.stop()
    j1 = r1.iloc[0]
    j2 = r2.iloc[0]
    cor1 = get_avatar_color(j1_nome)
    cor2 = get_avatar_color(j2_nome)

    col1, col2 = st.columns(2)
    for col, jogador, cor in [(col1, j1, cor1), (col2, j2, cor2)]:
        iniciais = ''.join([p[0].upper() for p in jogador['jogador_nome'].split()[:2]])[:2]
        with col:
            st.markdown(f"""
            <div style="background:linear-gradient(135deg,#1A1A2E,#16213E);
                border:1px solid #2D2D4E;border-top:3px solid {cor};
                border-radius:12px;padding:18px;
                display:flex;align-items:center;gap:14px;margin-bottom:16px;">
                <div style="width:52px;height:52px;border-radius:50%;
                    background:linear-gradient(135deg,{cor}33,{cor}66);
                    border:2px solid {cor};display:flex;align-items:center;
                    justify-content:center;font-weight:800;font-size:18px;
                    color:{cor};font-family:monospace;">{iniciais}</div>
                <div>
                    <div style="font-size:17px;font-weight:800;color:#F1F5F9;">{jogador['jogador_nome']}</div>
                    <div style="color:{TEXT_MUTED};font-size:12px;margin-top:2px;">{int(jogador['partidas'])} partidas</div>
                </div>
            </div>""", unsafe_allow_html=True)

    metricas_comp = [
        ('kd_ratio',     ICONS['target'], 'K/D Ratio',     ACCENT),
        ('adr_medio',    ICONS['gun'],    'ADR Médio',     '#60A5FA'),
        ('kast_medio',   ICONS['shield'], 'KAST%',         ACCENT2),
        ('taxa_vitoria', ICONS['trophy'], 'Taxa Vitória%', '#10B981'),
    ]
    cols = st.columns(4)
    for col, (metrica, icon, label, cor) in zip(cols, metricas_comp):
        v1, v2 = float(j1[metrica]), float(j2[metrica])
        cor_v = cor1 if v1 > v2 else cor2
        venc = j1_nome if v1 > v2 else j2_nome
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div style="color:{cor};display:flex;justify-content:center;margin-bottom:6px;">{icon}</div>
                <div style="font-size:11px;color:{TEXT_MUTED};text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">{label}</div>
                <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
                    <div style="color:{cor1};font-weight:800;font-size:18px;">{v1:.2f}</div>
                    <div style="color:{TEXT_MUTED};font-size:11px;">vs</div>
                    <div style="color:{cor2};font-weight:800;font-size:18px;">{v2:.2f}</div>
                </div>
                <div style="margin-top:8px;font-size:11px;color:{cor_v};font-weight:600;">▲ {venc}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f'<div class="section-title">{ICONS["target"]} Radar de Desempenho</div>', unsafe_allow_html=True)

    metricas_radar = ['kd_ratio', 'adr_medio', 'kast_medio', 'taxa_vitoria']
    categorias = ['K/D Ratio', 'ADR / 10', 'KAST%', 'Vitórias%']
    mins = [df[m].min() for m in metricas_radar]
    maxs = [df[m].max() for m in metricas_radar]

    vals1 = [normalizar(float(j1[m]), mn, mx) for m, mn, mx in zip(metricas_radar, mins, maxs)]
    vals2 = [normalizar(float(j2[m]), mn, mx) for m, mn, mx in zip(metricas_radar, mins, maxs)]

    fig = go.Figure()
    for nome, vals, cor in [(j1_nome, vals1, cor1), (j2_nome, vals2, cor2)]:
        fig.add_trace(go.Scatterpolar(
            r=vals, theta=categorias, fill='toself',
            name=nome, line_color=cor,
            fillcolor=hex_to_rgba(cor, alpha=0.2)
        ))
    fig.update_layout(
        polar=dict(
            bgcolor='rgba(26,26,46,0.8)',
            radialaxis=dict(visible=True, range=[0, 100], gridcolor='#2D2D4E',
                            color='#9CA3AF', tickfont=dict(size=9)),
            angularaxis=dict(gridcolor='#2D2D4E', color='#CBD5E1')
        ),
        paper_bgcolor='rgba(0,0,0,0)',
        font_color='#CBD5E1', height=480,
        legend=dict(bgcolor='rgba(26,26,46,0.8)', bordercolor='#2D2D4E', borderwidth=1)
    )
    st.plotly_chart(fig, use_container_width=True)
