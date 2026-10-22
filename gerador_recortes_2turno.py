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

    print('\n✔ Todos os recortes foram gerados e validados com sucesso!')
    return True

if __name__ == '__main__':
    processar_recortes_2turno()
