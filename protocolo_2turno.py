import os
import sys
import time
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
PROTOCOLO PRESIDENCIAL 2º TURNO - FOCO MUNICIPAL BRASIL (5.571 MUNICÍPIOS)
==========================================================================
Executa o fluxo completo focado exclusivamente na disputa presidencial:
  1. COLETAR & APURAR: Baixa os votos dos 5.571 municípios do Brasil (TSE 6258)
  2. FORMATAR: Monta as tabelas para os mapas do Flourish (com vencedor, margem e percentuais)
  3. PREENCHER: Atualiza as abas no Google Sheets e salva CSVs de backup locais
"""

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    import coletor_presidente_municipios_2turno
    import publicador_sheets_2turno
except ImportError:
    from Script_2 import coletor_presidente_municipios_2turno, publicador_sheets_2turno

def executar_ciclo_presidencial_completo(planilha=None, workers=40):
    """
    Executa uma rodada completa da apuração presidencial municipal:
    1. Coleta e consolidação dos 5.571 municípios
    2. Publicação no Google Sheets
    """
    hora_inicio = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    t0 = time.time()

    print("\n" + "=" * 70)
    print(f">> INICIANDO PROTOCOLO PRESIDENCIAL MUNICIPAL 2º TURNO - [{hora_inicio}]")
    print("=" * 70)

    # -------------------------------------------------------------
    # ETAPA 1 & 2: COLETA & RECORTES DOS 5.571 MUNICÍPIOS DO BRASIL
    # -------------------------------------------------------------
    print("\n[ETAPA 1/2] Apurando os 5.571 municípios do Brasil direto do TSE...")
    tabelas = coletor_presidente_municipios_2turno.coletar_municipios_brasil(max_workers=workers)

    # -------------------------------------------------------------
    # ETAPA 3: PREENCHIMENTO NO GOOGLE SHEETS
    # -------------------------------------------------------------
    print("\n[ETAPA 2/2] Atualizando abas no Google Sheets...")
    if planilha is None:
        planilha = publicador_sheets_2turno.conectar_planilha()

    if planilha:
        publicador_sheets_2turno.publicar_tabelas(planilha, tabelas)
    else:
        print("  [AVISO] Conexão com Google Sheets pendente (dados salvos nos CSVs locais).")

    tempo_total = round(time.time() - t0, 1)
    print("\n" + "-" * 70)
    print(f"[OK] APURAÇÃO MUNICIPAL CONCLUÍDA COM SUCESSO EM {tempo_total}s!")
    print("-" * 70 + "\n")
    return planilha

def rodar_loop(intervalo_segundos=60, workers=40):
    """Loop contínuo para o domingo de apuração."""
    print("=" * 70)
    print("APURAÇÃO PRESIDENCIAL MUNICIPAL - MODO CONTÍNUO (TEMPO REAL)")
    print(f"Intervalo entre ciclos: {intervalo_segundos} segundos | Workers: {workers}")
    print("=" * 70)

    planilha = publicador_sheets_2turno.conectar_planilha()
    ciclo = 1

    while True:
        print(f"\n>>> INICIANDO CICLO MUNICIPAL #{ciclo} <<<")
        try:
            planilha = executar_ciclo_presidencial_completo(planilha=planilha, workers=workers)
        except Exception as e:
            print(f"[ERRO] Falha no ciclo #{ciclo}: {e}")
            time.sleep(5)
            planilha = publicador_sheets_2turno.conectar_planilha()

        print(f"Aguardando {intervalo_segundos}s para o próximo ciclo de apuração municipal...")
        ciclo += 1
        time.sleep(intervalo_segundos)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Protocolo Presidencial 2º Turno por Município (5.571 cidades)")
    parser.add_argument("--once", action="store_true", help="Executa apenas uma varredura completa")
    parser.add_argument("--intervalo", type=int, default=60, help="Intervalo em segundos entre ciclos (padrão: 60)")
    parser.add_argument("--workers", type=int, default=40, help="Número de conexões simultâneas (padrão: 40)")
    args = parser.parse_args()

    if args.once:
        executar_ciclo_presidencial_completo(workers=args.workers)
    else:
        rodar_loop(intervalo_segundos=args.intervalo, workers=args.workers)
