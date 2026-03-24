import csv
import os
import random
import osmnx as ox

def configurar_diretorio():
    caminho_script = os.path.dirname(os.path.abspath(__file__))
    os.chdir(caminho_script)
    return caminho_script

def gerar_entregadores():
    fieldnames = ['id', 'tipo', 'velocidade', 'capacidade']
    entregadores = []
    
    # Gera 30 entregadores (proporção maior de motos do que carros)
    for i in range(1, 31):
        tipo = random.choice(['moto', 'moto', 'moto', 'carro']) 
        vel = round(random.uniform(4.0, 5.0), 1) if tipo == 'moto' else round(random.uniform(2.0, 3.0), 1)
        cap = 1 if tipo == 'moto' else random.choice([3, 4, 5])
        
        entregadores.append({
            'id': f'E{i:03d}', 
            'tipo': tipo, 
            'velocidade': vel, 
            'capacidade': cap
        })
        
    with open('entregadores.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(entregadores)
    print("✅ entregadores.csv gerado com 30 entregadores.")

def gerar_lojas():
    fieldnames = ['id', 'nome', 'node_id']
    
    nomes_lojas = [
        'McDonalds Higienopolis', 'Subway Maria Antonia', 'Restaurante Mackenzie',
        'Starbucks Consolação', 'Pizzaria Veridiana', 'Padaria Baronesa',
        'Burger King Angélica', 'Outback Pátio Higienópolis', 'Bacio di Latte',
        'Z Deli Sandwiches', 'Benjamin A Padaria', 'Temakeria Makis Place'
    ]
    
    nos_escolhidos = []
    # Tenta achar um mapa para pegar nós REAIS e DIFERENTES para cada loja
    for mapa in ["mapa_mackenzie.graphml", "mapa_itaim.graphml", "mapa_pinheiros.graphml"]:
        if os.path.exists(mapa):
            try:
                G = ox.load_graphml(mapa)
                todos_nos = list(G.nodes)
                # Garante que vai pegar pontos (nós) únicos para as 12 lojas
                nos_escolhidos = random.sample(todos_nos, len(nomes_lojas))
                print(f"📍 Usando {len(nos_escolhidos)} nós reais distintos do {mapa}")
                break
            except Exception as e:
                print(f"Erro ao ler mapa {mapa}: {e}")
                continue
    
    if not nos_escolhidos:
        print("⚠️ Nenhum mapa encontrado. Usando IDs de teste genéricos.")
        nos_escolhidos = [random.randint(1000000, 9999999) for _ in nomes_lojas]

    lojas = []
    for i, nome in enumerate(nomes_lojas):
        lojas.append({'id': f'L{i+1:02d}', 'nome': nome, 'node_id': nos_escolhidos[i]})

    with open('lojas.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(lojas)
    print(f"✅ lojas.csv gerado com {len(lojas)} lojas espalhadas pelo mapa.")

if __name__ == "__main__":
    pasta = configurar_diretorio()
    print(f"📂 Criando bases em: {pasta}")
    gerar_entregadores()
    gerar_lojas()
    print("\n🚀 Bases prontas para o Hackathon!")