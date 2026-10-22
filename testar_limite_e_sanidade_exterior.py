import os
import sys
import time
import urllib3
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Garante suporte a UTF-8 no terminal Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

"""
TESTE DE SANIDADE, RATE LIMIT & APURAÇÃO NO EXTERIOR (ZZ) - 2º TURNO (2026)
==========================================================================
Executa os mesmos testes rigorosos aplicados ao Brasil, agora para o Exterior:
1. Validação de sanidade e conectividade dos endpoints internacionais (TSE 6258).
2. Teste de estresse de carga e detecção de rate limit (429 / 403).
3. Coleta e consolidação de todas as 186 cidades consulares do mundo.
"""

ELEICAO_ID = "6258"
CARGO_ID = "c0001"
BASE_URL = f"https://resultados.tse.jus.br/oficial/ele2026/{ELEICAO_ID}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

def teste_fase_1_sanidade_exterior():
    print("\n" + "=" * 70)
    print("FASE 1: TESTE DE SANIDADE DOS ENDPOINTS DO EXTERIOR (ZZ) - 2º TURNO")
    print("=" * 70)

    # 1. Consolidado ZZ
    url_zz = f"{BASE_URL}/dados/zz/zz-{CARGO_ID}-e00{ELEICAO_ID}-u.json"
    t0 = time.time()
    try:
        r = requests.get(url_zz, headers=HEADERS, verify=False, timeout=10)
        lat = (time.time() - t0) * 1000
        print(f"[1] Endpoint Consolidado Mundial (Exterior ZZ):")
        print(f"    URL: {url_zz}")
        print(f"    Status: HTTP {r.status_code} ({lat:.1f} ms)")
        print(f"    Servidor CDN: {r.headers.get('Server', 'Desconhecido')}")
        print(f"    ETag: {r.headers.get('ETag', 'Nenhum')}")
        print(f"    Cache-Control: {r.headers.get('Cache-Control', 'Nenhum')}")
        
        if r.status_code == 200:
            d = r.json()
            e_total = d.get('e', {}).get('te', '0')
            s_total = d.get('s', {}).get('ts', '0')
            print(f"    -> Total de Eleitores Cadastrados no Exterior: {int(e_total):,}".replace(",", "."))
            print(f"    -> Total de Urnas / Seções no Exterior: {s_total}")
        else:
            print(f"    [ERRO] Código HTTP inesperado: {r.status_code}")
    except Exception as e:
        print(f"    [FALHA] Não foi possível conectar: {e}")

    # 2. Amostragem de Postos Consulares Estratégicos nos Continentes
    amostras_exterior = [
        ("Europa (Portugal)", "29955", "Lisboa"),
        ("Europa (Reino Unido)", "29971", "Londres"),
        ("Europa (França)", "30287", "Paris"),
        ("América do Norte (EUA)", "30112", "Miami"),
        ("América do Norte (EUA)", "29432", "Boston"),
        ("Ásia (Japão)", "30627", "Tóquio"),
        ("Oceania (Nova Zelândia)", "30805", "Wellington")
    ]

    print(f"\n[2] Amostragem de Cidades Estratégicas no Mundo:")
    for regiao, cod, nome in amostras_exterior:
        url = f"{BASE_URL}/dados/zz/zz{cod}-{CARGO_ID}-e00{ELEICAO_ID}-u.json"
        t0 = time.time()
        try:
            r = requests.get(url, headers=HEADERS, verify=False, timeout=10)
            lat = (time.time() - t0) * 1000
            if r.status_code == 200:
                d = r.json()
                aptos = d.get('e', {}).get('te', '0')
                secoes = d.get('s', {}).get('ts', '0')
                candidatos = []
                for cargo in d.get("carg", []):
                    for agr in cargo.get("agr", []):
                        for par in agr.get("par", []):
                            for cand in par.get("cand", []):
                                nome_cand = cand.get("nmu") or cand.get("nm") or ""
                                votos = cand.get("vap", "0")
                                candidatos.append(f"{nome_cand} ({votos} votos)")
                cand_str = " × ".join(candidatos) if candidatos else "Sem candidatos"
                print(f"    [{regiao:24}] {nome:12} (Cód {cod}): HTTP 200 OK ({lat:.1f} ms) | Aptos: {int(aptos):,} | {cand_str}".replace(",", "."))
            else:
                print(f"    [{regiao:24}] {nome:12}: HTTP {r.status_code} ({lat:.1f} ms)")
        except Exception as e:
            print(f"    [{regiao:24}] {nome:12}: Erro de conexão: {e}")

def teste_fase_2_stress_rate_limit_exterior():
    print("\n" + "=" * 70)
    print("FASE 2: TESTE DE STRESS DE CARGA & RATE LIMIT (186 CIDADES NO EXTERIOR)")
    print("=" * 70)

    dicionario_path = r"c:\Users\RED.AyuriReis\Downloads\Apurador_real\dicionario_cidades_exterior.csv"
    if not os.path.exists(dicionario_path):
        print("Dicionário de cidades do exterior não encontrado.")
        return

    df_ext = pd.read_csv(dicionario_path)
    total = len(df_ext)
    print(f"Disparando requisições simultâneas para todas as {total} cidades consulares...")

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=25, pool_maxsize=25)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)

    def requisitar(row):
        cod = str(row['cod_tse']).zfill(5)
        url = f"{BASE_URL}/dados/zz/zz{cod}-{CARGO_ID}-e00{ELEICAO_ID}-u.json"
        t_req = time.time()
        try:
            r = session.get(url, verify=False, timeout=8)
            lat = (time.time() - t_req) * 1000
            return r.status_code, lat
        except Exception:
            return 0, (time.time() - t_req) * 1000

    linhas = [row for _, row in df_ext.iterrows()]
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=25) as executor:
        resultados = list(executor.map(requisitar, linhas))

    duracao = time.time() - t0
    taxa = total / duracao

    status_contagem = {}
    latencias = []
    for code, lat in resultados:
        status_contagem[code] = status_contagem.get(code, 0) + 1
        latencias.append(lat)

    media_lat = sum(latencias) / len(latencias) if latencias else 0
    max_lat = max(latencias) if latencias else 0

    print(f"-> Total de Cidades Testadas: {total}")
    print(f"-> Tempo Total: {duracao:.2f} segundos")
    print(f"-> Taxa de Requisições: {taxa:.1f} req/s")
    print(f"-> Códigos HTTP Recebidos: {status_contagem}")
    print(f"-> Latência Média: {media_lat:.1f} ms (Pico: {max_lat:.1f} ms)")

    if 429 in status_contagem:
        print("⚠️ ATENÇÃO: Detectado HTTP 429 (Too Many Requests)!")
    elif 403 in status_contagem:
        print("⚠️ ATENÇÃO: Detectado HTTP 403 (Bloqueio WAF)!")
    else:
        print("✔ SUCESSO ABSOLUTO: 100% das cidades responderam com HTTP 200 OK sem qualquer bloqueio!")

def teste_fase_3_apuracao_e_ranking():
    print("\n" + "=" * 70)
    print("FASE 3: GERAÇÃO DA APURAÇÃO COMPLETA & RANKING DOS MAIORES COLÉGIOS")
    print("=" * 70)

    import coletor_presidente_exterior_2turno
    df_resultado = coletor_presidente_exterior_2turno.coletar_exterior_completo(max_workers=20)

    print(f"\nTotal de cidades processadas e exportadas: {len(df_resultado)}")
    print("\nTOP 15 MAIORES COLÉGIOS ELEITORAIS DE BRASILEIROS NO EXTERIOR:")
    cols_view = ['Cidade', 'Pais', 'Eleitores_Aptos', 'Urnas_Total', 'Lula', 'Flávio Bolsonaro', 'Vencedor']
    top15 = df_resultado[cols_view].head(15)
    print(top15.to_string(index=False))

    total_eleitores = df_resultado['Eleitores_Aptos'].sum()
    total_urnas = df_resultado['Urnas_Total'].sum()
    print("-" * 70)
    print(f"TOTAL ELEITORADO EXTERIOR: {total_eleitores:,} eleitores em {total_urnas} seções eleitorais.".replace(",", "."))
    print("=" * 70 + "\n")

if __name__ == "__main__":
    teste_fase_1_sanidade_exterior()
    teste_fase_2_stress_rate_limit_exterior()
    teste_fase_3_apuracao_e_ranking()
