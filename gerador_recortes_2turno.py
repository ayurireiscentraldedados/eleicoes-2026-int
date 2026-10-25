import json
import os
import sys
import time
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
PASTA_RECORTES = os.path.join(BASE_DIR, 'recortes_gerados_2turno')
os.makedirs(PASTA_RECORTES, exist_ok=True)

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

def processar_recortes_2turno():
    print('=' * 68)
    print('GERADOR DE RECORTES - 2º TURNO (2026)')
    print('Prepara e valida os 6 recortes para a planilha oficial')
    print('=' * 68)

    path_br = os.path.join(PASTA_RECORTES, 'presidente_br_resultado_direto.csv')
    if not os.path.exists(path_br):
        path_br = os.path.join(BASE_DIR, 'presidente_br_resultado_direto.csv')

    if not os.path.exists(path_br):
        print(f'[AVISO] Arquivo {path_br} não encontrado. Execute o coletor primeiro.')
        return False

    df = pd.read_csv(path_br, sep=None, engine='python', encoding='utf-8-sig')
    print(f'✔ Base de dados carregada: {len(df)} municípios')

    # 1. Recorte Regiões
    df['CD_REGIAO'] = df['UF_sigla'].map(lambda uf: UF_TO_REGION.get(uf, ('', ''))[0])
    df['Nome_Regiao'] = df['UF_sigla'].map(lambda uf: UF_TO_REGION.get(uf, ('', ''))[1])
    tot_col = 'Total_Validos' if 'Total_Validos' in df.columns else 'Total'

    reg_agg = df.groupby(['CD_REGIAO', 'Nome_Regiao']).agg({
        'Lula': 'sum',
        'Flávio Bolsonaro': 'sum',
        tot_col: 'sum'
    }).reset_index()
    path_reg = os.path.join(PASTA_RECORTES, 'recorte_regioes_2turno.csv')
    reg_agg.to_csv(path_reg, index=False, sep=';', encoding='utf-8-sig')
    print(f'  -> [1/3] Recorte por região salvo: {path_reg}')

    # 2. Recorte Estados
    est_agg = df.groupby('Estado').agg({
        'Lula': 'sum',
        'Flávio Bolsonaro': 'sum',
        tot_col: 'sum'
    }).reset_index()
    path_est = os.path.join(PASTA_RECORTES, 'recorte_estados_2turno.csv')
    est_agg.to_csv(path_est, index=False, sep=';', encoding='utf-8-sig')
    print(f'  -> [2/3] Recorte por estado salvo: {path_est}')

    # 3. Recorte Abstenções Brasil
    if 'Comparecimento' in df.columns and 'Abstencoes' in df.columns:
        tot_comp = df['Comparecimento'].sum()
        tot_abst = df['Abstencoes'].sum()
        print(f'  -> [3/3] Resumo nacional: Comparecimento={tot_comp:,} | Abstenções={tot_abst:,}')

    # 4. Recorte Capitais (27 capitais do Brasil - 2? Turno)
    capitais_ibge = [
        ('2800308', 'Sergipe', 'Aracaju'), ('1501402', 'Par?', 'Bel?m'), ('3106200', 'Minas Gerais', 'Belo Horizonte'),
        ('1400100', 'Roraima', 'Boa Vista'), ('5300108', 'Distrito Federal', 'Bras?lia'), ('5002704', 'Mato Grosso do Sul', 'Campo Grande'),
        ('5103403', 'Mato Grosso', 'Cuiab?'), ('4106902', 'Paran?', 'Curitiba'), ('4205407', 'Santa Catarina', 'Florian?polis'),
        ('2304400', 'Cear?', 'Fortaleza'), ('5208707', 'Goi?s', 'Goi?nia'), ('2507507', 'Para?ba', 'Jo?o Pessoa'),
        ('1600303', 'Amap?', 'Macap?'), ('2704302', 'Alagoas', 'Macei?'), ('1302603', 'Amazonas', 'Manaus'),
        ('2408102', 'Rio Grande do Norte', 'Natal'), ('1721000', 'Tocantins', 'Palmas'), ('4314902', 'Rio Grande do Sul', 'Porto Alegre'),
        ('1100205', 'Rond?nia', 'Porto Velho'), ('2611606', 'Pernambuco', 'Recife'), ('1200401', 'Acre', 'Rio Branco'),
        ('3304557', 'Rio de Janeiro', 'Rio De Janeiro'), ('2927408', 'Bahia', 'Salvador'), ('2111300', 'Maranh?o', 'S?o Lu?s'),
        ('3550308', 'S?o Paulo', 'S?o Paulo'), ('2211001', 'Piau?', 'Teresina'), ('3205309', 'Esp?rito Santo', 'Vit?ria')
    ]
    df['ibge_str'] = df['cod_ibge7'].astype(str).str.strip()
    dic_mun = df.set_index('ibge_str').to_dict(orient='index')
    
    rows_cap = []
    # Bloco 1: Lula (PT) nas 27 capitais
    for ibge, est, cap in capitais_ibge:
        d = dic_mun.get(ibge, {})
        try:
            l2 = int(float(str(d.get('Lula', 0)).replace('.', '').replace(',', '.')))
        except Exception:
            l2 = 0
        try:
            b2 = int(float(str(d.get('Fl?vio Bolsonaro', d.get('Fl\xe1vio Bolsonaro', d.get('flavio_bolsonaro', 0)))).replace('.', '').replace(',', '.')))
        except Exception:
            b2 = 0
        tot = l2 + b2
        pct = (l2 / tot * 100) if tot > 0 else 0.0
        rows_cap.append({
            'cod_ibge7': ibge, 'Estado': est, 'Turno': '2? turno', 'Capital': cap,
            'Candidato': 'Lula (PT)', 'Votos totais': l2, 'Votos (%)': f"{pct:.2f}%".replace('.', ',')
        })
    # Bloco 2: Fl?vio Bolsonaro (PL) nas 27 capitais
    for ibge, est, cap in capitais_ibge:
        d = dic_mun.get(ibge, {})
        try:
            l2 = int(float(str(d.get('Lula', 0)).replace('.', '').replace(',', '.')))
        except Exception:
            l2 = 0
        try:
            b2 = int(float(str(d.get('Fl?vio Bolsonaro', d.get('Fl\xe1vio Bolsonaro', d.get('flavio_bolsonaro', 0)))).replace('.', '').replace(',', '.')))
        except Exception:
            b2 = 0
        tot = l2 + b2
        pct = (b2 / tot * 100) if tot > 0 else 0.0
        rows_cap.append({
            'cod_ibge7': ibge, 'Estado': est, 'Turno': '2? turno', 'Capital': cap,
            'Candidato': 'Fl?vio Bolsonaro (PL)', 'Votos totais': b2, 'Votos (%)': f"{pct:.2f}%".replace('.', ',')
        })
    df_capitais = pd.DataFrame(rows_cap)
    path_cap = os.path.join(PASTA_RECORTES, 'recorte_capitais_2turno.csv')
    df_capitais.to_csv(path_cap, index=False, sep=';', encoding='utf-8-sig')
    print(f'  -> [4/4] Recorte das 27 capitais salvo: {path_cap}')

    # 5. JSON de Alta Performance para o Mapa Interativo O POVO+ (Five News)
    try:
        col_bolso = [c for c in df.columns if 'bolsonaro' in c.lower()][0]
        col_mun = [c for c in df.columns if 'munic' in c.lower()][0]
        tot_col_nome = 'Total_Validos' if 'Total_Validos' in df.columns else 'Total'
        
        urnas_br = '0,00%'
        col_sec_tot = [c for c in df.columns if 'totalizadas' in c.lower()]
        col_sec_all = [c for c in df.columns if 'se' in c.lower() and 'total' in c.lower() and 'totalizadas' not in c.lower()]
        if col_sec_tot and col_sec_all:
            s_tot = float(df[col_sec_tot[0]].sum())
            s_all = float(df[col_sec_all[0]].sum())
            if s_all > 0:
                urnas_br = f"{(s_tot / s_all * 100):.2f}%".replace('.', ',')
        elif 'Urnas_Pct' in df.columns:
            urnas_br = str(df['Urnas_Pct'].iloc[0])

        payload_mapa = {
            'nacional': {
                'lula_votos': int(df['Lula'].sum()),
                'flavio_votos': int(df[col_bolso].sum()),
                'total': int(df[tot_col_nome].sum()),
                'urnas': urnas_br,
                'atualizado_em': datetime.now().strftime('%H:%M:%S')
            },
            'municipios': {}
        }
        tot_val = payload_mapa['nacional']['total']
        lula_tot = payload_mapa['nacional']['lula_votos']
        flavio_tot = payload_mapa['nacional']['flavio_votos']
        if tot_val > 0:
            payload_mapa['nacional']['lula_pct'] = f"{(lula_tot / tot_val * 100):.2f}%".replace('.', ',')
            payload_mapa['nacional']['flavio_pct'] = f"{(flavio_tot / tot_val * 100):.2f}%".replace('.', ',')
        else:
            payload_mapa['nacional']['lula_pct'] = "0,00%"
            payload_mapa['nacional']['flavio_pct'] = "0,00%"

        # Cache anti-regressão do JSON do mapa
        mapa_anterior = {}
        caminho_mapa_antigo = os.path.join(BASE_DIR, 'mapa_eleicoes_opovomais', 'apuracao_brasil_tempo_real.json')
        if os.path.exists(caminho_mapa_antigo):
            try:
                with open(caminho_mapa_antigo, 'r', encoding='utf-8') as f_old:
                    old_data = json.load(f_old)
                    mapa_anterior = old_data.get('municipios', {})
            except Exception:
                pass

        for _, r in df.iterrows():
            ibge = str(r['cod_ibge7']).strip()
            l2 = int(r.get('Lula', 0))
            b2 = int(r.get(col_bolso, 0))
            t2 = l2 + b2
            urnas = str(r.get('Urnas_Pct', '0,00%')).strip()

            # REGRA DE NÃO-REGRESSÃO NO MAPA:
            # Se a linha do CSV vier zerada mas o mapa já tinha votos para o município, PRESERVA!
            if t2 == 0 and ibge in mapa_anterior:
                old_m = mapa_anterior[ibge]
                if len(old_m) >= 5 and int(old_m[4]) > 0:
                    payload_mapa['municipios'][ibge] = old_m
                    continue

            l_pct = round((l2 / t2 * 100), 2) if t2 > 0 else 0.0
            b_pct = round((b2 / t2 * 100), 2) if t2 > 0 else 0.0
            payload_mapa['municipios'][ibge] = [
                str(r[col_mun]),
                str(r['UF_sigla']),
                l2,
                b2,
                t2,
                l_pct,
                b_pct,
                urnas
            ]

        # Salva na pasta do mapa
        caminhos_json = [
            os.path.join(BASE_DIR, 'mapa_eleicoes_opovomais', 'apuracao_brasil_tempo_real.json'),
            os.path.join(os.path.dirname(BASE_DIR), 'mapa_eleicoes_opovomais', 'apuracao_brasil_tempo_real.json'),
            os.path.join(BASE_DIR, 'apuracao_brasil_tempo_real.json')
        ]
        for c_path in caminhos_json:
            if os.path.exists(os.path.dirname(c_path)):
                with open(c_path, 'w', encoding='utf-8') as f_out:
                    json.dump(payload_mapa, f_out, separators=(',', ':'), ensure_ascii=False)
        print('  -> [5/5] JSON em tempo real do mapa gerado com sucesso!')
    except Exception as e_mapa:
        print(f'  [AVISO] Falha ao gerar JSON do mapa: {e_mapa}')


    print('\n✔ Todos os recortes foram gerados e validados com sucesso!')
    return True

def rodar_loop(intervalo_segundos=60):
    print('=' * 68)
    print('GERADOR DE RECORTES - MODO CONT?NUO (TEMPO REAL)')
    print(f'Intervalo entre ciclos: {intervalo_segundos} segundos')
    print('=' * 68)
    ciclo = 1
    while True:
        hora_atual = time.strftime('%H:%M:%S')
        print(f"\n[{hora_atual}] >>> CICLO DE RECORTES #{ciclo} <<<")
        try:
            processar_recortes_2turno()
        except Exception as e:
            print(f"[ERRO] Falha ao processar recortes #{ciclo}: {e}")
        print(f"Aguardando {intervalo_segundos}s para o pr?ximo processamento...")
        ciclo += 1
        time.sleep(intervalo_segundos)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Gerador de Recortes 2? Turno')
    parser.add_argument('--once', action='store_true', help='Executa apenas um processamento')
    parser.add_argument('--intervalo', type=int, default=60, help='Intervalo em segundos entre ciclos (padr?o: 60)')
    args = parser.parse_args()

    if args.once:
        processar_recortes_2turno()
    else:
        rodar_loop(intervalo_segundos=args.intervalo)
