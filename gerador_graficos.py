import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

def gerar_relatorio_final():
    # 1. Definição de caminhos
    diretorio_base = os.path.dirname(os.path.abspath(__file__))
    pasta_resultados = os.path.join(diretorio_base, "relatorio_performance")
    
    if not os.path.exists(pasta_resultados):
        os.makedirs(pasta_resultados)

    # 2. Carregamento dos dados
    try:
        # Carrega o log e o banco de entregadores
        df_log = pd.read_csv('log_entregas.csv', names=["horario", "id_entregador", "id_loja", "status"])
        df_entregadores = pd.read_csv('entregadores.csv')
        
        # Converte horários para datetime para cálculos
        df_log['horario'] = pd.to_datetime(df_log['horario'], format='%H:%M:%S')
    except Exception as e:
        print(f"❌ Erro ao carregar arquivos: {e}")
        return

    # 3. Processamento de Tempo de Ciclo
    df_pivot = df_log.pivot_table(index=['id_entregador', 'id_loja'], 
                                  columns='status', 
                                  values='horario', 
                                  aggfunc='last').reset_index()

    if 'DESPACHADO' in df_pivot and 'ENTREGUE' in df_pivot:
        df_pivot['tempo_segundos'] = (df_pivot['ENTREGUE'] - df_pivot['DESPACHADO']).dt.total_seconds()
        df_pivot = df_pivot[df_pivot['tempo_segundos'] > 0]
    
    # --- CORREÇÃO DO ERRO DE ID ---
    # Se o ID já começa com 'E', mantemos. Se for número, formatamos.
    def formatar_id(x):
        val = str(x).strip()
        if val.startswith('E'):
            return val
        try:
            return f"E{int(float(val)):03d}"
        except:
            return val

    df_entregadores['id_str'] = df_entregadores['id'].apply(formatar_id)
    # ------------------------------

    # 4. Cruzamento de Dados (Merge)
    df_final = pd.merge(df_pivot, df_entregadores, left_on='id_entregador', right_on='id_str')

    if df_final.empty:
        print("⚠️ Aviso: Nenhum dado correspondente encontrado entre o Log e o CSV de Entregadores.")
        print("Verifique se os IDs no Log (ex: E001) batem com os IDs no entregadores.csv.")
        return

    # --- GERAÇÃO DOS GRÁFICOS ---
    sns.set_theme(style="whitegrid")

    # Gráfico 1: Eficiência por Tipo de Veículo
    plt.figure(figsize=(10, 6))
    if 'tipo' in df_final.columns:
        sns.boxplot(data=df_final, x='tipo', y='tempo_segundos', palette='coolwarm')
        plt.title('Comparativo de Lead Time: Motos vs Carros', fontsize=14)
        plt.xlabel('Tipo de Veículo')
        plt.ylabel('Tempo da Entrega (Segundos)')
        plt.savefig(os.path.join(pasta_resultados, '01_tempo_por_veiculo.png'))

    # Gráfico 2: Ranking de Produtividade
    plt.figure(figsize=(10, 6))
    df_final['id_entregador'].value_counts().plot(kind='bar', color='#4A90E2')
    plt.title('Ranking de Produtividade: Entregas por ID', fontsize=14)
    plt.ylabel('Qtd de Pedidos Entregues')
    plt.savefig(os.path.join(pasta_resultados, '02_ranking_produtividade.png'))

    # Gráfico 3: Performance por Loja
    plt.figure(figsize=(10, 6))
    loja_perf = df_final.groupby('id_loja')['tempo_segundos'].mean().sort_values()
    loja_perf.plot(kind='barh', color='#F5A623')
    plt.title('Gargalos: Tempo Médio de Entrega por Loja', fontsize=14)
    plt.xlabel('Segundos Médios')
    plt.savefig(os.path.join(pasta_resultados, '03_performance_lojas.png'))

    print(f"\n✅ Análise Finalizada com Sucesso!")
    print(f"📁 Pasta de saída: {pasta_resultados}")

if __name__ == "__main__":
    gerar_relatorio_final()