import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# 1. Carregamento e Limpeza
# Definindo nomes de colunas baseados na estrutura do CSV
cols = [
    'Horario', 'Entregador_ID', 'Veiculo', 'Local_ID', 'Status', 
    'Distancia', 'Taxa_Entrega', 'Valor_Pedido', 'Qtd_Items', 
    'Multiplicador', 'Condicoes', 'Atraso_Segundos'
]

df = pd.read_csv('log_entregas.csv', names=cols, header=None)

# Limpeza de dados financeiros e temporais
df['Taxa_Entrega'] = df['Taxa_Entrega'].str.replace('R$ ', '', regex=False).str.replace(',', '.').astype(float)
df['Atraso_Segundos'] = df['Atraso_Segundos'].str.replace('s', '', regex=False).str.replace('+', '', regex=False).astype(float)
df['Horario_H'] = pd.to_datetime(df['Horario']).dt.hour

# 2. Configuração Visual
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = [12, 6]

# --- Gráfico 1: Performance por Veículo ---
plt.figure()
sns.boxplot(x='Veiculo', y='Atraso_Segundos', data=df, palette='viridis')
plt.title('Distribuição de Atrasos/Adiantamentos por Tipo de Veículo')
plt.ylabel('Segundos (Positivo = Atraso, Negativo = Adiantamento)')
plt.show()

# --- Gráfico 2: Impacto das Condições no Atraso ---
# Simplificando a coluna de condições para pegar a principal (ex: 'Chuva')
df['Condicao_Principal'] = df['Condicoes'].apply(lambda x: str(x).split(',')[0].replace('"', ''))

plt.figure()
sns.barplot(x='Condicao_Principal', y='Atraso_Segundos', data=df, estimator='mean', palette='magma')
plt.title('Média de Atraso por Condição Ambiental/Tráfego')
plt.show()

# --- Gráfico 3: Volume de Entregas por Hora ---
plt.figure()
sns.countplot(x='Horario_H', data=df, color='skyblue')
plt.title('Volume de Entregas por Hora do Dia')
plt.xlabel('Hora (H)')
plt.ylabel('Total de Entregas')
plt.show()

# 3. Resumo Estatístico para insights rápidos
print("Resumo de Eficiência por Veículo (Média de Atraso):")
print(df.groupby('Veiculo')['Atraso_Segundos'].mean())