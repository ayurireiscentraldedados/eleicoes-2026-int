import os
import sys
import time
import json
import sqlite3
import threading
from datetime import datetime, timedelta
import urllib3
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

from contextlib import asynccontextmanager
import fastapi
from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import uvicorn

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Garante suporte a UTF-8 no Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ==========================================
# DIRETÓRIOS E CONSTANTES
# ==========================================
BASE_DIR = r"c:\Users\RED.AyuriReis\Downloads\Apurador_real"
if not os.path.exists(BASE_DIR):
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DIC_EXTERIOR_PATH = os.path.join(BASE_DIR, "dicionario_cidades_exterior.csv")
DIC_MUNICIPIOS_PATH = os.path.join(BASE_DIR, "dicionario_municipios_brasil.csv")
DB_PATH = os.path.join(BASE_DIR, "eleicoes_2turno.db")
CREDENCIAIS_PATH = os.path.join(BASE_DIR, "credentials.json")
# Se as credenciais vierem por variável de ambiente (nuvem), salva no arquivo
if os.environ.get('GOOGLE_CREDENTIALS_JSON'):
    try:
        with open(CREDENCIAIS_PATH, 'w', encoding='utf-8') as f:
            f.write(os.environ['GOOGLE_CREDENTIALS_JSON'])
    except Exception as e:
        print(f"Aviso ao gravar credenciais da nuvem: {e}")

if not os.path.exists(CREDENCIAIS_PATH):
    CREDENCIAIS_PATH = os.path.join(BASE_DIR, "Script_2", "credentials.json")

PASTA_RECORTES = os.path.join(BASE_DIR, "recortes_gerados_2turno")
os.makedirs(PASTA_RECORTES, exist_ok=True)

CSV_EXTERIOR_PATH = os.path.join(PASTA_RECORTES, "mapa_exterior_presidentes_2turno.csv")
CSV_BRASIL_PATH = os.path.join(PASTA_RECORTES, "mapa_brasil_presidentes_2turno.csv")

LINK_GOOGLE_SHEETS = "https://docs.google.com/spreadsheets/d/1uUmAveUktR3qyU62dmpyuf2wEaRgKIJMFzYOZYuXsho"

ELEICAO_ID = "6258"  # 2º Turno Oficial TSE
CARGO_ID = "c0001"

UF_TO_REGION = {
    'RO': ('1', 'Norte'), 'AC': ('1', 'Norte'), 'AM': ('1', 'Norte'), 'RR': ('1', 'Norte'),
    'PA': ('1', 'Norte'), 'AP': ('1', 'Norte'), 'TO': ('1', 'Norte'),
    'MA': ('2', 'Nordeste'), 'PI': ('2', 'Nordeste'), 'CE': ('2', 'Nordeste'), 'RN': ('2', 'Nordeste'),
    'PB': ('2', 'Nordeste'), 'PE': ('2', 'Nordeste'), 'AL': ('2', 'Nordeste'), 'SE': ('2', 'Nordeste'),
    'BA': ('2', 'Nordeste'),
    'MG': ('3', 'Sudeste'), 'ES': ('3', 'Sudeste'), 'RJ': ('3', 'Sudeste'), 'SP': ('3', 'Sudeste'),
    'PR': ('4', 'Sul'), 'SC': ('4', 'Sul'), 'RS': ('4', 'Sul'),
    'MS': ('5', 'Centro-oeste'), 'MT': ('5', 'Centro-oeste'), 'GO': ('5', 'Centro-oeste'), 'DF': ('5', 'Centro-oeste'),
}
   # Presidente

HEADERS_TSE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

# ==========================================
# BANCO DE DADOS LOCAL (SQLite)
# ==========================================
def inicializar_banco():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
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
    cur.execute("""
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
            brancos INTEGER DEFAULT 0,
            nulos INTEGER DEFAULT 0,
            atualizado_em DATETIME
        )
    """)
    # Auto-migração caso a tabela tenha sido criada anteriormente sem brancos/nulos
    try:
        colunas_ext = [row[1] for row in cur.execute("PRAGMA table_info(votos_exterior)").fetchall()]
        if "brancos" not in colunas_ext:
            cur.execute("ALTER TABLE votos_exterior ADD COLUMN brancos INTEGER DEFAULT 0")
        if "nulos" not in colunas_ext:
            cur.execute("ALTER TABLE votos_exterior ADD COLUMN nulos INTEGER DEFAULT 0")
    except Exception as e:
        print(f"Aviso migração colunas: {e}")

    cur.execute("""
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
            diferenca TEXT,
            vencedor TEXT,
            urnas_apuradas TEXT,
            brancos INTEGER DEFAULT 0,
            nulos INTEGER DEFAULT 0,
            abstencao INTEGER DEFAULT 0,
            comparecimento INTEGER DEFAULT 0,
            eleitores_aptos INTEGER DEFAULT 0,
            atualizado_em DATETIME
        )
    """)
    try:
        colunas_br = [row[1] for row in cur.execute("PRAGMA table_info(votos_municipios)").fetchall()]
        for col_name, col_type in [
            ("urnas_apuradas", "TEXT"),
            ("brancos", "INTEGER DEFAULT 0"),
            ("nulos", "INTEGER DEFAULT 0"),
            ("abstencao", "INTEGER DEFAULT 0"),
            ("comparecimento", "INTEGER DEFAULT 0"),
            ("eleitores_aptos", "INTEGER DEFAULT 0")
        ]:
            if col_name not in colunas_br:
                cur.execute(f"ALTER TABLE votos_municipios ADD COLUMN {col_name} {col_type}")
    except Exception as e:
        print(f"Aviso migracao colunas votos_municipios: {e}")
    conn.commit()
    conn.close()

def salvar_exterior_sqlite(df):
    if df is None or df.empty:
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for _, r in df.iterrows():
        cur.execute("""
            INSERT INTO votos_exterior (
                cod_tse, cidade, pais, uf, lula, flavio_bolsonaro,
                total_validos, lula_percentual, bolsonaro_percentual,
                diferenca, vencedor, eleitores_aptos, urnas_total,
                urnas_apuradas, comparecimento, abstencao, brancos, nulos, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                brancos=excluded.brancos,
                nulos=excluded.nulos,
                atualizado_em=excluded.atualizado_em
        """, (
            str(r.get('cod_tse', '')), str(r.get('Cidade', '')), str(r.get('Pais', '')), 'ZZ',
            int(r.get('Lula', 0)), int(r.get('Flávio Bolsonaro', 0)), int(r.get('Total_Validos', 0)),
            str(r.get('Lula_percentual', '0,00%')), str(r.get('Bolsonaro_percentual', '0,00%')),
            int(r.get('Diferença', 0)), str(r.get('Vencedor', 'Empate')),
            int(r.get('Eleitores_Aptos', 0)), int(r.get('Urnas_Total', 0)),
            str(r.get('Urnas_Apuradas', '0,00%')), int(r.get('Comparecimento', 0)),
            int(r.get('Abstencao', 0)), int(r.get('Brancos', 0)), int(r.get('Nulos', 0)),
            agora
        ))
    conn.commit()
    conn.close()

def salvar_brasil_sqlite(df):
    if df is None or df.empty:
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for _, r in df.iterrows():
        cur.execute("""
            INSERT INTO votos_municipios (
                cod_ibge7, cod_tse, municipio, uf_sigla, estado,
                lula, flavio_bolsonaro, total, lula_percentual,
                bolsonaro_percentual, diferenca, vencedor,
                urnas_apuradas, brancos, nulos, abstencao, comparecimento, eleitores_aptos,
                atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cod_ibge7) DO UPDATE SET
                lula=excluded.lula,
                flavio_bolsonaro=excluded.flavio_bolsonaro,
                total=excluded.total,
                lula_percentual=excluded.lula_percentual,
                bolsonaro_percentual=excluded.bolsonaro_percentual,
                diferenca=excluded.diferenca,
                vencedor=excluded.vencedor,
                urnas_apuradas=excluded.urnas_apuradas,
                brancos=excluded.brancos,
                nulos=excluded.nulos,
                abstencao=excluded.abstencao,
                comparecimento=excluded.comparecimento,
                eleitores_aptos=excluded.eleitores_aptos,
                atualizado_em=excluded.atualizado_em
        """, (
            str(r.get('cod_ibge7', '')), str(r.get('cod_mun', '')), str(r.get('Município', '')),
            str(r.get('UF_sigla', '')), str(r.get('Estado', '')),
            int(r.get('Lula', 0)), int(r.get('Flávio Bolsonaro', 0)), int(r.get('Total_Validos', r.get('Total', 0))),
            str(r.get('Lula_percentual', '0,00%')), str(r.get('Bolsonaro_percentual', '0,00%')),
            str(r.get('Diferença', '0,00')), str(r.get('Vencedor', 'Empate')),
            str(r.get('Urnas_Pct', '0,00%')),
            int(r.get('Brancos', 0)), int(r.get('Nulos', 0)),
            int(r.get('Abstencoes', 0)), int(r.get('Comparecimento', 0)), int(r.get('Total_Aptos', 0)),
            agora
        ))
    conn.commit()
    conn.close()

def registrar_ciclo_sqlite(escopo, urnas_pct, lula, flavio, total, cidades_qtd):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dif = lula - flavio
    lider = "Lula" if lula > flavio else ("Flávio Bolsonaro" if flavio > lula else "Empate")
    cur.execute("""
        INSERT INTO historico_ciclos (
            timestamp, escopo, urnas_apuradas_pct, votos_lula, votos_flavio,
            lider, diferenca, total_validos, cidades_processadas
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (agora, escopo, urnas_pct, lula, flavio, lider, dif, total, cidades_qtd))
    conn.commit()
    conn.close()

inicializar_banco()

# ==========================================
# ESTADO GLOBAL DA APLICAÇÃO
# ==========================================
class AppState:
    status = "IDLE"  # IDLE, AGENDADO, RODANDO, PAUSADO, CONCLUIDO_100
    modo = "exterior"  # 'exterior', 'brasil', 'completo'
    intervalo_segundos = 60
    
    agendamento_alvo = None  # datetime alvo ou None
    agendamento_restante = 0  # segundos restantes
    
    auto_stop_100 = True     # Para automaticamente ao atingir 100,00% das urnas
    auto_stop_hora = None    # "17:00" ou None
    
    ciclo_atual = 0
    ultimo_ciclo_hora = "--"
    duracao_ultimo_ciclo = 0.0
    
    urnas_pct = "0,00%"
    votos_lula = 0
    votos_flavio = 0
    pct_lula = "0,00%"
    pct_flavio = "0,00%"
    diferenca = 0
    lider = "Aguardando"
    total_validos = 0
    comparecimento = 0
    abstencao = 0
    
    sheets_status = "Aguardando primeiro envio"
    sheets_ultima_atualizacao = "--"
    
    logs = []  # [{ "hora": "...", "msg": "...", "tipo": "info"|"sucesso"|"aviso"|"erro" }]

def adicionar_log(msg, tipo="info"):
    hora = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora}] [{tipo.upper()}] {msg}")
    AppState.logs.insert(0, {
        "hora": hora,
        "msg": msg,
        "tipo": tipo
    })
    if len(AppState.logs) > 60:
        AppState.logs.pop()

adicionar_log("Servidor de Apuração Inicializado. Pronto para iniciar ou agendar.", "info")

# ==========================================
# MOTORES DE COLETA DO TSE
# ==========================================
def carregar_dicionario_exterior():
    if os.path.exists(DIC_EXTERIOR_PATH):
        return pd.read_csv(DIC_EXTERIOR_PATH, encoding="utf-8-sig")
    return pd.DataFrame()

def carregar_dicionario_municipios():
    if os.path.exists(DIC_MUNICIPIOS_PATH):
        return pd.read_csv(DIC_MUNICIPIOS_PATH, encoding="utf-8-sig")
    return pd.DataFrame()

def coletar_exterior(max_workers=20):
    df_dic = carregar_dicionario_exterior()
    if df_dic.empty:
        adicionar_log("Dicionário exterior não encontrado!", "erro")
        return None

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers, max_retries=2)
    session.mount("https://", adapter)
    session.headers.update(HEADERS_TSE)

    # 1. Macro arquivo ZZ
    url_macro = f"https://resultados.tse.jus.br/oficial/ele2026/{ELEICAO_ID}/dados/zz/zz-{CARGO_ID}-e00{ELEICAO_ID}-u.json"
    urnas_macro_pct = "0,00%"
    try:
        r_m = session.get(url_macro, verify=False, timeout=6)
        if r_m.status_code == 200:
            d_m = r_m.json()
            pst = d_m.get('s', {}).get('pst', '0,00')
            urnas_macro_pct = f"{pst}%" if not str(pst).endswith('%') else pst
    except Exception:
        pass

    resultados = []
    def fetch_cid(row):
        cod_tse = str(row['cod_tse']).zfill(5)
        url = f"https://resultados.tse.jus.br/oficial/ele2026/{ELEICAO_ID}/dados/zz/zz{cod_tse}-{CARGO_ID}-e00{ELEICAO_ID}-u.json"
        try:
            r = session.get(url, verify=False, timeout=6)
            if r.status_code == 200:
                d = r.json()
                lula = 0
                flavio = 0
                total_val = 0
                for c in d.get('carg', []):
                    for agr in c.get('agr', []):
                        for par in agr.get('par', []):
                            for cand in par.get('cand', []):
                                n = cand.get('nmu') or cand.get('nm') or ''
                                v = int(cand.get('vap', 0))
                                total_val += v
                                if 'LULA' in n.upper():
                                    lula += v
                                elif 'FLAVIO' in n.upper() or 'FLÁVIO' in n.upper():
                                    flavio += v
                e_info = d.get('e', {})
                s_info = d.get('s', {})
                v_info = d.get('v', {})
                return {
                    'cod_tse': cod_tse,
                    'Cidade': row['Cidade'],
                    'Pais': row['Pais'],
                    'UF': 'ZZ',
                    'Lula': lula,
                    'Flávio Bolsonaro': flavio,
                    'Total_Validos': total_val,
                    'Eleitores_Aptos': int(e_info.get('te', 0) or 0),
                    'Comparecimento': int(e_info.get('c', 0) or 0),
                    'Abstencao': int(e_info.get('a', 0) or 0),
                    'Brancos': int(v_info.get('vb', 0) or 0),
                    'Nulos': int(v_info.get('vn', 0) or 0),
                    'Urnas_Total': int(s_info.get('ts', 0) or 0),
                    'Urnas_Apuradas': s_info.get('pst', '0,00%')
                }
        except Exception:
            pass
        return {
            'cod_tse': cod_tse,
            'Cidade': row['Cidade'],
            'Pais': row['Pais'],
            'UF': 'ZZ',
            'Lula': 0,
            'Flávio Bolsonaro': 0,
            'Total_Validos': 0,
            'Eleitores_Aptos': 0,
            'Comparecimento': 0,
            'Abstencao': 0,
            'Brancos': 0,
            'Nulos': 0,
            'Urnas_Total': 0,
            'Urnas_Apuradas': '0,00%'
        }

    linhas = [r for _, r in df_dic.iterrows()]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for res in executor.map(fetch_cid, linhas):
            resultados.append(res)

    df = pd.DataFrame(resultados)
    mask = df['Total_Validos'] > 0
    df['Lula_percentual'] = "0,00%"
    df['Bolsonaro_percentual'] = "0,00%"
    df.loc[mask, 'Lula_percentual'] = (df['Lula'] / df['Total_Validos'] * 100).round(2).apply(lambda v: f"{v:.2f}%".replace(".", ","))
    df.loc[mask, 'Bolsonaro_percentual'] = (df['Flávio Bolsonaro'] / df['Total_Validos'] * 100).round(2).apply(lambda v: f"{v:.2f}%".replace(".", ","))
    df['Diferença'] = df['Lula'] - df['Flávio Bolsonaro']
    df['Vencedor'] = df.apply(lambda row: 'Lula' if row['Lula'] > row['Flávio Bolsonaro'] else ('Flávio Bolsonaro' if row['Flávio Bolsonaro'] > row['Lula'] else 'Empate'), axis=1)
    df.sort_values(by='Eleitores_Aptos', ascending=False, inplace=True)

    colunas = [
        'cod_tse', 'Cidade', 'Pais', 'UF', 'Lula', 'Flávio Bolsonaro', 'Total_Validos',
        'Lula_percentual', 'Bolsonaro_percentual', 'Diferença', 'Vencedor',
        'Eleitores_Aptos', 'Urnas_Total', 'Urnas_Apuradas', 'Comparecimento', 'Abstencao', 'Brancos', 'Nulos'
    ]
    df = df[colunas]
    df.to_csv(CSV_EXTERIOR_PATH, index=False, sep=";", encoding="utf-8-sig")
    
    return df, urnas_macro_pct

def coletar_brasil(max_workers=35):
    try:
        from coletar_presidente_municipios_2turno import coletar_municipios_brasil
        df = coletar_municipios_brasil(max_workers=max_workers)
        
        # Macro arquivo BR para urnas apuradas oficial total
        url_macro = f"https://resultados.tse.jus.br/oficial/ele2026/{ELEICAO_ID}/dados/br/br-{CARGO_ID}-e00{ELEICAO_ID}-u.json"
        urnas_br_pct = "0,00%"
        try:
            r_m = requests.get(url_macro, headers=HEADERS_TSE, verify=False, timeout=6)
            if r_m.status_code == 200:
                pst = r_m.json().get('s', {}).get('pst', '0,00')
                urnas_br_pct = f"{pst}%" if not str(pst).endswith('%') else pst
        except Exception:
            if df is not None and not df.empty and 'Urnas_Pct' in df.columns:
                urnas_br_pct = df['Urnas_Pct'].iloc[0]
                
        return df, urnas_br_pct
    except Exception as e:
        adicionar_log(f"Erro em coletar_brasil: {e}", "erro")
        return None, "0,00%"

# ==========================================
# AGREGADOR DE PAÍSES & GEOMETRIAS (FLOURISH)
# ==========================================
GEO_LOCAL_PATH = os.path.join(BASE_DIR, "geometrias_mundo.csv")
CSV_PAISES_EXTERIOR_PATH = os.path.join(PASTA_RECORTES, "mapa_flourish_paises_exterior.csv")

def gerar_dados_flourish_exterior(df_ext, sh=None):
    """
    Agrega as 186 cidades consulares por País (Name).
    Se houver a aba 'Geometrias_Base' no Google Sheets ou o arquivo 'geometrias_mundo.csv' local,
    insere a coluna 'geometry' antes de 'Name' exatamente como o Flourish requer.
    """
    df_dic = carregar_dicionario_exterior()
    df_dic['cod_tse'] = df_dic['cod_tse'].astype(str).str.zfill(5)
    df_ext_copy = df_ext.copy()
    df_ext_copy['cod_tse'] = df_ext_copy['cod_tse'].astype(str).str.zfill(5)
    map_pais = df_dic.set_index('cod_tse')['Pais'].to_dict()
    df_ext_copy['Pais'] = df_ext_copy['cod_tse'].map(map_pais).fillna(df_ext_copy.get('Pais', 'Exterior'))

    df_paises = df_ext_copy.groupby('Pais').agg({
        'Lula': 'sum',
        'Flávio Bolsonaro': 'sum',
        'Total_Validos': 'sum',
        'Eleitores_Aptos': 'sum',
        'Urnas_Total': 'sum',
        'Comparecimento': 'sum',
        'Abstencao': 'sum',
        'Brancos': 'sum',
        'Nulos': 'sum'
    }).reset_index().rename(columns={'Pais': 'Name'})

    mask = df_paises['Total_Validos'] > 0
    df_paises['Lula_percentual'] = "0,00%"
    df_paises['Bolsonaro_percentual'] = "0,00%"
    df_paises.loc[mask, 'Lula_percentual'] = (df_paises['Lula'] / df_paises['Total_Validos'] * 100).round(2).apply(lambda v: f"{v:.2f}%".replace(".", ","))
    df_paises.loc[mask, 'Bolsonaro_percentual'] = (df_paises['Flávio Bolsonaro'] / df_paises['Total_Validos'] * 100).round(2).apply(lambda v: f"{v:.2f}%".replace(".", ","))
    df_paises['Diferença'] = df_paises['Lula'] - df_paises['Flávio Bolsonaro']

    def calc_vencedor(row):
        if row['Total_Validos'] == 0:
            return 'Aguardando'
        if row['Lula'] > row['Flávio Bolsonaro']:
            return 'Lula'
        elif row['Flávio Bolsonaro'] > row['Lula']:
            return 'Flávio Bolsonaro'
        return 'Empate'

    df_paises['Vencedor'] = df_paises.apply(calc_vencedor, axis=1)

    # 1. Tenta carregar geometrias locais
    df_geo = None
    if os.path.exists(GEO_LOCAL_PATH):
        try:
            df_geo = pd.read_csv(GEO_LOCAL_PATH, sep=None, engine='python', encoding='utf-8-sig')
        except Exception:
            pass

    # 2. Tenta carregar geometrias da aba 'Geometrias_Base' no Google Sheets
    if df_geo is None and sh is not None:
        try:
            ws_geo = sh.worksheet("Geometrias_Base")
            valores = ws_geo.get_all_values()
            if len(valores) > 1:
                df_geo = pd.DataFrame(valores[1:], columns=valores[0])
        except Exception:
            pass

    # Se as geometrias foram encontradas, faz o merge mantendo a ordem geometry, Name, ...
    if df_geo is not None and 'geometry' in df_geo.columns and 'Name' in df_geo.columns:
        df_final = pd.merge(df_geo[['geometry', 'Name']], df_paises, on='Name', how='left')
        df_final['Lula'] = df_final['Lula'].fillna(0).astype(int)
        df_final['Flávio Bolsonaro'] = df_final['Flávio Bolsonaro'].fillna(0).astype(int)
        df_final['Total_Validos'] = df_final['Total_Validos'].fillna(0).astype(int)
        df_final['Lula_percentual'] = df_final['Lula_percentual'].fillna("0,00%")
        df_final['Bolsonaro_percentual'] = df_final['Bolsonaro_percentual'].fillna("0,00%")
        df_final['Diferença'] = df_final['Diferença'].fillna(0).astype(int)
        df_final['Vencedor'] = df_final['Vencedor'].fillna("Sem votação")
        df_final['Eleitores_Aptos'] = df_final['Eleitores_Aptos'].fillna(0).astype(int)
        df_final['Urnas_Total'] = df_final['Urnas_Total'].fillna(0).astype(int)
        df_final['Comparecimento'] = df_final['Comparecimento'].fillna(0).astype(int)
        df_final['Abstencao'] = df_final['Abstencao'].fillna(0).astype(int)
        df_final['Brancos'] = df_final['Brancos'].fillna(0).astype(int)
        df_final['Nulos'] = df_final['Nulos'].fillna(0).astype(int)
        df_final.to_csv(CSV_PAISES_EXTERIOR_PATH, index=False, sep=";", encoding="utf-8-sig")
        return df_final

    df_paises.sort_values(by='Eleitores_Aptos', ascending=False, inplace=True)
    df_paises.to_csv(CSV_PAISES_EXTERIOR_PATH, index=False, sep=";", encoding="utf-8-sig")
    return df_paises

# ==========================================
# SINCRONIZAÇÃO COM GOOGLE SHEETS
# ==========================================
def sincronizar_google_sheets(df_dados=None, df_brasil=None, df_exterior=None):
    try:
        import gspread
        gc = gspread.service_account(filename=CREDENCIAIS_PATH)
        sh = gc.open_by_key('1uUmAveUktR3qyU62dmpyuf2wEaRgKIJMFzYOZYuXsho')

        # Se df_dados foi passado como único parâmetro, identifica o tipo
        if df_brasil is None and df_dados is not None:
            if 'cod_ibge7' in df_dados.columns or 'UF_sigla' in df_dados.columns:
                df_brasil = df_dados
            elif 'Cidade' in df_dados.columns or 'Pais' in df_dados.columns:
                df_exterior = df_dados

        total_linhas_atualizadas = 0

        # -------------------------------------------------------------
        # 1. SINCRONIZAÇÃO DAS 5 ABAS DO BRASIL
        # -------------------------------------------------------------
        if df_brasil is not None and not df_brasil.empty:
            df_br = df_brasil.copy()
            # Normalizacao de colunas caso venham do SQLite em minusculo
            for col_orig, col_dest in [
                ('uf_sigla', 'UF_sigla'),
                ('estado', 'Estado'),
                ('municipio', 'Município'),
                ('lula', 'Lula'),
                ('flavio_bolsonaro', 'Flávio Bolsonaro'),
                ('total', 'Total'),
                ('total_validos', 'Total_Validos')
            ]:
                if col_orig in df_br.columns and col_dest not in df_br.columns:
                    df_br[col_dest] = df_br[col_orig]
            df_br['ibge_str'] = df_br['cod_ibge7'].astype(str).str.strip()
            dic_dados = df_br.set_index('ibge_str').to_dict(orient='index')

            # A. Mapa município -> Intervalo M2:S5572 (7 colunas)
            try:
                ws_mun = sh.worksheet('Mapa município')
                mun_ibges = ws_mun.col_values(1)[1:]
                payload_mun = []
                for ibge in mun_ibges:
                    d = dic_dados.get(str(ibge).strip(), {})
                    l2 = d.get('Lula', 0)
                    b2 = d.get('Flávio Bolsonaro', 0)
                    t2 = d.get('Total_Validos', d.get('Total', l2 + b2))
                    l_pct = (l2 / t2 * 100) if t2 > 0 else 0.0
                    b_pct = (b2 / t2 * 100) if t2 > 0 else 0.0
                    diff_pct = (l_pct - b_pct) if t2 > 0 else 0.0
                    urnas = d.get('Urnas_Pct', d.get('urnas_apuradas', '0,00'))
                    urnas_str = f"{urnas}%" if not str(urnas).endswith('%') else str(urnas)
                    payload_mun.append([
                        str(l2), str(b2), str(t2),
                        f"{l_pct:.2f}%".replace('.', ','),
                        f"{b_pct:.2f}%".replace('.', ','),
                        f"{diff_pct:.2f}".replace('.', ','),
                        urnas_str
                    ])
                if payload_mun:
                    ws_mun.update(range_name=f'M2:S{len(payload_mun)+1}', values=payload_mun, value_input_option='USER_ENTERED')
                    total_linhas_atualizadas += len(payload_mun)
            except Exception as e_mun:
                adicionar_log(f"Aviso sync Mapa município: {e_mun}", "aviso")

            # B. Mapa por região -> Intervalo K2:Q6 (7 colunas)
            try:
                ws_reg = sh.worksheet('Mapa por região')
                reg_rows = ws_reg.get_all_values()[1:]
                df_br['CD_REGIAO'] = df_br['UF_sigla'].map(lambda uf: UF_TO_REGION.get(uf, ('', ''))[0])
                
                tot_col = 'Total_Validos' if 'Total_Validos' in df_br.columns else 'Total'
                agg_dict = {
                    'Lula': 'sum',
                    'Flávio Bolsonaro': 'sum',
                    tot_col: 'sum'
                }
                if 'Seções_Totalizadas' in df_br.columns:
                    agg_dict['Seções_Totalizadas'] = 'sum'
                if 'Seções_Total' in df_br.columns:
                    agg_dict['Seções_Total'] = 'sum'
                    
                reg_agg = df_br.groupby('CD_REGIAO').agg(agg_dict).to_dict(orient='index')
                payload_reg = []
                for r in reg_rows:
                    cd = str(r[0]).strip()
                    d_reg = reg_agg.get(cd, {})
                    l2 = d_reg.get('Lula', 0)
                    b2 = d_reg.get('Flávio Bolsonaro', 0)
                    t2 = d_reg.get(tot_col, l2 + b2)
                    l_pct = (l2 / t2 * 100) if t2 > 0 else 0.0
                    b_pct = (b2 / t2 * 100) if t2 > 0 else 0.0
                    diff_pct = (l_pct - b_pct) if t2 > 0 else 0.0
                    sec_tot = d_reg.get('Seções_Total', 0)
                    sec_ap = d_reg.get('Seções_Totalizadas', 0)
                    urnas_reg = (sec_ap / sec_tot * 100) if sec_tot > 0 else 0.0
                    payload_reg.append([
                        str(l2), str(b2), str(t2),
                        f"{l_pct:.2f}%".replace('.', ','),
                        f"{b_pct:.2f}%".replace('.', ','),
                        f"{diff_pct:.2f}".replace('.', ','),
                        f"{urnas_reg:.2f}%".replace('.', ',')
                    ])
                if payload_reg:
                    ws_reg.update(range_name=f'K2:Q{len(payload_reg)+1}', values=payload_reg, value_input_option='USER_ENTERED')
                    total_linhas_atualizadas += len(payload_reg)
            except Exception as e_reg:
                adicionar_log(f"Aviso sync Mapa por região: {e_reg}", "aviso")

            # C. Mapa por estado -> Intervalo F2:I28 (4 colunas)
            try:
                ws_est = sh.worksheet('Mapa por estado')
                est_rows = ws_est.get_all_values()[1:]
                tot_col = 'Total_Validos' if 'Total_Validos' in df_br.columns else 'Total'
                agg_dict_est = {
                    'Lula': 'sum',
                    'Flávio Bolsonaro': 'sum',
                    tot_col: 'sum'
                }
                if 'Seções_Totalizadas' in df_br.columns:
                    agg_dict_est['Seções_Totalizadas'] = 'sum'
                if 'Seções_Total' in df_br.columns:
                    agg_dict_est['Seções_Total'] = 'sum'
                    
                est_agg = df_br.groupby('Estado').agg(agg_dict_est).to_dict(orient='index')
                payload_est = []
                for r in est_rows:
                    est_nome = str(r[0]).strip()
                    d_est = est_agg.get(est_nome, {})
                    l2 = d_est.get('Lula', 0)
                    b2 = d_est.get('Flávio Bolsonaro', 0)
                    t2 = d_est.get(tot_col, l2 + b2)
                    l_pct = (l2 / t2 * 100) if t2 > 0 else 0.0
                    b_pct = (b2 / t2 * 100) if t2 > 0 else 0.0
                    diff_pct = (l_pct - b_pct) if t2 > 0 else 0.0
                    sec_tot = d_est.get('Seções_Total', 0)
                    sec_ap = d_est.get('Seções_Totalizadas', 0)
                    urnas_est = (sec_ap / sec_tot * 100) if sec_tot > 0 else 0.0
                    payload_est.append([
                        f"{l_pct:.2f}".replace('.', ','),
                        f"{b_pct:.2f}".replace('.', ','),
                        f"{diff_pct:.2f}".replace('.', ','),
                        f"{urnas_est:.2f}%".replace('.', ',')
                    ])
                if payload_est:
                    ws_est.update(range_name=f'F2:I{len(payload_est)+1}', values=payload_est, value_input_option='USER_ENTERED')
                    total_linhas_atualizadas += len(payload_est)
            except Exception as e_est:
                adicionar_log(f"Aviso sync Mapa por estado: {e_est}", "aviso")

            # D. Município abstenção -> Intervalo M2:U5572 (9 colunas)
            try:
                ws_abst = sh.worksheet('Município abstenção')
                abst_ibges = ws_abst.col_values(1)[1:]
                payload_abst = []
                for ibge in abst_ibges:
                    d = dic_dados.get(str(ibge).strip(), {})
                    brancos = d.get('Brancos', 0)
                    nulos = d.get('Nulos', 0)
                    abst = d.get('Abstencoes', d.get('Abstencao', 0))
                    comp = d.get('Comparecimento', 0)
                    aptos = d.get('Total_Aptos', d.get('Eleitores_Aptos', comp + abst))
                    br_pct = (brancos / comp * 100) if comp > 0 else 0.0
                    nu_pct = (nulos / comp * 100) if comp > 0 else 0.0
                    ab_pct = (abst / aptos * 100) if aptos > 0 else 0.0
                    co_pct = (comp / aptos * 100) if aptos > 0 else 0.0
                    urnas = d.get('Urnas_Pct', d.get('urnas_apuradas', '0,00'))
                    urnas_str = f"{urnas}%" if not str(urnas).endswith('%') else str(urnas)
                    payload_abst.append([
                        str(brancos), str(nulos), str(abst), str(comp),
                        f"{br_pct:.2f}%".replace('.', ','),
                        f"{nu_pct:.2f}%".replace('.', ','),
                        f"{ab_pct:.2f}%".replace('.', ','),
                        f"{co_pct:.2f}%".replace('.', ','),
                        urnas_str
                    ])
                if payload_abst:
                    ws_abst.update(range_name=f'M2:U{len(payload_abst)+1}', values=payload_abst, value_input_option='USER_ENTERED')
                    total_linhas_atualizadas += len(payload_abst)
            except Exception as e_abst:
                adicionar_log(f"Aviso sync Município abstenção: {e_abst}", "aviso")

            # F. Voto nas capitais (1 e 2 turno) -> Intervalo F83:G136 (apenas 2º turno, não mexe no 1º turno)
            try:
                ws_cap = sh.worksheet('Voto nas capitais (1 e 2 turno)')
                cap_rows = ws_cap.get_all_values()

                # Localiza com segurança as linhas de 2º turno (preserva 100% as linhas do 1º turno)
                t2_indices = [idx for idx, r in enumerate(cap_rows) if len(r) > 2 and '2' in str(r[2]).lower() and 'turno' in str(r[2]).lower()]

                if t2_indices:
                    start_row = t2_indices[0] + 1  # 1-indexed (linha 83)
                    end_row = t2_indices[-1] + 1    # 1-indexed (linha 136)

                    payload_cap = []
                    for idx in t2_indices:
                        r = cap_rows[idx]
                        ibge = str(r[0]).strip()
                        cand = str(r[4]).strip().lower()

                        d = dic_dados.get(ibge, {})
                        
                        # Extração resiliente de votos Lula
                        l2 = 0
                        for k in ['Lula', 'lula', 'Lula (PT)', 'LULA']:
                            if k in d and d[k] is not None and str(d[k]).strip() != '':
                                try:
                                    l2 = int(float(str(d[k]).replace('.', '').replace(',', '.')))
                                    break
                                except Exception:
                                    pass

                        # Extração resiliente de votos Flávio Bolsonaro
                        b2 = 0
                        for k in ['Flávio Bolsonaro', 'Fl\xe1vio Bolsonaro', 'Flavio Bolsonaro', 'flavio_bolsonaro', 'Flavio_Bolsonaro', 'bolsonaro', 'Bolsonaro']:
                            if k in d and d[k] is not None and str(d[k]).strip() != '':
                                try:
                                    b2 = int(float(str(d[k]).replace('.', '').replace(',', '.')))
                                    break
                                except Exception:
                                    pass

                        t2 = l2 + b2
                        if t2 == 0:
                            for k in ['Total_Validos', 'total_validos', 'Total', 'total']:
                                if k in d and d[k] is not None and str(d[k]).strip() != '':
                                    try:
                                        t2 = int(float(str(d[k]).replace('.', '').replace(',', '.')))
                                        break
                                    except Exception:
                                        pass

                        l_pct = (l2 / t2 * 100) if t2 > 0 else 0.0
                        b_pct = (b2 / t2 * 100) if t2 > 0 else 0.0

                        if 'lula' in cand:
                            votos = l2
                            pct_str = f"{l_pct:.2f}%".replace('.', ',')
                        elif 'bolsonaro' in cand or 'fl' in cand:
                            votos = b2
                            pct_str = f"{b_pct:.2f}%".replace('.', ',')
                        else:
                            votos = 0
                            pct_str = "0,00%"

                        payload_cap.append([str(votos), pct_str])

                    if payload_cap:
                        ws_cap.update(range_name=f'F{start_row}:G{end_row}', values=payload_cap, value_input_option='USER_ENTERED')
                        total_linhas_atualizadas += len(payload_cap)
            except Exception as e_cap:
                adicionar_log(f"Aviso sync Voto nas capitais (1 e 2 turno): {e_cap}", "aviso")

            # E. Município alfabetização -> Intervalo J2:O5572 (6 colunas)
            try:
                ws_alfab = sh.worksheet('Município alfabetização')
                alfab_ibges = ws_alfab.col_values(1)[1:]
                payload_alfab = []
                for ibge in alfab_ibges:
                    d = dic_dados.get(str(ibge).strip(), {})
                    l2 = d.get('Lula', 0)
                    b2 = d.get('Flávio Bolsonaro', 0)
                    t2 = d.get('Total_Validos', d.get('Total', l2 + b2))
                    l_pct = (l2 / t2 * 100) if t2 > 0 else 0.0
                    b_pct = (b2 / t2 * 100) if t2 > 0 else 0.0
                    if t2 == 0:
                        vencedor = 'Aguardando'
                    elif l2 > b2:
                        vencedor = 'Lula'
                    elif b2 > l2:
                        vencedor = 'Flávio Bolsonaro'
                    else:
                        vencedor = 'Empate'
                    payload_alfab.append([
                        str(l2), str(b2), str(t2),
                        f"{l_pct:.2f}%".replace('.', ','),
                        f"{b_pct:.2f}%".replace('.', ','),
                        vencedor
                    ])
                if payload_alfab:
                    ws_alfab.update(range_name=f'J2:O{len(payload_alfab)+1}', values=payload_alfab, value_input_option='USER_ENTERED')
                    total_linhas_atualizadas += len(payload_alfab)
            except Exception as e_alfab:
                adicionar_log(f"Aviso sync Município alfabetização: {e_alfab}", "aviso")

        # -------------------------------------------------------------
        # 2. SINCRONIZAÇÃO DO EXTERIOR (MAPA MUNDI)
        # -------------------------------------------------------------
        if df_exterior is not None and not df_exterior.empty:
            try:
                ws_mundi = sh.worksheet('Mapa mundi')
                mundi_paises = ws_mundi.col_values(2)[1:]
                df_ext_copy = df_exterior.copy()
                df_dic_ext = carregar_dicionario_exterior()
                df_dic_ext['cod_tse'] = df_dic_ext['cod_tse'].astype(str).str.zfill(5)
                df_ext_copy['cod_tse'] = df_ext_copy['cod_tse'].astype(str).str.zfill(5)
                map_pais = df_dic_ext.set_index('cod_tse')['Pais'].to_dict()
                df_ext_copy['Pais'] = df_ext_copy['cod_tse'].map(map_pais).fillna(df_ext_copy.get('Pais', 'Exterior'))

                tot_ext_col = 'Total_Validos' if 'Total_Validos' in df_ext_copy.columns else 'Total'
                agg_ext = {
                    'Lula': 'sum',
                    'Flávio Bolsonaro': 'sum',
                    tot_ext_col: 'sum'
                }
                if 'Urnas_Total' in df_ext_copy.columns:
                    agg_ext['Urnas_Total'] = 'sum'
                if 'Urnas_Apuradas' in df_ext_copy.columns:
                    agg_ext['Urnas_Apuradas'] = 'sum'

                paises_agg = df_ext_copy.groupby('Pais').agg(agg_ext).to_dict(orient='index')
                paises_votantes = set(df_dic_ext['Pais'].dropna().str.strip())
                payload_mundi = []
                for p_nome in mundi_paises:
                    p_clean = str(p_nome).strip()
                    if p_clean not in paises_votantes:
                        payload_mundi.append(['', '', '', '', '', '', ''])
                    else:
                        d_p = paises_agg.get(p_clean, {})
                        l2 = d_p.get('Lula', 0)
                        b2 = d_p.get('Flávio Bolsonaro', 0)
                        t2 = d_p.get(tot_ext_col, l2 + b2)
                        l_pct = (l2 / t2 * 100) if t2 > 0 else 0.0
                        b_pct = (b2 / t2 * 100) if t2 > 0 else 0.0
                        diff_pct = (l_pct - b_pct) if t2 > 0 else 0.0
                        u_tot = d_p.get('Urnas_Total', 0)
                        u_ap = d_p.get('Urnas_Apuradas', 0)
                        u_pct = (u_ap / u_tot * 100) if u_tot > 0 else 0.0
                        payload_mundi.append([
                            str(l2), str(b2), str(t2),
                            f"{l_pct:.2f}%".replace('.', ','),
                            f"{b_pct:.2f}%".replace('.', ','),
                            f"{diff_pct:.2f}".replace('.', ','),
                            f"{u_pct:.2f}%".replace('.', ',')
                        ])
                if payload_mundi:
                    ws_mundi.update(range_name=f'K2:Q{len(payload_mundi)+1}', values=payload_mundi, value_input_option='USER_ENTERED')
                    total_linhas_atualizadas += len(payload_mundi)
            except Exception as e_mundi:
                adicionar_log(f"Aviso sync Mapa mundi: {e_mundi}", "aviso")

        agora = datetime.now().strftime("%H:%M:%S")
        AppState.sheets_status = f"Sincronizado com sucesso ({total_linhas_atualizadas} registros)"
        AppState.sheets_ultima_atualizacao = agora
        adicionar_log(f"Google Sheets atualizado com sucesso ({total_linhas_atualizadas} registros no 2º Turno)!", "sucesso")
        return True
    except Exception as e:
        AppState.sheets_status = f"Erro ao sincronizar: {str(e)[:40]}"
        adicionar_log(f"Falha ao sincronizar Google Sheets: {e}", "aviso")
        return False

# ==========================================
# WORKER BACKGROUND: LOOP DE APURAÇÃO
# ==========================================
worker_thread = None
worker_executando = False

def ciclo_execucao():
    t0 = time.time()
    AppState.ciclo_atual += 1
    adicionar_log(f"Iniciando Ciclo #{AppState.ciclo_atual} (Modo: {AppState.modo.upper()})...", "info")

    df_para_sheets = None
    df_br = None
    df_ext = None
    urnas_detectadas = "0,00%"

    if AppState.modo in ["exterior", "completo"]:
        df_ext, urnas_ext = coletar_exterior(max_workers=20)
        if df_ext is not None:
            salvar_exterior_sqlite(df_ext)
            df_para_sheets = df_ext
            urnas_detectadas = urnas_ext
            
            # Totais
            lula = int(df_ext['Lula'].sum())
            flavio = int(df_ext['Flávio Bolsonaro'].sum())
            tot = int(df_ext['Total_Validos'].sum())
            aptos = int(df_ext['Eleitores_Aptos'].sum())
            comp = int(df_ext['Comparecimento'].sum())
            abst = int(df_ext['Abstencao'].sum())

            AppState.votos_lula = lula
            AppState.votos_flavio = flavio
            AppState.total_validos = tot
            AppState.comparecimento = comp
            AppState.abstencao = abst
            AppState.urnas_pct = urnas_detectadas

            if tot > 0:
                AppState.pct_lula = f"{(lula / tot * 100):.2f}%".replace(".", ",")
                AppState.pct_flavio = f"{(flavio / tot * 100):.2f}%".replace(".", ",")
            AppState.diferenca = lula - flavio
            AppState.lider = "Lula" if lula > flavio else ("Flávio Bolsonaro" if flavio > lula else "Empate")

            registrar_ciclo_sqlite("exterior", urnas_detectadas, lula, flavio, tot, len(df_ext))

    if AppState.modo in ["brasil", "completo"]:
        df_br, urnas_br = coletar_brasil(max_workers=35)
        if df_br is not None:
            salvar_brasil_sqlite(df_br)
            if AppState.modo == "brasil":
                df_para_sheets = df_br
                urnas_detectadas = urnas_br
                
                lula = int(df_br['Lula'].sum())
                flavio = int(df_br['Flávio Bolsonaro'].sum())
                tot = int(df_br['Total'].sum())

                AppState.votos_lula = lula
                AppState.votos_flavio = flavio
                AppState.total_validos = tot
                AppState.urnas_pct = urnas_detectadas
                if tot > 0:
                    AppState.pct_lula = f"{(lula / tot * 100):.2f}%".replace(".", ",")
                    AppState.pct_flavio = f"{(flavio / tot * 100):.2f}%".replace(".", ",")
                AppState.diferenca = lula - flavio
                AppState.lider = "Lula" if lula > flavio else ("Flávio Bolsonaro" if flavio > lula else "Empate")

                registrar_ciclo_sqlite("brasil", urnas_detectadas, lula, flavio, tot, len(df_br))

    # Atualiza Google Sheets
    if AppState.modo == "completo" and (df_br is not None or df_ext is not None):
        sincronizar_google_sheets(df_brasil=df_br, df_exterior=df_ext)
    elif df_para_sheets is not None:
        sincronizar_google_sheets(df_para_sheets)

    tempo_ciclo = time.time() - t0
    AppState.duracao_ultimo_ciclo = round(tempo_ciclo, 2)
    AppState.ultimo_ciclo_hora = datetime.now().strftime("%H:%M:%S")

    adicionar_log(f"Ciclo #{AppState.ciclo_atual} concluído em {tempo_ciclo:.1f}s | Urnas: {AppState.urnas_pct} | Lula: {AppState.pct_lula} x Flávio: {AppState.pct_flavio}", "sucesso")

    # Verifica se 100% das urnas foram apuradas (Auto-Desativação Inteligente)
    limpo_pct = AppState.urnas_pct.replace("%", "").replace(",", ".").strip()
    try:
        val_pct = float(limpo_pct)
        if AppState.auto_stop_100 and val_pct >= 100.0:
            adicionar_log("🎉 100% das urnas apuradas! Auto-desativação ativada para proteger o computador.", "sucesso")
            AppState.status = "CONCLUIDO_100"
            return False
    except Exception:
        pass

    # Verifica auto-stop por horário (ex: 17:00 no domingo para exterior)
    if AppState.auto_stop_hora:
        agora_hhmm = datetime.now().strftime("%H:%M")
        if agora_hhmm >= AppState.auto_stop_hora:
            adicionar_log(f"Horário limite atingido ({AppState.auto_stop_hora}). Desativando apuração automática.", "aviso")
            AppState.status = "PAUSADO"
            return False

    return True

def background_worker_loop():
    global worker_executando
    worker_executando = True

    while worker_executando:
        # Estado: AGENDADO
        if AppState.status == "AGENDADO":
            if AppState.agendamento_alvo:
                agora = datetime.now()
                delta = (AppState.agendamento_alvo - agora).total_seconds()
                AppState.agendamento_restante = max(0, int(delta))

                if delta <= 0:
                    adicionar_log("⏰ Horário agendado atingido! Ativando apuração automática...", "sucesso")
                    AppState.status = "RODANDO"
                    AppState.agendamento_alvo = None
                    AppState.agendamento_restante = 0
            time.sleep(1)
            continue

        # Estado: RODANDO
        if AppState.status == "RODANDO":
            try:
                continua = ciclo_execucao()
                if not continua:
                    break
            except Exception as e:
                adicionar_log(f"Erro inesperado no ciclo: {e}", "erro")

            # Descanso entre ciclos para proteger contra taxa de requisição
            descanso = AppState.intervalo_segundos
            adicionar_log(f"Aguardando {descanso}s até a próxima rodada de varredura...", "info")
            for _ in range(descanso):
                if AppState.status != "RODANDO" or not worker_executando:
                    break
                time.sleep(1)
            continue

        # Estado: IDLE, PAUSADO, CONCLUIDO_100
        time.sleep(1)

    worker_executando = False

def iniciar_worker_se_necessario():
    global worker_thread, worker_executando
    if worker_thread is None or not worker_thread.is_alive():
        worker_thread = threading.Thread(target=background_worker_loop, daemon=True)
        worker_thread.start()

# ==========================================
# FASTAPI APP & ROTAS
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    iniciar_worker_se_necessario()
    yield

app = FastAPI(title="Apurador Remoto 2º Turno", version="2.0", lifespan=lifespan)

# API Endpoints
@app.get("/api/status")
def get_status():
    return {
        "status": AppState.status,
        "modo": AppState.modo,
        "ciclo_atual": AppState.ciclo_atual,
        "ultimo_ciclo_hora": AppState.ultimo_ciclo_hora,
        "duracao_ultimo_ciclo": AppState.duracao_ultimo_ciclo,
        "intervalo_segundos": AppState.intervalo_segundos,
        "agendamento_restante": AppState.agendamento_restante,
        "agendamento_alvo": AppState.agendamento_alvo.strftime("%d/%m/%Y %H:%M:%S") if AppState.agendamento_alvo else None,
        "auto_stop_100": AppState.auto_stop_100,
        "auto_stop_hora": AppState.auto_stop_hora,
        "urnas_pct": AppState.urnas_pct,
        "votos_lula": AppState.votos_lula,
        "votos_flavio": AppState.votos_flavio,
        "pct_lula": AppState.pct_lula,
        "pct_flavio": AppState.pct_flavio,
        "diferenca": AppState.diferenca,
        "lider": AppState.lider,
        "total_validos": AppState.total_validos,
        "comparecimento": AppState.comparecimento,
        "abstencao": AppState.abstencao,
        "sheets_status": AppState.sheets_status,
        "sheets_ultima_atualizacao": AppState.sheets_ultima_atualizacao,
        "logs": AppState.logs[:25]
    }

@app.post("/api/iniciar")
def api_iniciar():
    iniciar_worker_se_necessario()
    AppState.status = "RODANDO"
    adicionar_log("Comando recebido: Iniciar apuração imediatamente.", "info")
    return {"ok": True, "status": AppState.status}

@app.post("/api/parar")
def api_parar():
    AppState.status = "PAUSADO"
    adicionar_log("Comando recebido: Apuração pausada pelo usuário.", "aviso")
    return {"ok": True, "status": AppState.status}

@app.post("/api/agendar")
def api_agendar(data: dict):
    # Pode receber minutos (countdown) ou datahora ISO
    iniciar_worker_se_necessario()
    minutos = data.get("minutos")
    datahora = data.get("datahora")

    if minutos:
        alvo = datetime.now() + timedelta(minutes=int(minutos))
    elif datahora:
        # Formato esperado: YYYY-MM-DDTHH:MM ou YYYY-MM-DD HH:MM
        datahora = datahora.replace("T", " ")
        if len(datahora) == 16:
            datahora += ":00"
        alvo = datetime.strptime(datahora, "%Y-%m-%d %H:%M:%S")
    else:
        # Padrão: Próximo Domingo às 00:00:00
        hoje = datetime.now()
        dias_ate_domingo = (6 - hoje.weekday()) % 7
        if dias_ate_domingo == 0 and hoje.hour >= 0:
            dias_ate_domingo = 7
        domingo = hoje + timedelta(days=dias_ate_domingo)
        alvo = datetime(domingo.year, domingo.month, domingo.day, 0, 0, 0)

    AppState.agendamento_alvo = alvo
    delta = (alvo - datetime.now()).total_seconds()
    AppState.agendamento_restante = max(0, int(delta))
    AppState.status = "AGENDADO"

    adicionar_log(f"⏰ Apuração agendada com sucesso para: {alvo.strftime('%d/%m/%Y às %H:%M:%S')}", "sucesso")
    return {"ok": True, "alvo": alvo.strftime("%d/%m/%Y %H:%M:%S"), "restante": AppState.agendamento_restante}

@app.post("/api/cancelar_agendamento")
def api_cancelar_agendamento():
    AppState.status = "IDLE"
    AppState.agendamento_alvo = None
    AppState.agendamento_restante = 0
    adicionar_log("Agendamento cancelado pelo usuário.", "info")
    return {"ok": True}

@app.post("/api/configurar_modo")
def api_configurar_modo(data: dict):
    novo_modo = data.get("modo", "exterior")
    if novo_modo in ["exterior", "brasil", "completo"]:
        AppState.modo = novo_modo
        adicionar_log(f"Modo de apuração alterado para: {novo_modo.upper()}", "info")
    intervalo = data.get("intervalo")
    if intervalo:
        AppState.intervalo_segundos = max(30, int(intervalo))
    auto_stop_100 = data.get("auto_stop_100")
    if auto_stop_100 is not None:
        AppState.auto_stop_100 = bool(auto_stop_100)
    auto_stop_hora = data.get("auto_stop_hora")
    AppState.auto_stop_hora = auto_stop_hora if auto_stop_hora else None

    return {"ok": True, "modo": AppState.modo, "intervalo": AppState.intervalo_segundos}

@app.post("/api/sincronizar_sheets_agora")
def api_sincronizar_sheets_agora():
    df_br = None
    df_ext = None
    if os.path.exists(CSV_BRASIL_PATH):
        try:
            df_br = pd.read_csv(CSV_BRASIL_PATH, sep=";", encoding="utf-8-sig")
        except Exception:
            pass
    if df_br is None and os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            df_br = pd.read_sql_query("SELECT * FROM votos_municipios", conn)
            conn.close()
        except Exception:
            pass

    if os.path.exists(CSV_EXTERIOR_PATH):
        try:
            df_ext = pd.read_csv(CSV_EXTERIOR_PATH, sep=";", encoding="utf-8-sig")
        except Exception:
            pass
    if df_ext is None and os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            df_ext = pd.read_sql_query("SELECT * FROM votos_exterior", conn)
            conn.close()
        except Exception:
            pass
            
    if df_br is None and df_ext is None:
        return {"ok": False, "msg": "Nenhum dado gerado ainda"}
        
    sucesso = sincronizar_google_sheets(df_brasil=df_br, df_exterior=df_ext)
    return {"ok": sucesso}

# Downloads remotos diretos
@app.get("/api/download/banco")
def download_banco():
    if os.path.exists(DB_PATH):
        return FileResponse(DB_PATH, media_type="application/octet-stream", filename="eleicoes_2turno.db")
    return JSONResponse(status_code=404, content={"erro": "Banco SQLite ainda não gerado"})

@app.get("/api/download/csv_exterior")
def download_csv_exterior():
    if os.path.exists(CSV_EXTERIOR_PATH):
        return FileResponse(CSV_EXTERIOR_PATH, media_type="text/csv", filename="mapa_exterior_presidentes_2turno.csv")
    return JSONResponse(status_code=404, content={"erro": "CSV Exterior ainda não gerado"})

@app.get("/api/download/csv_brasil")
def download_csv_brasil():
    if os.path.exists(CSV_BRASIL_PATH):
        return FileResponse(CSV_BRASIL_PATH, media_type="text/csv", filename="mapa_brasil_presidentes_2turno.csv")
    return JSONResponse(status_code=404, content={"erro": "CSV Brasil ainda não gerado"})

# Interface HTML Principal
@app.get("/", response_class=HTMLResponse)
def index_page():
    return HTML_INTERFACE

# ==========================================
# INTERFACE WEB (MOBILE & DESKTOP - MODERNA)
# ==========================================
HTML_INTERFACE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Central de Dados O POVO+ | Apuração Exterior 2º Turno 2026</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=Roboto+Condensed:wght@400;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #080C14;
      --bg-card: rgba(15, 23, 42, 0.75);
      --bg-card-hover: rgba(30, 41, 59, 0.85);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-highlight: rgba(229, 9, 20, 0.35);
      --opovo-red: #E50914;
      --opovo-red-glow: rgba(229, 9, 20, 0.25);
      --text-main: #F8FAFC;
      --text-muted: #94A3B8;
      --text-dim: #64748B;
      --lula-color: #EF4444;
      --flavio-color: #3B82F6;
      --emerald: #10B981;
      --amber: #F59E0B;
      --font-display: 'Outfit', sans-serif;
      --font-condensed: 'Roboto Condensed', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--bg-base);
      background-image: 
        radial-gradient(circle at 15% 15%, rgba(229, 9, 20, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 85% 85%, rgba(59, 130, 246, 0.05) 0%, transparent 45%);
      color: var(--text-main);
      font-family: var(--font-display);
      min-height: 100vh;
      padding: 24px 16px 40px;
      line-height: 1.5;
    }

    .container {
      max-width: 1180px;
      margin: 0 auto;
    }

    /* HEADER EDITORIAL O POVO+ */
    header {
      background: linear-gradient(135deg, rgba(20, 27, 45, 0.9) 0%, rgba(15, 23, 42, 0.95) 100%);
      border: 1px solid var(--border-subtle);
      border-top: 3px solid var(--opovo-red);
      border-radius: 16px;
      padding: 24px 28px;
      margin-bottom: 24px;
      backdrop-filter: blur(16px);
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 20px;
    }

    .brand-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .brand-badge-bar {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .brand-logo-badge {
      background: var(--opovo-red);
      color: #FFFFFF;
      font-family: var(--font-condensed);
      font-weight: 800;
      font-size: 0.85rem;
      letter-spacing: 1px;
      text-transform: uppercase;
      padding: 4px 10px;
      border-radius: 6px;
      box-shadow: 0 0 14px var(--opovo-red-glow);
    }

    .brand-subtag {
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--text-muted);
      letter-spacing: 1.5px;
      text-transform: uppercase;
    }

    h1 {
      font-size: 1.75rem;
      font-weight: 800;
      letter-spacing: -0.5px;
      color: #FFFFFF;
      margin-top: 2px;
    }

    .header-desc {
      font-size: 0.92rem;
      color: var(--text-muted);
    }

    .live-status-pill {
      display: flex;
      align-items: center;
      gap: 10px;
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.3);
      padding: 8px 16px;
      border-radius: 30px;
    }

    .pulse-dot {
      width: 10px;
      height: 10px;
      background: var(--emerald);
      border-radius: 50%;
      box-shadow: 0 0 10px var(--emerald);
      animation: pulse 1.8s infinite;
    }

    @keyframes pulse {
      0% { transform: scale(0.95); opacity: 0.8; }
      50% { transform: scale(1.25); opacity: 1; filter: drop-shadow(0 0 6px var(--emerald)); }
      100% { transform: scale(0.95); opacity: 0.8; }
    }

    /* METRIC BANNER STATS */
    .metrics-strip {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }

    .metric-card {
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 16px 18px;
      backdrop-filter: blur(12px);
      transition: transform 0.2s, border-color 0.2s;
    }

    .metric-card:hover {
      transform: translateY(-2px);
      border-color: rgba(255, 255, 255, 0.16);
    }

    .metric-card .label {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: var(--text-dim);
      font-weight: 600;
    }

    .metric-card .value {
      font-size: 1.5rem;
      font-weight: 800;
      color: #FFFFFF;
      margin-top: 4px;
      font-family: var(--font-condensed);
    }

    .metric-card .sub {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 2px;
    }

    /* GRIDS */
    .main-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-bottom: 24px;
    }

    @media (max-width: 860px) {
      .main-grid {
        grid-template-columns: 1fr;
      }
    }

    .card {
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 22px 24px;
      backdrop-filter: blur(14px);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border-subtle);
      padding-bottom: 14px;
    }

    .card-title {
      font-size: 1.1rem;
      font-weight: 700;
      color: #FFFFFF;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* TIMER & STATUS CARD */
    .timer-hero {
      text-align: center;
      background: rgba(8, 12, 20, 0.6);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 20px 16px;
    }

    .timer-display {
      font-family: var(--font-mono);
      font-size: 2.5rem;
      font-weight: 700;
      color: #60A5FA;
      text-shadow: 0 0 20px rgba(96, 165, 250, 0.35);
      letter-spacing: 2px;
    }

    .timer-caption {
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-top: 6px;
    }

    .btn-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    .btn {
      flex: 1;
      min-width: 130px;
      padding: 11px 16px;
      border-radius: 8px;
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 0.88rem;
      cursor: pointer;
      border: 1px solid transparent;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: all 0.2s ease;
    }

    .btn-primary {
      background: var(--opovo-red);
      color: #FFFFFF;
      box-shadow: 0 4px 12px var(--opovo-red-glow);
    }
    .btn-primary:hover {
      background: #B91C1C;
      transform: translateY(-1px);
    }

    .btn-success {
      background: #059669;
      color: #FFFFFF;
      box-shadow: 0 4px 12px rgba(5, 150, 105, 0.3);
    }
    .btn-success:hover {
      background: #047857;
      transform: translateY(-1px);
    }

    .btn-danger {
      background: #DC2626;
      color: #FFFFFF;
      box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);
    }
    .btn-danger:hover {
      background: #B91C1C;
      transform: translateY(-1px);
    }

    .btn-outline {
      background: rgba(30, 41, 59, 0.6);
      border-color: rgba(255, 255, 255, 0.12);
      color: #E2E8F0;
    }
    .btn-outline:hover {
      background: rgba(51, 65, 85, 0.8);
      border-color: rgba(255, 255, 255, 0.25);
    }

    /* PLACAR ELEITORAL EXTERIOR */
    .scoreboard {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .cand-box {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(8, 12, 20, 0.5);
      border: 1px solid var(--border-subtle);
      border-radius: 10px;
      padding: 12px 16px;
    }

    .cand-meta {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .cand-avatar {
      width: 14px;
      height: 38px;
      border-radius: 4px;
    }

    .cand-name-title {
      font-weight: 700;
      font-size: 1.05rem;
    }

    .cand-votos-sub {
      font-size: 0.8rem;
      color: var(--text-muted);
      font-family: var(--font-condensed);
    }

    .cand-percent-display {
      font-size: 1.7rem;
      font-weight: 800;
      font-family: var(--font-condensed);
    }

    .bar-wrapper {
      width: 100%;
      height: 12px;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 6px;
      overflow: hidden;
      display: flex;
    }

    .bar-seg-lula {
      background: var(--lula-color);
      height: 100%;
      width: 50%;
      transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .bar-seg-flavio {
      background: var(--flavio-color);
      height: 100%;
      width: 50%;
      transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .metrics-pill-row {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 10px;
    }

    .pill-card {
      background: rgba(8, 12, 20, 0.6);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 10px 12px;
      text-align: center;
    }

    .pill-label {
      font-size: 0.72rem;
      text-transform: uppercase;
      color: var(--text-dim);
      font-weight: 600;
    }

    .pill-data {
      font-size: 1rem;
      font-weight: 700;
      color: #FFFFFF;
      margin-top: 2px;
    }

    /* GOOGLE SHEETS & DOWNLOADS */
    .sheets-box {
      background: rgba(8, 12, 20, 0.5);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .sheets-url-link {
      color: #60A5FA;
      text-decoration: none;
      word-break: break-all;
      font-size: 0.88rem;
      font-weight: 500;
    }
    .sheets-url-link:hover {
      text-decoration: underline;
    }

    .download-strip {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    .download-tile {
      display: flex;
      align-items: center;
      gap: 12px;
      background: rgba(8, 12, 20, 0.5);
      border: 1px solid var(--border-subtle);
      padding: 14px 16px;
      border-radius: 10px;
      text-decoration: none;
      color: inherit;
      transition: all 0.2s;
    }

    .download-tile:hover {
      background: rgba(30, 41, 59, 0.7);
      border-color: rgba(255, 255, 255, 0.2);
      transform: translateY(-2px);
    }

    .tile-icon {
      font-size: 1.6rem;
    }

    .tile-title {
      font-weight: 700;
      font-size: 0.9rem;
    }

    .tile-sub {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    /* TERMINAL LOG CONSOLE */
    .terminal-box {
      background: #05080E;
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      height: 220px;
      overflow-y: auto;
      padding: 14px;
      font-family: var(--font-mono);
      font-size: 0.8rem;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .log-row {
      display: flex;
      gap: 10px;
      line-height: 1.4;
    }

    .log-ts {
      color: var(--text-dim);
      white-space: nowrap;
    }

    .log-txt.sucesso { color: #34D399; }
    .log-txt.info { color: #94A3B8; }
    .log-txt.aviso { color: #FBBF24; }
    .log-txt.erro { color: #F87171; }

    /* Custom Scrollbar */
    .terminal-box::-webkit-scrollbar {
      width: 6px;
    }
    .terminal-box::-webkit-scrollbar-track {
      background: rgba(0, 0, 0, 0.2);
    }
    .terminal-box::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.15);
      border-radius: 3px;
    }

    footer {
      text-align: center;
      margin-top: 36px;
      font-size: 0.8rem;
      color: var(--text-dim);
    }
  </style>
</head>
<body>
  <div class="container">
    <!-- HEADER EDITORIAL O POVO+ -->
    <header>
      <div class="brand-group">
        <div class="brand-badge-bar">
          <span class="brand-logo-badge">O POVO+</span>
          <span class="brand-subtag">Central de Dados</span>
        </div>
        <h1>Apuração Presidencial 2º Turno 2026</h1>
        <p class="header-desc">Monitoramento em Tempo Real do Voto no Exterior (ZZ) & Integração com Flourish</p>
      </div>
      <div class="live-status-pill">
        <div class="pulse-dot"></div>
        <span style="font-weight: 700; font-size: 0.85rem; color: #34D399;" id="statusIndicator">LIVE NA NUVEM</span>
      </div>
    </header>

    <!-- METRICS STRIP: EXTERIOR -->
    <div class="metrics-strip">
      <div class="metric-card">
        <div class="label">Eleitorado no Exterior</div>
        <div class="value">916.683</div>
        <div class="sub">Total de eleitores aptos</div>
      </div>
      <div class="metric-card">
        <div class="label">Cidades Consulares</div>
        <div class="value">186</div>
        <div class="sub">Seções de votação pelo mundo</div>
      </div>
      <div class="metric-card">
        <div class="label">Países Votantes</div>
        <div class="value">132</div>
        <div class="sub">Alimentando a aba Mapa mundi</div>
      </div>
      <div class="metric-card">
        <div class="label">Urnas Totalizadas</div>
        <div class="value" id="urnasMetric" style="color: #34D399;">0,00%</div>
        <div class="sub">Progresso oficial do TSE</div>
      </div>
    </div>

    <!-- MAIN TWO COLUMN GRID -->
    <div class="main-grid">
      <!-- CARD 1: CONTROLE DO ROBÔ -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">⏱️ Controle & Cronômetro</div>
          <span style="font-size: 0.8rem; color: #60A5FA; font-weight: 600;" id="modoBadge">Modo: Exterior (ZZ)</span>
        </div>

        <div class="timer-hero">
          <div class="timer-display" id="timerDisplay">00:00:00</div>
          <div class="timer-caption" id="timerSubtitle">Aguardando início ou agendamento</div>
        </div>

        <div class="btn-row">
          <button class="btn btn-primary" onclick="agendarDomingo()">📅 Agendar Domingo 00h00</button>
          <button class="btn btn-outline" onclick="cancelarAgendamento()">❌ Cancelar Agendamento</button>
        </div>

        <div class="btn-row">
          <button class="btn btn-success" id="btnIniciar" onclick="iniciarAgora()">▶️ Iniciar Agora</button>
          <button class="btn btn-danger" id="btnParar" onclick="pararAgora()">⏸️ Pausar</button>
        </div>

        <div style="font-size: 0.8rem; color: var(--text-dim); text-align: center; margin-top: 4px;">
          Varredura configurada para <strong>60 segundos</strong> com parada inteligente aos 100%.
        </div>
      </div>

      <!-- CARD 2: PLACAR PRESIDENCIAL EXTERIOR -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">📊 Placar Presidencial no Exterior</div>
          <span style="font-size: 0.8rem; color: #A78BFA; font-weight: 700;" id="statCiclo">Ciclo #0</span>
        </div>

        <div class="scoreboard">
          <div class="cand-box">
            <div class="cand-meta">
              <div class="cand-avatar" style="background: var(--lula-color);"></div>
              <div>
                <div class="cand-name-title">Lula</div>
                <div class="cand-votos-sub" id="votosLulaAbs">0 votos apurados</div>
              </div>
            </div>
            <div class="cand-percent-display" style="color: var(--lula-color);" id="pctLula">0,00%</div>
          </div>

          <div class="cand-box">
            <div class="cand-meta">
              <div class="cand-avatar" style="background: var(--flavio-color);"></div>
              <div>
                <div class="cand-name-title">Flávio Bolsonaro</div>
                <div class="cand-votos-sub" id="votosFlavioAbs">0 votos apurados</div>
              </div>
            </div>
            <div class="cand-percent-display" style="color: var(--flavio-color);" id="pctFlavio">0,00%</div>
          </div>

          <div class="bar-wrapper">
            <div class="bar-seg-lula" id="barLula"></div>
            <div class="bar-seg-flavio" id="barFlavio"></div>
          </div>

          <div class="metrics-pill-row">
            <div class="pill-card">
              <div class="pill-label">Líder Exterior</div>
              <div class="pill-data" id="statLider" style="color: #60A5FA;">--</div>
            </div>
            <div class="pill-card">
              <div class="pill-label">Diferença de Votos</div>
              <div class="pill-data" id="statDif">0</div>
            </div>
            <div class="pill-card">
              <div class="pill-label">Total Válidos</div>
              <div class="pill-data" id="statValidos">0</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- GRID INFERIOR: PLANILHA & DOWNLOADS -->
    <div class="main-grid">
      <!-- CARD 3: FLOURISH & PLANILHA -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">📈 Sincronização Google Sheets (Flourish)</div>
          <button class="btn btn-outline" style="padding: 6px 12px; font-size: 0.78rem;" onclick="sincronizarSheets()">⚡ Forçar Sincronização</button>
        </div>

        <div class="sheets-box">
          <div style="font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase; font-weight: 700;">Status do Envio</div>
          <div id="sheetsStatus" style="font-size: 1rem; font-weight: 700; color: #34D399;">Aguardando primeiro ciclo</div>
          
          <div style="font-size: 0.82rem; color: var(--text-muted); margin-top: 6px;">
            Planilha Oficial:
            <div>
              <a href="https://docs.google.com/spreadsheets/d/1uUmAveUktR3qyU62dmpyuf2wEaRgKIJMFzYOZYuXsho" target="_blank" class="sheets-url-link">
                Central das eleições - segundo turno (Aba: Mapa mundi) ↗
              </a>
            </div>
          </div>

          <div style="font-size: 0.78rem; color: var(--text-dim); margin-top: 2px;">
            Intervalo Alvo: <strong>K2:Q244</strong> (Lula2, Bolsonaro2, Total2, Percentuais, 2º turno, Urnas)
          </div>
        </div>
      </div>

      <!-- CARD 4: EXPORTAÇÃO DE DADOS -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">💾 Exportação & Backups do Exterior</div>
        </div>

        <div class="download-strip">
          <a href="/api/download/csv_exterior" class="download-tile">
            <span class="tile-icon">🌍</span>
            <div>
              <div class="tile-title">CSV Exterior</div>
              <div class="tile-sub">186 cidades consulares</div>
            </div>
          </a>

          <a href="/api/download/banco" class="download-tile">
            <span class="tile-icon">🗄️</span>
            <div>
              <div class="tile-title">Banco SQLite</div>
              <div class="tile-sub">eleicoes_2turno.db</div>
            </div>
          </a>
        </div>

        <div style="font-size: 0.8rem; color: var(--text-dim); line-height: 1.4; margin-top: 4px;">
          Os arquivos são gerados e persistidos a cada ciclo de apuração para conferência jornalística e arquivamento histórico.
        </div>
      </div>
    </div>

    <!-- CARD 5: TERMINAL DE LOGS -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">📜 Console de Logs em Tempo Real</div>
        <span style="font-size: 0.75rem; color: var(--text-dim); font-family: var(--font-mono);">Polling: 2s</span>
      </div>
      <div class="terminal-box" id="logConsole">
        <div class="log-row">
          <span class="log-ts">--:--:--</span>
          <span class="log-txt info">Inicializando console da Central de Dados O POVO+...</span>
        </div>
      </div>
    </div>

    <footer>
      Central de Dados & Redação O POVO+ &bull; Eleições 2026 &bull; Servidor em Nuvem Render
    </footer>
  </div>

  <script>
    function formatarSegundos(segundos) {
      if (segundos <= 0) return "00:00:00";
      const h = Math.floor(segundos / 3600).toString().padStart(2, '0');
      const m = Math.floor((segundos % 3600) / 60).toString().padStart(2, '0');
      const s = (segundos % 60).toString().padStart(2, '0');
      return `${h}:${m}:${s}`;
    }

    function formatarNumero(num) {
      return (num || 0).toLocaleString('pt-BR');
    }

    async function atualizarStatus() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        // 1. Status Indicator & Timer
        const stInd = document.getElementById('statusIndicator');
        const timerDisp = document.getElementById('timerDisplay');
        const timerSub = document.getElementById('timerSubtitle');
        
        if (data.status === 'RUNNING') {
          stInd.innerText = 'EM EXECUÇÃO';
          stInd.style.color = '#34D399';
          timerDisp.innerText = 'EM LOOP';
          timerDisp.style.color = '#34D399';
          timerSub.innerText = `Varrendo o TSE a cada ${data.intervalo_segundos}s`;
        } else if (data.status === 'AGENDADO') {
          stInd.innerText = 'AGENDADO';
          stInd.style.color = '#FBBF24';
          timerDisp.innerText = formatarSegundos(data.agendamento_restante);
          timerDisp.style.color = '#FBBF24';
          timerSub.innerText = `Início automático em: ${data.agendamento_alvo || 'Domingo 00h'}`;
        } else {
          stInd.innerText = 'STANDBY / PAUSADO';
          stInd.style.color = '#94A3B8';
          timerDisp.innerText = '00:00:00';
          timerDisp.style.color = '#60A5FA';
          timerSub.innerText = 'Pronto para iniciar ou agendar';
        }

        // 2. Metrics & Placar
        document.getElementById('urnasMetric').innerText = data.urnas_pct || '0,00%';
        document.getElementById('statCiclo').innerText = `Ciclo #${data.ciclo_atual || 0}`;
        document.getElementById('pctLula').innerText = data.pct_lula || '0,00%';
        document.getElementById('pctFlavio').innerText = data.pct_flavio || '0,00%';
        document.getElementById('votosLulaAbs').innerText = `${formatarNumero(data.votos_lula)} votos apurados`;
        document.getElementById('votosFlavioAbs').innerText = `${formatarNumero(data.votos_flavio)} votos apurados`;
        document.getElementById('statLider').innerText = data.lider || '--';
        document.getElementById('statDif').innerText = formatarNumero(data.diferenca);
        document.getElementById('statValidos').innerText = formatarNumero(data.total_validos);

        // Barra de progresso
        const tot = (data.votos_lula || 0) + (data.votos_flavio || 0);
        if (tot > 0) {
          const pL = (data.votos_lula / tot) * 100;
          const pF = (data.votos_flavio / tot) * 100;
          document.getElementById('barLula').style.width = pL + '%';
          document.getElementById('barFlavio').style.width = pF + '%';
        } else {
          document.getElementById('barLula').style.width = '50%';
          document.getElementById('barFlavio').style.width = '50%';
        }

        // 3. Google Sheets Status
        const shSt = document.getElementById('sheetsStatus');
        shSt.innerText = data.sheets_status || 'Aguardando';
        if (data.sheets_ultima_atualizacao && data.sheets_ultima_atualizacao !== '--') {
          shSt.innerText += ` (${data.sheets_ultima_atualizacao})`;
        }

        // 4. Logs Console
        const logBox = document.getElementById('logConsole');
        if (data.logs && data.logs.length > 0) {
          logBox.innerHTML = '';
          data.logs.forEach(l => {
            const row = document.createElement('div');
            row.className = 'log-row';
            row.innerHTML = `<span class="log-ts">${l.hora}</span><span class="log-txt ${l.tipo}">${l.msg}</span>`;
            logBox.appendChild(row);
          });
        }
      } catch (e) {
        console.error('Erro polling status:', e);
      }
    }

    async function iniciarAgora() {
      await fetch('/api/iniciar', { method: 'POST' });
      atualizarStatus();
    }

    async function pararAgora() {
      await fetch('/api/parar', { method: 'POST' });
      atualizarStatus();
    }

    async function agendarDomingo() {
      await fetch('/api/agendar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tipo: 'domingo_00' })
      });
      atualizarStatus();
    }

    async function cancelarAgendamento() {
      await fetch('/api/cancelar_agendamento', { method: 'POST' });
      atualizarStatus();
    }

    async function sincronizarSheets() {
      await fetch('/api/sincronizar_sheets_agora', { method: 'POST' });
      atualizarStatus();
    }

    setInterval(atualizarStatus, 2000);
    atualizarStatus();
  </script>
</body>
</html>
"""

# ==========================================
# EXECUÇÃO DO SERVIDOR
# ==========================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Servidor de Apuração 2º Turno TSE")
    parser.add_argument("--host", default="0.0.0.0", help="Host IP")
    parser.add_argument("--port", type=int, default=8080, help="Porta de escuta")
    args = parser.parse_args()

    print("=" * 70)
    print("🚀 INICIANDO SERVIDOR LOCAL DE APURAÇÃO 2º TURNO (TSE 2026)")
    print(f"📡 Acesso Local (PC):          http://localhost:{args.port}")
    print(f"📱 Acesso Remoto (Wi-Fi/Rede): http://192.168.6.116:{args.port}")
    print(f"🗄️ Banco SQLite:              {DB_PATH}")
    print(f"📊 Google Sheets:             {LINK_GOOGLE_SHEETS}")
    print("=" * 70)

    porta = int(os.environ.get("PORT", args.port))
    uvicorn.run(app, host=args.host, port=porta, log_level="warning")
