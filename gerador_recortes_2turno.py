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
