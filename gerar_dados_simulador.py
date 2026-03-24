import csv
import os
import random
import osmnx as ox

def configurar_diretorio():
    # Detecta a pasta onde este script está salvo
    caminho_script = os.path.dirname(os.path.abspath(__file__))
    os.chdir(caminho_script)
    return caminho_script

def gerar_entregadores():
    fieldnames = ['id', 'tipo', 'velocidade', 'capacidade']
    entregadores = [
        {'id': 1, 'tipo': 'moto', 'velocidade': 4.5, 'capacidade': 1},
        {'id': 2, 'tipo': 'moto', 'velocidade': 4.2, 'capacidade': 1},
        {'id': 3, 'tipo': 'carro', 'velocidade': 2.8, 'capacidade': 3},
        {'id': 4, 'tipo': 'moto', 'velocidade': 4.8, 'capacidade': 1},
        {'id': 5, 'tipo': 'carro', 'velocidade': 2.5, 'capacidade': 5},
    ]
    
    with open('entregadores.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(entregadores)
    print("✅ entregadores.csv gerado.")

def gerar_lojas():
    fieldnames = ['id', 'nome', 'node_id']
    
    # Tenta achar um mapa para pegar um nó real, senão usa um ID genérico
    node_id_base = 0
    for mapa in ["mapa_mackenzie.graphml", "mapa_itaim.graphml", "mapa_pinheiros.graphml"]:
        if os.path.exists(mapa):
            try:
                G = ox.load_graphml(mapa)
                node_id_base = random.choice(list(G.nodes))
                print(f"📍 Usando nós reais do {mapa}")
                break
            except: continue
    
    if node_id_base == 0:
        print("⚠️ Nenhum mapa encontrado. Usando IDs de teste.")
        node_id_base = 12345678 # ID genérico caso não tenha mapa

    lojas = [
        {'id': 'L01', 'nome': 'McDonalds Higienopolis', 'node_id': node_id_base},
        {'id': 'L02', 'nome': 'Subway Maria Antonia', 'node_id': node_id_base},
        {'id': 'L03', 'nome': 'Restaurante Mackenzie', 'node_id': node_id_base},
    ]

    with open('lojas.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(lojas)
    print("✅ lojas.csv gerado.")

if __name__ == "__main__":
    pasta = configurar_diretorio()
    print(f"📂 Criando bases em: {pasta}")
    gerar_entregadores()
    gerar_lojas()
    print("\n🚀 Bases prontas para o Hackathon!")