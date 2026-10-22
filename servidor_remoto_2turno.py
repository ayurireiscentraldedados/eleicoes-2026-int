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
    if df_para_sheets is not None:
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
    if os.path.exists(CSV_EXTERIOR_PATH):
        try:
            df_ext = pd.read_csv(CSV_EXTERIOR_PATH, sep=";", encoding="utf-8-sig")
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
HTML_INTERFACE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Apurador 2º Turno 2026 | Controle Remoto</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #090D16;
      --card-bg: rgba(22, 30, 49, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --text-main: #F1F5F9;
      --text-muted: #94A3B8;
      --primary: #6366F1;
      --primary-hover: #4F46E5;
      --lula-color: #EF4444;
      --flavio-color: #3B82F6;
      --success: #10B981;
      --warning: #F59E0B;
      --danger: #EF4444;
      --glow-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    }
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
    }
    body {
      background-color: var(--bg-dark);
      background-image: radial-gradient(circle at 15% 15%, rgba(99, 102, 241, 0.15) 0%, transparent 40%),
                        radial-gradient(circle at 85% 85%, rgba(16, 185, 129, 0.1) 0%, transparent 40%);
      color: var(--text-main);
      font-family: 'Outfit', sans-serif;
      min-height: 100vh;
      padding: 16px;
      display: flex;
      flex-direction: column;
      align-items: center;
    }
    .container {
      width: 100%;
      max-width: 900px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    /* Header */
    header {
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 18px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: var(--glow-shadow);
    }
    .header-title h1 {
      font-size: 1.35rem;
      font-weight: 800;
      letter-spacing: -0.5px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .header-title p {
      font-size: 0.85rem;
      color: var(--text-muted);
      margin-top: 2px;
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      background: rgba(148, 163, 184, 0.15);
      border: 1px solid rgba(148, 163, 184, 0.3);
    }
    .badge-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #94A3B8;
    }
    .status-badge.rodando {
      background: rgba(16, 185, 129, 0.2);
      border-color: rgba(16, 185, 129, 0.5);
      color: #34D399;
    }
    .status-badge.rodando .badge-dot {
      background: #34D399;
      box-shadow: 0 0 12px #34D399;
      animation: pulse 1.5s infinite;
    }
    .status-badge.agendado {
      background: rgba(245, 158, 11, 0.2);
      border-color: rgba(245, 158, 11, 0.5);
      color: #FBBF24;
    }
    .status-badge.agendado .badge-dot {
      background: #FBBF24;
    }
    .status-badge.pausado {
      background: rgba(239, 68, 68, 0.2);
      border-color: rgba(239, 68, 68, 0.5);
      color: #F87171;
    }
    @keyframes pulse {
      0% { opacity: 0.4; transform: scale(0.9); }
      50% { opacity: 1; transform: scale(1.2); }
      100% { opacity: 0.4; transform: scale(0.9); }
    }
    /* Cards Layout */
    .grid-2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    @media (max-width: 720px) {
      .grid-2 {
        grid-template-columns: 1fr;
      }
    }
    .card {
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 20px;
      box-shadow: var(--glow-shadow);
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .card-header h2 {
      font-size: 1.05rem;
      font-weight: 700;
      color: var(--text-main);
    }
    /* Timer Display */
    .timer-box {
      background: rgba(0, 0, 0, 0.35);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 16px;
      padding: 16px;
      text-align: center;
    }
    .timer-digits {
      font-family: 'JetBrains Mono', monospace;
      font-size: 2.3rem;
      font-weight: 800;
      letter-spacing: 2px;
      color: #FBBF24;
    }
    .timer-subtitle {
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 4px;
    }
    /* Candidate Scoreboard */
    .score-container {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .candidate-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 14px;
      background: rgba(0, 0, 0, 0.3);
      border-radius: 12px;
    }
    .cand-info {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .cand-badge {
      width: 14px;
      height: 14px;
      border-radius: 4px;
    }
    .cand-name {
      font-size: 0.95rem;
      font-weight: 700;
    }
    .cand-votes {
      text-align: right;
    }
    .cand-pct {
      font-size: 1.15rem;
      font-weight: 800;
      font-family: 'JetBrains Mono', monospace;
    }
    .cand-abs {
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    /* Comparison Bar */
    .progress-bar-bg {
      height: 14px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      overflow: hidden;
      display: flex;
    }
    .bar-lula {
      background: var(--lula-color);
      width: 50%;
      transition: width 0.6s ease;
    }
    .bar-flavio {
      background: var(--flavio-color);
      width: 50%;
      transition: width 0.6s ease;
    }
    /* Stat Pills */
    .stats-row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }
    .stat-pill {
      background: rgba(0, 0, 0, 0.3);
      border-radius: 12px;
      padding: 10px;
      text-align: center;
    }
    .stat-label {
      font-size: 0.72rem;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 600;
    }
    .stat-val {
      font-size: 1.05rem;
      font-weight: 800;
      margin-top: 2px;
      font-family: 'JetBrains Mono', monospace;
    }
    /* Buttons */
    .btn {
      padding: 12px 18px;
      border-radius: 12px;
      font-family: 'Outfit', sans-serif;
      font-size: 0.92rem;
      font-weight: 700;
      cursor: pointer;
      border: none;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: all 0.2s ease;
    }
    .btn:active {
      transform: scale(0.97);
    }
    .btn-primary {
      background: var(--primary);
      color: white;
    }
    .btn-success {
      background: var(--success);
      color: white;
    }
    .btn-danger {
      background: var(--danger);
      color: white;
    }
    .btn-secondary {
      background: rgba(255, 255, 255, 0.1);
      color: var(--text-main);
      border: 1px solid var(--card-border);
    }
    .btn-secondary:hover {
      background: rgba(255, 255, 255, 0.15);
    }
    .btn-group {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    /* Form controls */
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .form-label {
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
    }
    .form-input, .form-select {
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 10px 14px;
      border-radius: 10px;
      font-family: inherit;
      font-size: 0.9rem;
      outline: none;
    }
    .form-input:focus, .form-select:focus {
      border-color: var(--primary);
    }
    /* Logs Console */
    .log-console {
      background: #05070D;
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 14px;
      padding: 12px;
      height: 180px;
      overflow-y: auto;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.78rem;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .log-item {
      display: flex;
      gap: 8px;
      line-height: 1.4;
    }
    .log-time {
      color: #64748B;
      flex-shrink: 0;
    }
    .log-msg.info { color: #94A3B8; }
    .log-msg.sucesso { color: #34D399; font-weight: 600; }
    .log-msg.aviso { color: #FBBF24; }
    .log-msg.erro { color: #F87171; font-weight: 600; }
    /* Network Access Card */
    .ip-box {
      background: rgba(99, 102, 241, 0.1);
      border: 1px dashed rgba(99, 102, 241, 0.4);
      border-radius: 12px;
      padding: 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.88rem;
    }
    .ip-text {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 700;
      color: #818CF8;
    }
    /* Downloads */
    .download-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }
    @media (max-width: 600px) {
      .download-grid {
        grid-template-columns: 1fr;
      }
    }
    .download-link {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 12px;
      text-decoration: none;
      color: var(--text-main);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      text-align: center;
      font-size: 0.82rem;
      transition: background 0.2s;
    }
    .download-link:hover {
      background: rgba(255, 255, 255, 0.1);
    }
    .download-icon {
      font-size: 1.3rem;
    }
  </style>
</head>
<body>
  <div class="container">
    <!-- Top Header -->
    <header>
      <div class="header-title">
        <h1>🗳️ Apurador 2º Turno 2026</h1>
        <p>Servidor Local de Alta Performance & Controle Remoto</p>
      </div>
      <div id="statusBadge" class="status-badge">
        <span class="badge-dot"></span>
        <span id="statusText">IDLE</span>
      </div>
    </header>

    <!-- Mobile Remote Access Link -->
    <div class="ip-box">
      <div>
        <span>📱 Acesso pelo Celular (mesmo Wi-Fi):</span>
        <span class="ip-text" id="localIp">http://192.168.6.116:8080</span>
      </div>
      <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 0.78rem;" onclick="copiarLink()">Copiar</button>
    </div>

    <!-- Main Grid: Timer & Telemetry -->
    <div class="grid-2">
      <!-- Card 1: Cronômetro & Agendamento -->
      <div class="card">
        <div class="card-header">
          <h2>⏱️ Agendamento & Cronômetro</h2>
          <span style="font-size: 0.8rem; color: var(--text-muted);" id="agendamentoLabel">Inativo</span>
        </div>
        <div class="timer-box">
          <div class="timer-digits" id="timerDisplay">00:00:00</div>
          <div class="timer-subtitle" id="timerSubtitle">Aguardando definição ou início manual</div>
        </div>
        <div class="btn-group">
          <button class="btn btn-secondary" onclick="agendarDomingo()">📅 Domingo 00h00</button>
          <button class="btn btn-secondary" onclick="agendarMinutos(30)">⏳ Em 30 min</button>
        </div>
        <div class="btn-group">
          <button class="btn btn-success" id="btnIniciar" onclick="iniciarAgora()">▶️ Iniciar Agora</button>
          <button class="btn btn-danger" id="btnParar" onclick="pararAgora()">⏸️ Pausar</button>
        </div>
      </div>

      <!-- Card 2: Placar em Tempo Real -->
      <div class="card">
        <div class="card-header">
          <h2>📊 Totalização Presidencial</h2>
          <span style="font-size: 0.8rem; color: #10B981; font-weight: 700;" id="urnasPct">Urnas: 0,00%</span>
        </div>
        <div class="score-container">
          <div class="candidate-row">
            <div class="cand-info">
              <div class="cand-badge" style="background: var(--lula-color);"></div>
              <div>
                <div class="cand-name">Lula</div>
                <div class="cand-abs" id="votosLulaAbs">0 votos</div>
              </div>
            </div>
            <div class="cand-pct" style="color: var(--lula-color);" id="pctLula">0,00%</div>
          </div>
          <div class="candidate-row">
            <div class="cand-info">
              <div class="cand-badge" style="background: var(--flavio-color);"></div>
              <div>
                <div class="cand-name">Flávio Bolsonaro</div>
                <div class="cand-abs" id="votosFlavioAbs">0 votos</div>
              </div>
            </div>
            <div class="cand-pct" style="color: var(--flavio-color);" id="pctFlavio">0,00%</div>
          </div>
          <div class="progress-bar-bg">
            <div class="bar-lula" id="barLula"></div>
            <div class="bar-flavio" id="barFlavio"></div>
          </div>
        </div>
        <div class="stats-row">
          <div class="stat-pill">
            <div class="stat-label">Líder</div>
            <div class="stat-val" id="statLider">--</div>
          </div>
          <div class="stat-pill">
            <div class="stat-label">Diferença</div>
            <div class="stat-val" id="statDif">0</div>
          </div>
          <div class="stat-pill">
            <div class="stat-label">Ciclo</div>
            <div class="stat-val" id="statCiclo">#0</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Mode Configuration & Google Sheets -->
    <div class="grid-2">
      <!-- Configurações Rápidas -->
      <div class="card">
        <div class="card-header">
          <h2>⚙️ Modo & Auto-Desativação</h2>
        </div>
        <div class="form-group">
          <label class="form-label">Escopo da Apuração</label>
          <select id="selectModo" class="form-select" onchange="salvarConfig()">
            <option value="exterior">Exterior (186 cidades consulares - ZZ)</option>
            <option value="brasil">Brasil (5.571 municípios nacionais)</option>
            <option value="completo">Completo (Brasil + Exterior)</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Intervalo de Varredura (Descanso entre ciclos)</label>
          <select id="selectIntervalo" class="form-select" onchange="salvarConfig()">
            <option value="45">45 segundos (Rápido)</option>
            <option value="60" selected>60 segundos (Recomendado TSE)</option>
            <option value="120">120 segundos (Conservador)</option>
          </select>
        </div>
        <div style="display: flex; gap: 8px; align-items: center; font-size: 0.85rem; color: #10B981; margin-top: 4px;">
          <span>✔ Auto-Desativação Inteligente em 100% ativa (protege o PC)</span>
        </div>
      </div>

      <!-- Google Sheets Flourish Sync -->
      <div class="card">
        <div class="card-header">
          <h2>📈 Google Sheets (Flourish)</h2>
          <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 0.78rem;" onclick="sincronizarSheets()">Forçar Envio</button>
        </div>
        <div class="stat-pill" style="text-align: left; padding: 12px;">
          <div class="stat-label">Status da Planilha</div>
          <div class="stat-val" id="sheetsStatus" style="font-size: 0.95rem; margin-top: 4px; color: #34D399;">Conectado</div>
        </div>
        <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.4;">
          Planilha Vinculada: <a href="https://docs.google.com/spreadsheets/d/1uUmAveUktR3qyU62dmpyuf2wEaRgKIJMFzYOZYuXsho" target="_blank" style="color: #818CF8; word-break: break-all;">Central das eleições - segundo turno (Aba: Mapa mundi)</a>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-muted);">
          Última sincronização: <span id="sheetsHora">--</span>
        </div>
      </div>
    </div>

    <!-- Downloads Remotos -->
    <div class="card">
      <div class="card-header">
        <h2>💾 Downloads Remotos para Celular / PC</h2>
      </div>
      <div class="download-grid">
        <a href="/api/download/banco" class="download-link">
          <span class="download-icon">🗄️</span>
          <strong>Banco SQLite (.db)</strong>
          <span>eleicoes_2turno.db</span>
        </a>
        <a href="/api/download/csv_exterior" class="download-link">
          <span class="download-icon">🌍</span>
          <strong>CSV Exterior (186 cid)</strong>
          <span>mapa_exterior_presidentes</span>
        </a>
        <a href="/api/download/csv_brasil" class="download-link">
          <span class="download-icon">🇧🇷</span>
          <strong>CSV Brasil (5.571 mun)</strong>
          <span>mapa_brasil_presidentes</span>
        </a>
      </div>
    </div>

    <!-- Live Terminal Logs Console -->
    <div class="card">
      <div class="card-header">
        <h2>📜 Logs de Execução em Tempo Real</h2>
      </div>
      <div class="log-console" id="logConsole">
        <div class="log-item"><span class="log-time">--:--:--</span><span class="log-msg info">Aguardando primeiros registros...</span></div>
      </div>
    </div>
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
        const data = await res.json();

        // 1. Badge de Status
        const badge = document.getElementById('statusBadge');
        const text = document.getElementById('statusText');
        badge.className = 'status-badge ' + data.status.toLowerCase();
        text.innerText = data.status;

        // 2. Timer
        const timerDisp = document.getElementById('timerDisplay');
        const timerSub = document.getElementById('timerSubtitle');
        const agendamentoLabel = document.getElementById('agendamentoLabel');

        if (data.status === 'AGENDADO') {
          timerDisp.innerText = formatarSegundos(data.agendamento_restante);
          timerSub.innerText = `Ativação automática em: ${data.agendamento_alvo || ''}`;
          agendamentoLabel.innerText = "Agendado";
          agendamentoLabel.style.color = "#FBBF24";
        } else if (data.status === 'RODANDO') {
          timerDisp.innerText = "EM MARCHA";
          timerSub.innerText = `Ciclo ativo a cada ${data.intervalo_segundos}s | Duração: ${data.duracao_ultimo_ciclo}s`;
          agendamentoLabel.innerText = "Em Apuração";
          agendamentoLabel.style.color = "#34D399";
        } else if (data.status === 'CONCLUIDO_100') {
          timerDisp.innerText = "100,00%";
          timerSub.innerText = "Apuração finalizada com sucesso! PC em repouso.";
          agendamentoLabel.innerText = "Concluído";
          agendamentoLabel.style.color = "#34D399";
        } else {
          timerDisp.innerText = "00:00:00";
          timerSub.innerText = "Apuração parada. Clique em 'Iniciar' ou agende.";
          agendamentoLabel.innerText = "Parado";
          agendamentoLabel.style.color = "#94A3B8";
        }

        // 3. Placar e Telemetria
        document.getElementById('urnasPct').innerText = `Urnas: ${data.urnas_pct}`;
        document.getElementById('pctLula').innerText = data.pct_lula;
        document.getElementById('pctFlavio').innerText = data.pct_flavio;
        document.getElementById('votosLulaAbs').innerText = `${formatarNumero(data.votos_lula)} votos`;
        document.getElementById('votosFlavioAbs').innerText = `${formatarNumero(data.votos_flavio)} votos`;

        document.getElementById('statLider').innerText = data.lider;
        document.getElementById('statDif').innerText = formatarNumero(data.diferenca);
        document.getElementById('statCiclo').innerText = `#${data.ciclo_atual}`;

        // Barra percentual
        const pLula = parseFloat((data.pct_lula || "0").replace(",", ".")) || 50;
        const pFlavio = parseFloat((data.pct_flavio || "0").replace(",", ".")) || 50;
        const totalP = pLula + pFlavio || 100;
        document.getElementById('barLula').style.width = `${(pLula / totalP) * 100}%`;
        document.getElementById('barFlavio').style.width = `${(pFlavio / totalP) * 100}%`;

        // 4. Google Sheets
        document.getElementById('sheetsStatus').innerText = data.sheets_status;
        document.getElementById('sheetsHora').innerText = data.sheets_ultima_atualizacao;

        // 5. Logs Console
        const logBox = document.getElementById('logConsole');
        logBox.innerHTML = '';
        (data.logs || []).forEach(l => {
          const item = document.createElement('div');
          item.className = 'log-item';
          item.innerHTML = `<span class="log-time">${l.hora}</span><span class="log-msg ${l.tipo}">${l.msg}</span>`;
          logBox.appendChild(item);
        });

      } catch (e) {
        console.error("Erro ao atualizar status:", e);
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
        body: JSON.stringify({})
      });
      atualizarStatus();
    }

    async function agendarMinutos(m) {
      await fetch('/api/agendar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ minutos: m })
      });
      atualizarStatus();
    }

    async function salvarConfig() {
      const modo = document.getElementById('selectModo').value;
      const intervalo = document.getElementById('selectIntervalo').value;
      await fetch('/api/configurar_modo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modo, intervalo })
      });
      atualizarStatus();
    }

    async function sincronizarSheets() {
      await fetch('/api/sincronizar_sheets_agora', { method: 'POST' });
      atualizarStatus();
    }

    function copiarLink() {
      const url = document.getElementById('localIp').innerText;
      navigator.clipboard.writeText(url).then(() => {
        alert("Link copiado! Abra no navegador do seu smartphone conectado ao mesmo Wi-Fi.");
      });
    }

    // Polling a cada 2 segundos
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
