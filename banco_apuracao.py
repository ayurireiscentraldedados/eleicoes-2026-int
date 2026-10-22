import sqlite3
import os
import pandas as pd
from datetime import datetime

"""
MÓDULO DE BANCO DE DADOS - ELEIÇÕES 2º TURNO (2026)
---------------------------------------------------
Gerencia o banco de dados SQLite local (eleicoes_2turno.db):
- Armazena o histórico cronológico de cada ciclo de apuração.
- Armazena a tabela de votação de todos os 5.571 municípios do Brasil.
- Armazena a tabela de votação das 186 cidades do Exterior.
- Disponibiliza exportação e download remoto direto para celular ou PC.
"""

DB_PATH = os.path.join(r"c:\Users\RED.AyuriReis\Downloads\Apurador_real", "eleicoes_2turno.db")

def inicializar_banco():
    """Cria as tabelas caso não existam."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Tabela de histórico de ciclos de apuração
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historico_ciclos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            escopo TEXT,
            urnas_apuradas_pct TEXT,
            votos_lula INTEGER,
            votos_flavio INTEGER,
            lider TEXT,
            diferenca INTEGER,
            total_validos INTEGER,
            cidades_processadas INTEGER
        )
    """)

    # 2. Tabela de votos municipais (Brasil - 5.571 municípios)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS votos_municipios (
            cod_ibge7 TEXT PRIMARY KEY,
            cod_tse TEXT,
            municipio TEXT,
            uf_sigla TEXT,
            estado TEXT,
            lula INTEGER,
            flavio_bolsonaro INTEGER,
            total INTEGER,
            lula_percentual TEXT,
            bolsonaro_percentual TEXT,
            diferenca INTEGER,
            vencedor TEXT,
            atualizado_em DATETIME
        )
    """)

    # 3. Tabela de votos no Exterior (186 cidades consulares)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS votos_exterior (
            cod_tse TEXT PRIMARY KEY,
            cidade TEXT,
            pais TEXT,
            uf TEXT DEFAULT 'ZZ',
            lula INTEGER,
            flavio_bolsonaro INTEGER,
            total_validos INTEGER,
            lula_percentual TEXT,
            bolsonaro_percentual TEXT,
            diferenca INTEGER,
            vencedor TEXT,
            eleitores_aptos INTEGER,
            urnas_total INTEGER,
            urnas_apuradas TEXT,
            comparecimento INTEGER,
            abstencao INTEGER,
            atualizado_em DATETIME
        )
    """)

    conn.commit()
    conn.close()

def salvar_dados_municipais(df_municipios):
    """Atualiza a tabela de municípios do Brasil e registra o ciclo."""
    if df_municipios is None or df_municipios.empty:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Upsert em lote
    for _, row in df_municipios.iterrows():
        cursor.execute("""
            INSERT INTO votos_municipios (
                cod_ibge7, cod_tse, municipio, uf_sigla, estado,
                lula, flavio_bolsonaro, total, lula_percentual,
                bolsonaro_percentual, diferenca, vencedor, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cod_ibge7) DO UPDATE SET
                lula=excluded.lula,
                flavio_bolsonaro=excluded.flavio_bolsonaro,
                total=excluded.total,
                lula_percentual=excluded.lula_percentual,
                bolsonaro_percentual=excluded.bolsonaro_percentual,
                diferenca=excluded.diferenca,
                vencedor=excluded.vencedor,
                atualizado_em=excluded.atualizado_em
        """, (
            str(row.get('cod_ibge7', '')),
            str(row.get('cod_mun', '')),
            str(row.get('Município', '')),
            str(row.get('UF_sigla', '')),
            str(row.get('Estado', '')),
            int(row.get('Lula', 0)),
            int(row.get('Flávio Bolsonaro', 0)),
            int(row.get('Total', 0)),
            str(row.get('Lula_percentual', '0,00%')),
            str(row.get('Bolsonaro_percentual', '0,00%')),
            int(row.get('Diferença', 0)),
            str(row.get('Vencedor', 'Empate')),
            agora
        ))

    # Registra no histórico de ciclos
    total_lula = int(df_municipios['Lula'].sum())
    total_flavio = int(df_municipios['Flávio Bolsonaro'].sum())
    total_val = int(df_municipios['Total'].sum())
    dif = total_lula - total_flavio
    lider = "Lula" if total_lula > total_flavio else ("Flávio Bolsonaro" if total_flavio > total_lula else "Empate")

    cursor.execute("""
        INSERT INTO historico_ciclos (
            timestamp, escopo, urnas_apuradas_pct, votos_lula, votos_flavio,
            lider, diferenca, total_validos, cidades_processadas
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        agora, 'brasil', "Em apuração", total_lula, total_flavio,
        lider, dif, total_val, len(df_municipios)
    ))

    conn.commit()
    conn.close()

def salvar_dados_exterior(df_exterior):
    """Atualiza a tabela de cidades do exterior no banco."""
    if df_exterior is None or df_exterior.empty:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for _, row in df_exterior.iterrows():
        cursor.execute("""
            INSERT INTO votos_exterior (
                cod_tse, cidade, pais, uf, lula, flavio_bolsonaro,
                total_validos, lula_percentual, bolsonaro_percentual,
                diferenca, vencedor, eleitores_aptos, urnas_total,
                urnas_apuradas, comparecimento, abstencao, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cod_tse) DO UPDATE SET
                lula=excluded.lula,
                flavio_bolsonaro=excluded.flavio_bolsonaro,
                total_validos=excluded.total_validos,
                lula_percentual=excluded.lula_percentual,
                bolsonaro_percentual=excluded.bolsonaro_percentual,
                diferenca=excluded.diferenca,
                vencedor=excluded.vencedor,
                comparecimento=excluded.comparecimento,
                abstencao=excluded.abstencao,
                urnas_apuradas=excluded.urnas_apuradas,
                atualizado_em=excluded.atualizado_em
        """, (
            str(row.get('cod_tse', '')),
            str(row.get('Cidade', '')),
            str(row.get('Pais', '')),
            'ZZ',
            int(row.get('Lula', 0)),
            int(row.get('Flávio Bolsonaro', 0)),
            int(row.get('Total_Validos', 0)),
            str(row.get('Lula_percentual', '0,00%')),
            str(row.get('Bolsonaro_percentual', '0,00%')),
            int(row.get('Diferença', 0)),
            str(row.get('Vencedor', 'Empate')),
            int(row.get('Eleitores_Aptos', 0)),
            int(row.get('Urnas_Total', 0)),
            str(row.get('Urnas_Apuradas', '0,00%')),
            int(row.get('Comparecimento', 0)),
            int(row.get('Abstencao', 0)),
            agora
        ))

    conn.commit()
    conn.close()

# Inicializa ao importar
inicializar_banco()
