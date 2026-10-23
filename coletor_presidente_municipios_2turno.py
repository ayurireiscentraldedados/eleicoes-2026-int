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

# Suporte a UTF-8 no terminal Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

"""
COLETOR & APURADOR DE DADOS PRESIDENCIAIS POR MUNICÍPIO - 2º TURNO (2026)
-------------------------------------------------------------------------
Monitora todos os 5.571 municípios do Brasil diretamente do CDN oficial do TSE:
- Eleição Federal 2º Turno: 6258
- Cargo: Presidente (c0001)
- Coleta completa: Lula, Flávio, Total, Urnas Apuradas, Brancos, Nulos, Abstenção, Comparecimento
- Concorrência de alta performance (40 conexões simultâneas)
"""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DICIONARIO_PATH = os.path.join(BASE_DIR, "dicionario_municipios_brasil.csv")
PASTA_RECORTES = os.path.join(BASE_DIR, "recortes_gerados_2turno")
os.makedirs(PASTA_RECORTES, exist_ok=True)

ELEICAO_ID = "6258"  # 2º Turno Oficial TSE (Presidente)
CARGO_ID = "c0001"   # Presidente

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

def carregar_dicionario_municipios():
    """Carrega o dicionário base de 5.571 municípios com cod_tse e cod_ibge7."""
    if os.path.exists(DICIONARIO_PATH):
        try:
            return pd.read_csv(DICIONARIO_PATH, sep=None, engine='python', encoding="utf-8-sig")
        except Exception:
            return pd.read_csv(DICIONARIO_PATH, sep=',', encoding="utf-8")
    
    print("[Aviso] Dicionário local não encontrado. Baixando do TSE...")
    url_mun = f"https://resultados.tse.jus.br/oficial/ele2026/{ELEICAO_ID}/config/mun-e00{ELEICAO_ID}-cm.json"
    r = requests.get(url_mun, headers=HEADERS, verify=False, timeout=15)
    data = r.json()
    
    sigla_para_estado = {
        'ac': 'Acre', 'al': 'Alagoas', 'am': 'Amazonas', 'ap': 'Amapá', 'ba': 'Bahia',
        'ce': 'Ceará', 'df': 'Distrito Federal', 'es': 'Espírito Santo',
        'go': 'Goiás', 'ma': 'Maranhão', 'mt': 'Mato Grosso', 'ms': 'Mato Grosso do Sul',
        'mg': 'Minas Gerais', 'pa': 'Pará', 'pb': 'Paraíba', 'pr': 'Paraná',
        'pe': 'Pernambuco', 'pi': 'Piauí', 'rj': 'Rio de Janeiro', 'rn': 'Rio Grande do Norte',
        'rs': 'Rio Grande do Sul', 'ro': 'Rondônia', 'rr': 'Roraima', 'sc': 'Santa Catarina',
        'sp': 'São Paulo', 'se': 'Sergipe', 'to': 'Tocantins'
    }
    
    municipios = []
    for u in data.get('abr', []):
        sigla = u.get('cd', '').lower()
        if sigla in ['zz', 'br']:
            continue
        nome_estado = sigla_para_estado.get(sigla, sigla.upper())
        for m in u.get('mu', []):
            municipios.append({
                'cod_mun': str(m.get('cd')).zfill(5),
                'cod_ibge7': str(m.get('cdi')),
                'Estado': nome_estado,
                'Município': m.get('nm', '').title(),
                'UF_sigla': sigla.upper()
            })
            
    df = pd.DataFrame(municipios)
    df.sort_values(by=['Estado', 'Município'], inplace=True)
    df.to_csv(DICIONARIO_PATH, index=False, encoding="utf-8-sig")
    return df

def coletar_municipios_brasil(max_workers=40):
    """
    Executa a coleta concorrente de todos os 5.571 municípios do Brasil para Presidente no 2º Turno.
    Extrai votos válidos, brancos, nulos, abstenções, comparecimento e urnas apuradas.
    """
    df_dicionario = carregar_dicionario_municipios()
    total_mun = len(df_dicionario)
    
    print("=" * 68)
    print(f"APURAÇÃO PRESIDENCIAL POR MUNICÍPIO - 2º TURNO (TSE {ELEICAO_ID})")
    print(f"Total de Municípios no Brasil: {total_mun}")
    print(f"Conexões simultâneas: {max_workers}")
    print("=" * 68)
    
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers, max_retries=2)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)
    
    t0 = time.time()
    resultados = []
    
    def fetch_item(row):
        sigla = str(row['UF_sigla']).lower()
        cd_tse = str(row['cod_mun']).zfill(5)
        url = f"https://resultados.tse.jus.br/oficial/ele2026/{ELEICAO_ID}/dados/{sigla}/{sigla}{cd_tse}-{CARGO_ID}-e00{ELEICAO_ID}-u.json"
        
        try:
            r = session.get(url, verify=False, timeout=8)
            if r.status_code == 200:
                d = r.json()
                lula = 0
                flavio = 0
                
                # Votos dos candidatos
                for c in d.get('carg', []):
                    for agr in c.get('agr', []):
                        for par in agr.get('par', []):
                            for cand in par.get('cand', []):
                                n = cand.get('nmu') or cand.get('nm') or ''
                                v = int(cand.get('vap', 0))
                                if 'LULA' in n.upper():
                                    lula += v
                                elif 'FLAVIO' in n.upper() or 'FLÁVIO' in n.upper():
                                    flavio += v
                
                total_validos = lula + flavio
                
                # Informações de urnas
                s_info = d.get('s', {})
                pst = s_info.get('pst', '0,00')
                urnas_pct_str = f"{pst}%" if not str(pst).endswith('%') else str(pst)
                st = int(s_info.get('st', s_info.get('sa', 0)))
                ts = int(s_info.get('ts', 0))
                
                # Informações de eleitorado
                e_info = d.get('e', {})
                aptos = int(e_info.get('te', 0))
                abst = int(e_info.get('a', 0))
                
                # Informações de votos
                v_info = d.get('v', {})
                comp = int(e_info.get('c', v_info.get('tv', 0)))
                brancos = int(v_info.get('vb', 0))
                nulos = int(v_info.get('tvn', v_info.get('vn', 0)))
                
                # Percentuais
                lula_pct = (lula / total_validos * 100) if total_validos > 0 else 0.0
                flavio_pct = (flavio / total_validos * 100) if total_validos > 0 else 0.0
                diff_pct = (lula_pct - flavio_pct) if total_validos > 0 else 0.0
                
                br_pct = (brancos / comp * 100) if comp > 0 else 0.0
                nu_pct = (nulos / comp * 100) if comp > 0 else 0.0
                ab_pct = (abst / aptos * 100) if aptos > 0 else 0.0
                co_pct = (comp / aptos * 100) if aptos > 0 else 0.0
                
                if total_validos == 0:
                    vencedor = 'Aguardando'
                elif lula > flavio:
                    vencedor = 'Lula'
                elif flavio > lula:
                    vencedor = 'Flávio Bolsonaro'
                else:
                    vencedor = 'Empate'
                    
                return {
                    'cod_ibge7': str(row['cod_ibge7']),
                    'cod_mun': cd_tse,
                    'Estado': row['Estado'],
                    'Município': row['Município'],
                    'UF_sigla': row['UF_sigla'],
                    'Lula': lula,
                    'Flávio Bolsonaro': flavio,
                    'Total_Validos': total_validos,
                    'Lula_percentual': f"{lula_pct:.2f}%".replace('.', ','),
                    'Bolsonaro_percentual': f"{flavio_pct:.2f}%".replace('.', ','),
                    'Diferença': f"{diff_pct:.2f}".replace('.', ','),
                    'Vencedor': vencedor,
                    'Urnas_Pct': urnas_pct_str,
                    'Seções_Totalizadas': st,
                    'Seções_Total': ts,
                    'Brancos': brancos,
                    'Nulos': nulos,
                    'Abstencoes': abst,
                    'Comparecimento': comp,
                    'Total_Aptos': aptos,
                    'Branco_pct': f"{br_pct:.2f}%".replace('.', ','),
                    'Nulo_pct': f"{nu_pct:.2f}%".replace('.', ','),
                    'Abst_pct': f"{ab_pct:.2f}%".replace('.', ','),
                    'Comp_pct': f"{co_pct:.2f}%".replace('.', ',')
                }
        except Exception:
            pass
            
        return {
            'cod_ibge7': str(row['cod_ibge7']),
            'cod_mun': cd_tse,
            'Estado': row['Estado'],
            'Município': row['Município'],
            'UF_sigla': row['UF_sigla'],
            'Lula': 0,
            'Flávio Bolsonaro': 0,
            'Total_Validos': 0,
            'Lula_percentual': "0,00%",
            'Bolsonaro_percentual': "0,00%",
            'Diferença': "0,00",
            'Vencedor': 'Aguardando',
            'Urnas_Pct': "0,00%",
            'Seções_Totalizadas': 0,
            'Seções_Total': 0,
            'Brancos': 0,
            'Nulos': 0,
            'Abstencoes': 0,
            'Comparecimento': 0,
            'Total_Aptos': 0,
            'Branco_pct': "0,00%",
            'Nulo_pct': "0,00%",
            'Abst_pct': "0,00%",
            'Comp_pct': "0,00%"
        }

    print(f"Iniciando varredura em tempo real dos {total_mun} municípios...")
    linhas = [row for _, row in df_dicionario.iterrows()]
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for i, res in enumerate(executor.map(fetch_item, linhas), 1):
            resultados.append(res)
            if i % 1000 == 0 or i == total_mun:
                taxa = i / (time.time() - t0)
                print(f"  -> {i}/{total_mun} municípios apurados ({taxa:.1f} mun/s)...")
                
    tempo_total = time.time() - t0
    print(f"\n[OK] Apuracao dos {total_mun} municipios concluida em {tempo_total:.1f} segundos!")    
    df = pd.DataFrame(resultados)
    
    # Salva CSVs locais para backup imediato
    path_csv_1 = os.path.join(PASTA_RECORTES, "mapa_brasil_presidentes_2turno.csv")
    path_csv_2 = os.path.join(PASTA_RECORTES, "presidente_br_resultado_direto.csv")
    path_csv_root = os.path.join(BASE_DIR, "presidente_br_resultado_direto.csv")
    
    df.to_csv(path_csv_1, index=False, sep=";", encoding="utf-8-sig")
    df.to_csv(path_csv_2, index=False, sep=";", encoding="utf-8-sig")
    df.to_csv(path_csv_root, index=False, sep=";", encoding="utf-8-sig")
    print(f"Backups locais salvos em: {path_csv_2}")
    
    return df

def rodar_loop(intervalo_segundos=60, workers=40):
    print("=" * 70)
    print("COLETOR PRESIDENCIAL MUNICIPAL - MODO CONT?NUO (TEMPO REAL)")
    print(f"Intervalo entre ciclos: {intervalo_segundos} segundos | Workers: {workers}")
    print("=" * 70)
    ciclo = 1
    while True:
        hora_atual = datetime.now().strftime('%H:%M:%S')
        print(f"\n[{hora_atual}] >>> CICLO DE COLETA MUNICIPAL #{ciclo} <<<")
        try:
            coletar_municipios_brasil(max_workers=workers)
        except Exception as e:
            print(f"[ERRO] Falha na coleta municipal #{ciclo}: {e}")
        print(f"Aguardando {intervalo_segundos}s para o pr?ximo ciclo de coleta...")
        ciclo += 1
        time.sleep(intervalo_segundos)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Coletor Munic?pios 2? Turno")
    parser.add_argument("--once", action="store_true", help="Executa apenas uma varredura")
    parser.add_argument("--intervalo", type=int, default=60, help="Intervalo em segundos entre ciclos (padr?o: 60)")
    parser.add_argument("--workers", type=int, default=40, help="N?mero de conex?es simult?neas (padr?o: 40)")
    args = parser.parse_args()

    if args.once:
        coletar_municipios_brasil(max_workers=args.workers)
    else:
        rodar_loop(intervalo_segundos=args.intervalo, workers=args.workers)
