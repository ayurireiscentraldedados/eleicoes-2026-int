import os
import sys
import time
import argparse
import pandas as pd
from datetime import datetime

# Garante suporte a UTF-8 no terminal Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
for p in [BASE_DIR, PARENT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import importlib
import servidor_remoto_2turno

def publicar_recortes_2turno():
    print('=' * 65)
    print('PUBLICADOR GOOGLE SHEETS - 2? TURNO (2026)')
    print('Planilha: Central das elei??es - segundo turno')
    print('=' * 65)

    csv_br_candidatos = [
        os.path.join(BASE_DIR, 'recortes_gerados_2turno', 'mapa_brasil_presidentes_2turno.csv'),
        os.path.join(BASE_DIR, 'recortes_gerados_2turno', 'presidente_br_resultado_direto.csv'),
        os.path.join(BASE_DIR, 'presidente_br_resultado_direto.csv'),
        os.path.join(PARENT_DIR, 'recortes_gerados_2turno', 'mapa_brasil_presidentes_2turno.csv'),
        os.path.join(PARENT_DIR, 'recortes_gerados_2turno', 'presidente_br_resultado_direto.csv'),
        os.path.join(PARENT_DIR, 'presidente_br_resultado_direto.csv'),
    ]
    csv_ext_candidatos = [
        os.path.join(BASE_DIR, 'recortes_gerados_2turno', 'mapa_exterior_presidentes_2turno.csv'),
        os.path.join(BASE_DIR, 'recortes_gerados_2turno', 'presidente_exterior_resultado_direto.csv'),
        os.path.join(BASE_DIR, 'presidente_exterior_resultado_direto.csv'),
        os.path.join(PARENT_DIR, 'recortes_gerados_2turno', 'mapa_exterior_presidentes_2turno.csv'),
        os.path.join(PARENT_DIR, 'recortes_gerados_2turno', 'presidente_exterior_resultado_direto.csv'),
        os.path.join(PARENT_DIR, 'presidente_exterior_resultado_direto.csv'),
    ]

    df_br = None
    for p in csv_br_candidatos:
        if os.path.exists(p):
            try:
                df_br = pd.read_csv(p, sep=None, engine='python', encoding='utf-8-sig')
                print(f'[OK] Dados Brasil carregados: {p} ({len(df_br)} linhas)')
                break
            except Exception:
                pass

    df_ext = None
    for p in csv_ext_candidatos:
        if os.path.exists(p):
            try:
                df_ext = pd.read_csv(p, sep=None, engine='python', encoding='utf-8-sig')
                print(f'[OK] Dados Exterior carregados: {p} ({len(df_ext)} linhas)')
                break
            except Exception:
                pass

    if df_br is None and df_ext is None:
        print('[ERRO] Nenhum arquivo CSV de resultado encontrado para publicar.')
        return False

        try:
        importlib.reload(servidor_remoto_2turno)
    except Exception:
        pass
    sucesso = servidor_remoto_2turno.sincronizar_google_sheets(df_brasil=df_br, df_exterior=df_ext)
    if sucesso:
        print('\n? Publica??o no Google Sheets conclu?da com 100% de sucesso!')
    else:
        print('\n? Houve falha na sincroniza??o com o Google Sheets.')
    return sucesso

def rodar_loop(intervalo_segundos=60):
    print('=' * 65)
    print('PUBLICADOR GOOGLE SHEETS - MODO CONT?NUO (TEMPO REAL)')
    print(f'Intervalo entre ciclos: {intervalo_segundos} segundos')
    print('=' * 65)
    ciclo = 1
    while True:
        hora_atual = datetime.now().strftime('%H:%M:%S')
        print(f"\n[{hora_atual}] >>> CICLO DE PUBLICA??O #{ciclo} <<<")
        try:
            publicar_recortes_2turno()
        except Exception as e:
            print(f"[ERRO] Falha na publica??o #{ciclo}: {e}")
        print(f"Aguardando {intervalo_segundos}s para a pr?xima publica??o...")
        ciclo += 1
        time.sleep(intervalo_segundos)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Publicador Google Sheets 2? Turno')
    parser.add_argument('--once', action='store_true', help='Executa apenas uma publica??o')
    parser.add_argument('--intervalo', type=int, default=60, help='Intervalo em segundos entre ciclos (padr?o: 60)')
    args = parser.parse_args()

    if args.once:
        publicar_recortes_2turno()
    else:
        rodar_loop(intervalo_segundos=args.intervalo)
