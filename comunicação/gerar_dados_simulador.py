import csv
import os
import random
import osmnx as ox


def configurar_diretorio():
    caminho_script = os.path.dirname(os.path.abspath(__file__))
    os.chdir(caminho_script)
    return caminho_script


def gerar_entregadores():
    """
    Gera entregadores com velocidade máxima do veículo em km/h.

    Referência de velocidade urbana em SP para entregas:
      - Moto  : 30–50 km/h (mais ágil, pode circular em faixas estreitas)
      - Carro : 20–40 km/h (limitado pelo trânsito e por não ter a mobilidade da moto)

    O simulador usará min(vel_veículo, vel_via_OSM) para cada segmento,
    respeitando o limite real de cada rua.
    """
    fieldnames = ['id', 'tipo', 'velocidade', 'capacidade']
    entregadores = []

    for i in range(1, 31):
        tipo = random.choice(['moto', 'moto', 'moto', 'carro'])

        if tipo == 'moto':
            # Motos: mais rápidas, capacidade unitária
            vel = round(random.uniform(30.0, 50.0), 1)
            cap = 1
        else:
            # Carros: mais lentos no trânsito urbano, maior capacidade
            vel = round(random.uniform(20.0, 40.0), 1)
            cap = random.choice([3, 4, 5])

        entregadores.append({
            'id':         f'E{i:03d}',
            'tipo':       tipo,
            'velocidade': vel,   # km/h — velocidade máxima do veículo
            'capacidade': cap,
        })

    with open('entregadores.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(entregadores)

    print("✅ entregadores.csv gerado com 30 entregadores (velocidade em km/h).")


def gerar_lojas():
    fieldnames = ['id', 'nome', 'node_id']
    nomes_lojas = [
        'McDonalds Higienopolis', 'Subway Maria Antonia', 'Restaurante Mackenzie',
        'Starbucks Consolação',  'Pizzaria Veridiana',    'Padaria Baronesa',
        'Burger King Angélica',  'Outback Pátio Higienópolis', 'Bacio di Latte',
        'Z Deli Sandwiches',     'Benjamin A Padaria',    'Temakeria Makis Place',
    ]

    nos_escolhidos = []
    for mapa in ["mapa_mackenzie.graphml", "mapa_itaim.graphml", "mapa_pinheiros.graphml"]:
        if os.path.exists(mapa):
            try:
                G = ox.load_graphml(mapa)
                todos_nos  = list(G.nodes)
                nos_escolhidos = random.sample(todos_nos, len(nomes_lojas))
                print(f"📍 Usando {len(nos_escolhidos)} nós reais distintos de {mapa}")
                break
            except Exception as e:
                print(f"Erro ao ler mapa {mapa}: {e}")

    if not nos_escolhidos:
        print("⚠️ Nenhum mapa encontrado. Usando IDs genéricos.")
        nos_escolhidos = [random.randint(1_000_000, 9_999_999) for _ in nomes_lojas]

    lojas = [
        {'id': f'L{i+1:02d}', 'nome': nome, 'node_id': nos_escolhidos[i]}
        for i, nome in enumerate(nomes_lojas)
    ]

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
    print("\n🚀 Bases prontas! Velocidade dos entregadores agora em km/h.")
