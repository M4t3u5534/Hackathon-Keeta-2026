import osmnx as ox
import os

# Configurações das Regiões (Lat, Lon)
regioes = {
    "pinheiros": (-23.5667, -46.6939), # Largo da Batata
    "itaim": (-23.5899, -46.6815),     # Cruzamento Faria Lima x JK
}

def gerar_mapas_adicionais():
    print("🚀 Iniciando download das novas regiões...")
    
    for nome, coords in regioes.items():
        filename = f"mapa_{nome}.graphml"
        print(f"📍 Baixando {nome.capitalize()} (raio de 500m)...")
        
        try:
            # Baixa a malha viária focada
            G = ox.graph_from_point(coords, dist=500, network_type='drive')
            
            # Garante que salva no diretório do script
            diretorio_atual = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(diretorio_atual, filename)
            
            ox.save_graphml(G, filepath=path)
            print(f"✅ Arquivo '{filename}' gerado com {len(G.nodes)} nós.")
            
        except Exception as e:
            print(f"❌ Erro em {nome}: {e}")

if __name__ == "__main__":
    gerar_mapas_adicionais()