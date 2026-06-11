import sqlite3
import pandas as pd
import os

DB_PATH = "data/cs2_stats.db"
RAW_PATH = "data/raw"

def create_database():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS jogadores (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS times (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS torneios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS partidas (
            id INTEGER PRIMARY KEY,
            game_id INTEGER,
            torneio TEXT,
            time1_id INTEGER,
            time1_nome TEXT,
            time2_id INTEGER,
            time2_nome TEXT,
            score1_match INTEGER,
            score2_match INTEGER,
            score1_game INTEGER,
            score2_game INTEGER,
            mapa TEXT,
            data TEXT,
            time1_venceu INTEGER,
            tier TEXT,
            FOREIGN KEY (time1_id) REFERENCES times(id),
            FOREIGN KEY (time2_id) REFERENCES times(id)
        );

        CREATE TABLE IF NOT EXISTS stats_jogador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partida_id INTEGER,
            jogador_id INTEGER,
            jogador_nome TEXT,
            time_id INTEGER,
            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,
            adr REAL,
            kast REAL,
            kd_diff INTEGER,
            FOREIGN KEY (partida_id) REFERENCES partidas(id),
            FOREIGN KEY (jogador_id) REFERENCES jogadores(id)
        );
    """)

    conn.commit()
    conn.close()
    print("✅ Banco de dados criado com sucesso!")

def load_jogadores():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_csv(f"{RAW_PATH}/players.csv")
    df = df[['player_id', 'player_name']].drop_duplicates()
    df.columns = ['id', 'nome']
    df.to_sql('jogadores', conn, if_exists='replace', index=False)
    conn.close()
    print(f"✅ Jogadores carregados: {len(df)} registros")

def load_times():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_csv(f"{RAW_PATH}/teams.csv")
    df = df[['team_id', 'team_name']].drop_duplicates()
    df.columns = ['id', 'nome']
    df.to_sql('times', conn, if_exists='replace', index=False)
    conn.close()
    print(f"✅ Times carregados: {len(df)} registros")

def load_partidas_e_stats(arquivo, tier):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_csv(f"{RAW_PATH}/{arquivo}")

    # Filtrar apenas linhas de jogos individuais (não totais de match)
    df = df[df['is_total'] == 0].copy()

    # --- PARTIDAS ---
    partidas = df[[
        'game_id', 'tournament', 'team1_id', 'team1', 'team2_id', 'team2',
        'score1_match', 'score2_match', 'score1_game', 'score2_game',
        'map_name', 'datetime', 'team1_win'
    ]].copy()
    partidas.columns = [
        'id', 'torneio', 'time1_id', 'time1_nome', 'time2_id', 'time2_nome',
        'score1_match', 'score2_match', 'score1_game', 'score2_game',
        'mapa', 'data', 'time1_venceu'
    ]
    partidas['tier'] = tier
    partidas = partidas.drop_duplicates(subset='id')
    partidas.to_sql('partidas', conn, if_exists='append', index=False)

    # --- STATS POR JOGADOR ---
    stats_rows = []
    for _, row in df.iterrows():
        for team in ['team1', 'team2']:
            team_id = row[f'{team}_id']
            for i in range(1, 6):
                player_id = row.get(f'{team}_player{i}_id')
                player_name = row.get(f'{team}_player{i}')
                kills = row.get(f'{team}_player{i}_kills')
                deaths = row.get(f'{team}_player{i}_deaths')
                assists = row.get(f'{team}_player{i}_assists')
                adr = row.get(f'{team}_player{i}_adr')
                kast = row.get(f'{team}_player{i}_kast')
                kd_diff = row.get(f'{team}_player{i}_kddiff')

                if pd.notna(player_id) and pd.notna(kills):
                    stats_rows.append({
                        'partida_id': row['game_id'],
                        'jogador_id': int(player_id),
                        'jogador_nome': player_name,
                        'time_id': team_id,
                        'kills': kills,
                        'deaths': deaths,
                        'assists': assists,
                        'adr': adr,
                        'kast': kast,
                        'kd_diff': kd_diff
                    })

    stats_df = pd.DataFrame(stats_rows)
    stats_df.to_sql('stats_jogador', conn, if_exists='append', index=False)
    conn.close()
    print(f"✅ {tier} carregado: {len(partidas)} partidas | {len(stats_df)} stats de jogadores")

def run():
    print("🚀 Iniciando carga do banco de dados...\n")
    create_database()
    load_jogadores()
    load_times()
    load_partidas_e_stats('cs2_tier1_games.csv', 'tier1')
    load_partidas_e_stats('cs2_tier2_games.csv', 'tier2')
    load_partidas_e_stats('cs2_tier3_games.csv', 'tier3')
    print("\n✅ Carga completa finalizada!")

if __name__ == "__main__":
    run()