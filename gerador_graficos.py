import pandas as pd
import matplotlib.pyplot as plt
import os

# 1. Configuração de pastas
output_dir = "relatorio_performance"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# 2. Carregamento dos dados
# O arquivo não possui cabeçalho explícito baseado no snippet, 
# então definimos os nomes das colunas.
colunas = ['horario', 'id_entrega', 'local', 'status', 'tempo_min', 'valor', 'condicao']
df = pd.read_csv('log_entregas.csv', names=colunas, header=None)

# 3. Processamento
# Definimos o que é considerado "Nenhum" intemperismo
df['categoria_clima'] = df['condicao'].apply(
    lambda x: 'Sem Intempéries' if str(x).strip() == 'Nenhum' else 'Com Intempéries'
)

# 4. Cálculo das Médias
stats = df.groupby('categoria_clima')['tempo_min'].mean()
print("Média de tempo por condição:\n", stats)

# 5. Geração do Gráfico
plt.figure(figsize=(10, 6))
colors = ['#e74c3c', '#2ecc71'] # Vermelho para intempéries, Verde para normal
stats.plot(kind='bar', color=colors, edgecolor='black')

plt.title('Impacto de Intempéries no Tempo Médio de Entrega', fontsize=14)
plt.xlabel('Condição Climática/Trânsito', fontsize=12)
plt.ylabel('Tempo Médio (minutos)', fontsize=12)
plt.xticks(rotation=0)
plt.grid(axis='y', linestyle='--', alpha=0.7)

# Adicionando os valores nas barras
for i, v in enumerate(stats):
    plt.text(i, v + 0.5, f"{v:.2f} min", ha='center', fontweight='bold')

# 6. Salvando o arquivo
file_path = os.path.join(output_dir, "analise_tempo_intemperies.png")
plt.savefig(file_path, bbox_inches='tight')
plt.close()

print(f"\nSucesso! O gráfico foi salvo em: {file_path}")