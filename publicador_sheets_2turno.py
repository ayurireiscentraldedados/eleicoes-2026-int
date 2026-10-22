import os
import sys
import pandas as pd

# Garante suporte a UTF-8 no terminal Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from servidor_remoto_2turno import sincronizar_google_sheets

def publicar_recortes_2turno():
    print('=' * 65)
    print('PUBLICADOR GOOGLE SHEETS - 2º TURNO (2026)')
    print('Planilha: Central das eleições - segundo turno')
    print('=' * 65)

    csv_br_candidatos = [
        os.path.join(BASE_DIR, 'recortes_gerados_2turno', 'mapa_brasil_presidentes_2turno.csv'),
        os.path.join(BASE_DIR, 'recortes_gerados_2turno', 'presidente_br_resultado_direto.csv'),
        os.path.join(BASE_DIR, 'presidente_br_resultado_direto.csv'),
    ]
    csv_ext_candidatos = [
        os.path.join(BASE_DIR, 'recortes_gerados_2turno', 'mapa_exterior_presidentes_2turno.csv'),
        os.path.join(BASE_DIR, 'recortes_gerados_2turno', 'presidente_exterior_resultado_direto.csv'),
        os.path.join(BASE_DIR, 'presidente_exterior_resultado_direto.csv'),
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

    sucesso = sincronizar_google_sheets(df_brasil=df_br, df_exterior=df_ext)
    if sucesso:
        print('\n✔ Publicação no Google Sheets concluída com 100% de sucesso!')
    else:
        print('\n✖ Houve falha na sincronização com o Google Sheets.')
    return sucesso

if __name__ == '__main__':
    publicar_recortes_2turno()
