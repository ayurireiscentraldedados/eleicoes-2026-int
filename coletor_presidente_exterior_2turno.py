import os
import sys
import time
import json
import urllib3
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Garante suporte a UTF-8 no terminal Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

"""
COLETOR & APURADOR DE DADOS PRESIDENCIAIS NO EXTERIOR (ZZ) - 2º TURNO (2026)
----------------------------------------------------------------------------
Monitora todos os 186 postos consulares / cidades no exterior diretamente do CDN do TSE:
- Eleição Federal 2º Turno: 6258
- Cargo: Presidente (c0001)
- Unidade Federativa: ZZ (Exterior)
- Gera tabela consolidada com votos de Lula x Flávio Bolsonaro, eleitores e comparecimento
"""

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = r"c:\Users\RED.AyuriReis\Downloads\Apurador_real" if os.path.exists(r"c:\Users\RED.AyuriReis\Downloads\Apurador_real") else SCRIPT_DIR

DICIONARIO_PATH = os.path.join(BASE_DIR, "dicionario_cidades_exterior.csv")
PASTA_RECORTES = os.path.join(BASE_DIR, "recortes_gerados_2turno")
os.makedirs(PASTA_RECORTES, exist_ok=True)

ELEICAO_ID = "6258"  # 2º Turno Oficial TSE
CARGO_ID = "c0001"   # Presidente

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

def carregar_dicionario_exterior():
    """Carrega o dicionário das 186 cidades consulares no exterior."""
    if os.path.exists(DICIONARIO_PATH):
        return pd.read_csv(DICIONARIO_PATH, encoding="utf-8-sig")
    
    print("[Aviso] Dicionário de cidades do exterior não encontrado localmente. Baixando do TSE...")
    url_mun = f"https://resultados.tse.jus.br/oficial/ele2026/{ELEICAO_ID}/config/mun-e00{ELEICAO_ID}-cm.json"
    r = requests.get(url_mun, headers=HEADERS, verify=False, timeout=15)
    data = r.json()
    
    cidades = []
    for u in data.get('abr', []):
        if u.get('cd', '').lower() == 'zz':
            for m in u.get('mu', []):
                cidades.append({
                    'cod_tse': str(m.get('cd')).zfill(5),
                    'Cidade': m.get('nm', '').title(),
                    'Pais': 'Exterior',
                    'UF': 'ZZ'
                })
    df = pd.DataFrame(cidades)
    df.to_csv(DICIONARIO_PATH, index=False, encoding="utf-8-sig")
    return df

def coletar_exterior_completo(max_workers=20):
    """
    Executa a coleta de todas as 186 cidades no exterior + consolidado ZZ.
    Retorna o DataFrame compilado.
    """
    df_dic = carregar_dicionario_exterior()
    total_cidades = len(df_dic)
    
    print("=" * 68)
    print(f"APURAÇÃO PRESIDENCIAL NO EXTERIOR (ZZ) - 2º TURNO (TSE {ELEICAO_ID})")
    print(f"Total de Cidades / Postos Consulares: {total_cidades}")
    print(f"Conexões simultâneas: {max_workers}")
    print("=" * 68)

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers, max_retries=2)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)

    # 1. Coleta consolidado geral do exterior (ZZ)
    url_zz_macro = f"https://resultados.tse.jus.br/oficial/ele2026/{ELEICAO_ID}/dados/zz/zz-{CARGO_ID}-e00{ELEICAO_ID}-u.json"
    dados_zz_macro = None
    try:
        r_macro = session.get(url_zz_macro, verify=False, timeout=8)
        if r_macro.status_code == 200:
            dados_zz_macro = r_macro.json()
    except Exception:
        pass

    t0 = time.time()
    resultados = []

    def fetch_cidade(row):
        cod_tse = str(row['cod_tse']).zfill(5)
        url = f"https://resultados.tse.jus.br/oficial/ele2026/{ELEICAO_ID}/dados/zz/zz{cod_tse}-{CARGO_ID}-e00{ELEICAO_ID}-u.json"

        try:
            r = session.get(url, verify=False, timeout=8)
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

                aptos = int(e_info.get('te', 0) or 0)
                comp = int(e_info.get('c', 0) or 0)
                abst = int(e_info.get('a', 0) or 0)
                brancos = int(v_info.get('vb', 0) or 0)
                nulos = int(v_info.get('vn', 0) or 0)
                total_urnas = int(s_info.get('ts', 0) or 0)
                urnas_apuradas = s_info.get('pst', '0,00%')

                return {
                    'cod_tse': cod_tse,
                    'Cidade': row['Cidade'],
                    'Pais': row['Pais'],
                    'UF': 'ZZ',
                    'Lula': lula,
                    'Flávio Bolsonaro': flavio,
                    'Total_Validos': total_val,
                    'Eleitores_Aptos': aptos,
                    'Comparecimento': comp,
                    'Abstencao': abst,
                    'Brancos': brancos,
                    'Nulos': nulos,
                    'Urnas_Total': total_urnas,
                    'Urnas_Apuradas': f"{urnas_apuradas}%" if not str(urnas_apuradas).endswith('%') else urnas_apuradas
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

    print(f"Iniciando varredura das {total_cidades} cidades no exterior...")
    linhas = [row for _, row in df_dic.iterrows()]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for i, res in enumerate(executor.map(fetch_cidade, linhas), 1):
            resultados.append(res)

    tempo_total = time.time() - t0
    print(f"✔ Varredura das {total_cidades} cidades concluída em {tempo_total:.2f} segundos!")

    df = pd.DataFrame(resultados)
    
    # Cálculos analíticos
    mask = df['Total_Validos'] > 0
    df['Lula_percentual'] = "0,00%"
    df['Bolsonaro_percentual'] = "0,00%"

    df.loc[mask, 'Lula_percentual'] = (df['Lula'] / df['Total_Validos'] * 100).round(2).apply(lambda v: f"{v:.2f}%".replace(".", ","))
    df.loc[mask, 'Bolsonaro_percentual'] = (df['Flávio Bolsonaro'] / df['Total_Validos'] * 100).round(2).apply(lambda v: f"{v:.2f}%".replace(".", ","))
    df['Diferença'] = df['Lula'] - df['Flávio Bolsonaro']

    def calc_vencedor(row):
        if row['Lula'] > row['Flávio Bolsonaro']:
            return 'Lula'
        elif row['Flávio Bolsonaro'] > row['Lula']:
            return 'Flávio Bolsonaro'
        return 'Empate'

    df['Vencedor'] = df.apply(calc_vencedor, axis=1)

    # Ordena pelos maiores colégios eleitorais no exterior
    df.sort_values(by='Eleitores_Aptos', ascending=False, inplace=True)

    # Salva CSVs de exportação
    path_csv_root = os.path.join(BASE_DIR, "presidente_exterior_resultado_direto.csv")
    path_csv_recortes = os.path.join(PASTA_RECORTES, "mapa_exterior_presidentes_2turno.csv")

    colunas_ordenadas = [
        'cod_tse', 'Cidade', 'Pais', 'UF',
        'Lula', 'Flávio Bolsonaro', 'Total_Validos',
        'Lula_percentual', 'Bolsonaro_percentual', 'Diferença', 'Vencedor',
        'Eleitores_Aptos', 'Urnas_Total', 'Urnas_Apuradas',
        'Comparecimento', 'Abstencao', 'Brancos', 'Nulos'
    ]
    df = df[colunas_ordenadas]

    df.to_csv(path_csv_root, index=False, sep=";", encoding="utf-8-sig")
    df.to_csv(path_csv_recortes, index=False, sep=";", encoding="utf-8-sig")
    print(f"Resultados locais salvos em: {path_csv_root}")

    return df

if __name__ == "__main__":
    df_resultado = coletar_exterior_completo(max_workers=20)
    print("\nTop 10 Maiores Colégios Eleitorais no Exterior:")
    print(df_resultado[['Cidade', 'Pais', 'Eleitores_Aptos', 'Urnas_Total', 'Lula', 'Flávio Bolsonaro', 'Vencedor']].head(10).to_string(index=False))
