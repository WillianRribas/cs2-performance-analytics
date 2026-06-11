import sqlite3
import pandas as pd

DB_PATH = "data/cs2_stats.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def limpar_nome(nome):
    """Remove informações extras do nome, mantendo apenas o nickname."""
    if pd.isna(nome):
        return nome
    return nome.split('(')[0].strip().rstrip(',').strip()

def calcular_metricas():
    conn = get_connection()

    print("📊 Calculando métricas por jogador...\n")

    df = pd.read_sql("""
        SELECT
            s.jogador_id,
            s.jogador_nome,
            s.kills,
            s.deaths,
            s.assists,
            s.adr,
            s.kast,
            s.kd_diff,
            p.tier,
            p.time1_venceu,
            CASE WHEN s.time_id = p.time1_id THEN 1 ELSE 0 END as jogou_no_time1
        FROM stats_jogador s
        JOIN partidas p ON s.partida_id = p.id
    """, conn)

    # Limpar nomes
    df['jogador_nome'] = df['jogador_nome'].apply(limpar_nome)

    # Calcular vitória do jogador
    df['venceu'] = (
        (df['jogou_no_time1'] == 1) & (df['time1_venceu'] == 1) |
        (df['jogou_no_time1'] == 0) & (df['time1_venceu'] == 0)
    ).astype(int)

    # Calcular K/D ratio
    df['kd_ratio'] = df['kills'] / df['deaths'].replace(0, 1)

    # Agrupar métricas por jogador
    metricas = df.groupby(['jogador_id', 'jogador_nome']).agg(
        partidas=('kills', 'count'),
        kills_total=('kills', 'sum'),
        deaths_total=('deaths', 'sum'),
        assists_total=('assists', 'sum'),
        kd_ratio=('kd_ratio', 'mean'),
        adr_medio=('adr', 'mean'),
        kast_medio=('kast', 'mean'),
        kd_diff_total=('kd_diff', 'sum'),
        vitorias=('venceu', 'sum'),
    ).reset_index()

    # Taxa de vitória
    metricas['taxa_vitoria'] = (metricas['vitorias'] / metricas['partidas'] * 100).round(1)

    # Arredondar valores
    metricas['kd_ratio'] = metricas['kd_ratio'].round(2)
    metricas['adr_medio'] = metricas['adr_medio'].round(1)
    metricas['kast_medio'] = metricas['kast_medio'].round(1)

    # Salvar no banco
    metricas.to_sql('metricas_jogador', conn, if_exists='replace', index=False)

    print(f"✅ Métricas calculadas para {len(metricas)} jogadores!")
    print("\nTop 10 jogadores por K/D ratio (mínimo 20 partidas):\n")

    top10 = metricas[metricas['partidas'] >= 20].sort_values('kd_ratio', ascending=False).head(10)
    print(top10[['jogador_nome', 'partidas', 'kd_ratio', 'adr_medio', 'kast_medio', 'taxa_vitoria']].to_string(index=False))

    conn.close()
    return metricas

if __name__ == "__main__":
    calcular_metricas()