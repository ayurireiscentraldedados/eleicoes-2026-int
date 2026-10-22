import requests
import time
import json
import os
import sys
import argparse
from datetime import datetime

# Garante suporte a UTF-8 no terminal Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

"""
COLETOR DE DADOS - 2º TURNO (ELEIÇÕES GERAIS 2026)
--------------------------------------------------
Foco exclusivo nas disputas ativas de 2º Turno:
1. Presidente da República: Todas as 27 UFs + BR (Exterior / Consolidado Nacional).
2. Governador: Exclusivamente os 6 estados com 2º turno confirmado:
   - Acre (AC)
   - Amazonas (AM)
   - Distrito Federal (DF)
   - Espírito Santo (ES)
   - Rio Grande do Norte (RN)
   - Tocantins (TO)
"""

estados_padrao = [
    "ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", 
    "mt", "ms", "mg", "pa", "pb", "pr", "pe", "pi", "rj", "rn", 
    "rs", "ro", "rr", "sc", "sp", "se", "to"
]

# Apenas os 6 estados que vão disputar 2º turno para Governador
estados_governador_2t = ["ac", "am", "df", "es", "rn", "to"]

mapa_cargos_estados_2t = {
    "presidente": estados_padrao + ["br"],
    "governador": estados_governador_2t
}

url_base = "https://www.opovo.com.br/reboot_portal/call.php"

parametros_base = {
    "model": "apiApuracao2026",
    "action": "DadosApuracao",
    "turno": "2turno"  # Configurado explicitamente para o 2º Turno
}

def resolver_caminho_brutos():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidatos = [
        os.path.join(script_dir, "dados_brutos_2turno"),
        os.path.join(os.path.dirname(script_dir), "dados_brutos_2turno"),
        r"c:\Users\RED.AyuriReis\Downloads\Apurador_real\dados_brutos_2turno",
        os.path.join(os.getcwd(), "dados_brutos_2turno")
    ]
    for c in candidatos:
        if os.path.exists(c):
            return c
    return candidatos[2]

caminho_salvamento = resolver_caminho_brutos()

def garantir_diretorio():
    """Cria a pasta dados_brutos_2turno se não existir."""
    if not os.path.exists(caminho_salvamento):
        os.makedirs(caminho_salvamento, exist_ok=True)
        print(f"[Setup] Diretório criado: {caminho_salvamento}")

def coletar_uma_rodada():
    """Executa uma varredura completa das 28 chamadas de Presidente + 6 de Governador."""
    total_sucesso = 0
    total_erros = 0
    garantir_diretorio()
    
    for cargo, lista_estados in mapa_cargos_estados_2t.items():
        print(f" -> Coletando 2º Turno: {cargo.upper()} ({len(lista_estados)} chamadas)...")
        
        for sigla in lista_estados:
            parametros = parametros_base.copy()
            parametros["cargo"] = cargo
            parametros["siglaEstado"] = sigla
            
            nome_arquivo = f"{cargo}_{sigla}.json"
            caminho_arquivo = os.path.join(caminho_salvamento, nome_arquivo)
            
            try:
                resposta = requests.get(url_base, params=parametros, timeout=12)
                if resposta.status_code == 200:
                    dados_json = resposta.json()
                    data_obj = dados_json.get("data")
                    
                    # Salva se vier conteúdo ou se o arquivo local ainda não existir
                    if data_obj is not None or not os.path.exists(caminho_arquivo):
                        with open(caminho_arquivo, "w", encoding="utf-8") as arquivo:
                            json.dump(dados_json, arquivo, ensure_ascii=False, indent=4)
                        total_sucesso += 1
                        
                        # Exibe resumo do líder se disponível
                        if data_obj and isinstance(data_obj, dict):
                            cands = data_obj.get("candidates", [])
                            try:
                                votos_totais = int(data_obj.get("number_votes") or 0)
                            except (ValueError, TypeError):
                                votos_totais = 0
                            if cands:
                                lider = cands[0]
                                print(f"    [{sigla.upper()}] Votos: {votos_totais:,} | Líder: {lider.get('name', '')} ({lider.get('party', '')})")
                    else:
                        print(f"    [{sigla.upper()}] API retornou nulo (mantido cache existente).")
                        total_sucesso += 1
                else:
                    print(f"    [AVISO] {cargo} em {sigla.upper()}: HTTP {resposta.status_code}")
                    total_erros += 1
                    
            except Exception as erro:
                print(f"    [ERRO] Falha ao baixar {cargo} em {sigla.upper()}: {erro}")
                total_erros += 1
                
            time.sleep(0.15)
            
    return total_sucesso, total_erros

def rodar_coletor(intervalo_segundos=30):
    """Loop contínuo de monitoramento para o dia da apuração."""
    garantir_diretorio()
    print("=" * 65)
    print("INICIANDO MONITORAMENTO DO 2º TURNO - ELEIÇÕES 2026")
    print(f"Destino dos dados: {caminho_salvamento}")
    print(f"Presidente: 27 UFs + BR | Governador: {', '.join(e.upper() for e in estados_governador_2t)}")
    print(f"Intervalo de varredura: {intervalo_segundos} segundos")
    print("=" * 65)
    
    ciclo = 1
    while True:
        hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        print(f"\n[{hora_atual}] Iniciando Ciclo #{ciclo} de Varredura...")
        
        inicio = time.time()
        ok, erros = coletar_uma_rodada()
        duracao = round(time.time() - inicio, 1)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Ciclo #{ciclo} concluído em {duracao}s. Sucesso: {ok} | Falhas: {erros}")
        print(f"Aguardando {intervalo_segundos}s para a próxima coleta...")
        ciclo += 1
        time.sleep(intervalo_segundos)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coletor API 2º Turno")
    parser.add_argument("--once", action="store_true", help="Executa apenas uma rodada de coleta")
    parser.add_argument("intervalo_pos", nargs="?", type=int, default=None, help="Intervalo posicional em segundos")
    parser.add_argument("--intervalo", type=int, default=30, help="Intervalo em segundos entre varreduras")
    args = parser.parse_args()

    intervalo = args.intervalo_pos if args.intervalo_pos is not None else args.intervalo

    if args.once:
        coletar_uma_rodada()
    else:
        rodar_coletor(intervalo_segundos=intervalo)
