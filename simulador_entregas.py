import pygame
import networkx as nx
import random
import math
import threading
import csv
import time
import os

# --- Configurações e Identidade Visual (Mini Metro Style) ---
WIDTH, HEIGHT = 1000, 700
BG_COLOR = (242, 238, 230)      # Fundo off-white clássico
TEXT_COLOR = (50, 50, 50)
LINE_COLOR = (200, 200, 200)    # Ruas vazias
ROUTE_COLORS = [(255, 51, 102), (0, 194, 209), (255, 204, 0), (0, 153, 102)] # Cores vibrantes
NODE_COLOR = (150, 150, 150)

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Simulador de Entregas - Higienópolis")
font = pygame.font.SysFont("segoeui", 20, bold=True)
title_font = pygame.font.SysFont("segoeui", 28, bold=True)

# --- Lock para Thread-Safety no Log ---
log_lock = threading.Lock()
LOG_FILE = "log_entregas.csv"

# Inicializa o CSV se não existir
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Timestamp", "ID_Entregador", "ID_Restaurante", "Status"])

def registrar_log(id_entregador, id_restaurante, status):
    """Grava no CSV de forma segura contra concorrência."""
    with log_lock:
        with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), id_entregador, id_restaurante, status])

# --- Estrutura de Dados ---
# Substitua isso pela importação real do OSMnx para Higienópolis:
# import osmnx as ox
# G = ox.graph_from_place('Higienópolis, São Paulo, Brazil', network_type='drive')
# nodes_proj, edges_proj = ox.graph_to_gdfs(G, nodes=True, edges=True)
# Aqui usamos um grid complexo como placeholder funcional
G = nx.grid_2d_graph(15, 10)
nodes = list(G.nodes)
# Mapeamento de coordenadas do grafo para a tela do Pygame
pos = {node: (50 + node[0] * 60, 100 + node[1] * 50) for node in nodes}

class Entregador:
    def __init__(self, e_id, start_node):
        self.id = e_id
        self.node = start_node
        self.x, self.y = pos[start_node]
        self.target_node = None
        self.path = []
        self.assigned = False
        self.color = random.choice(ROUTE_COLORS)
        
        # Simulação de DB de veículos (1: Moto rápida/pouca cap, 2: Carro lento/muita cap)
        self.tipo_veiculo = random.choice(["moto", "carro"])
        self.velocidade = 4 if self.tipo_veiculo == "moto" else 2.5

    def update(self):
        if not self.target_node and not self.assigned:
            # Fica circulando pelas ruas aleatoriamente se não tiver entrega
            vizinhos = list(G.neighbors(self.node))
            self.target_node = random.choice(vizinhos)
        
        if self.target_node:
            tx, ty = pos[self.target_node]
            dx, dy = tx - self.x, ty - self.y
            dist = math.hypot(dx, dy)
            
            if dist < self.velocidade:
                self.node = self.target_node
                self.x, self.y = tx, ty
                if self.path:
                    self.target_node = self.path.pop(0)
                else:
                    self.target_node = None
                    if self.assigned:
                        # Chegou ao destino final da entrega
                        self.assigned = False
            else:
                self.x += (dx / dist) * self.velocidade
                self.y += (dy / dist) * self.velocidade

    def draw(self, surface):
        if self.assigned and self.target_node:
            # Desenha a linha da rota no estilo Mini Metro
            if self.path:
                points = [(self.x, self.y)] + [pos[n] for n in [self.target_node] + self.path]
                if len(points) > 1:
                    pygame.draw.lines(surface, self.color, False, points, 6)
        
        # Desenha o entregador (círculo)
        pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), 10)
        if self.tipo_veiculo == "carro":
            # Diferencia carro com um contorno quadrado
            pygame.draw.rect(surface, TEXT_COLOR, (int(self.x)-12, int(self.y)-12, 24, 24), 2)

class Botao:
    def __init__(self, x, y, text, is_plus=True):
        self.rect = pygame.Rect(x, y, 40, 40)
        self.text = text
        self.is_plus = is_plus

    def draw(self, surface):
        pygame.draw.rect(surface, (220, 220, 220), self.rect, border_radius=8)
        label = title_font.render(self.text, True, TEXT_COLOR)
        surface.blit(label, (self.rect.x + 10, self.rect.y + 2))

    def is_clicked(self, pos):
        return self.rect.collidepoint(pos)

# --- Instâncias da Simulação ---
entregadores = []
entregas_pendentes = 0

btn_ent_menos = Botao(50, 20, "-")
btn_ent_mais = Botao(150, 20, "+")
btn_ped_menos = Botao(WIDTH - 190, 20, "-")
btn_ped_mais = Botao(WIDTH - 90, 20, "+")

def atribuir_entrega():
    """Busca um entregador livre e traça a rota."""
    livres = [e for e in entregadores if not e.assigned]
    if livres:
        e = livres[0]
        e.assigned = True
        
        # Define restaurante (origem) e cliente (destino) aleatórios
        restaurante_node = random.choice(nodes)
        cliente_node = random.choice(nodes)
        
        # Calcula rota mais curta usando NetworkX
        try:
            caminho_ate_restaurante = nx.shortest_path(G, e.node, restaurante_node)
            caminho_ate_cliente = nx.shortest_path(G, restaurante_node, cliente_node)
            
            # Combina os caminhos
            e.path = caminho_ate_restaurante[1:] + caminho_ate_cliente[1:]
            if e.path:
                e.target_node = e.path.pop(0)
            
            # Registra no Log
            registrar_log(e.id, f"REST_{restaurante_node}", "COLETANDO")
            return True
        except nx.NetworkXNoPath:
            e.assigned = False
            return False
    return False

# --- Loop Principal ---
running = True
clock = pygame.time.Clock()
id_counter = 1

while running:
    screen.fill(BG_COLOR)
    
    # Eventos UI
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.MOUSEBUTTONDOWN:
            mouse_pos = event.pos
            if btn_ent_mais.is_clicked(mouse_pos):
                entregadores.append(Entregador(id_counter, random.choice(nodes)))
                id_counter += 1
            elif btn_ent_menos.is_clicked(mouse_pos) and entregadores:
                entregadores.pop()
            
            if btn_ped_mais.is_clicked(mouse_pos):
                entregas_pendentes += 1
            elif btn_ped_menos.is_clicked(mouse_pos) and entregas_pendentes > 0:
                entregas_pendentes -= 1

    # Despacho de entregas
    if entregas_pendentes > 0:
        if atribuir_entrega():
            entregas_pendentes -= 1

    # Desenho das Ruas (Edges)
    for edge in G.edges():
        p1, p2 = pos[edge[0]], pos[edge[1]]
        pygame.draw.line(screen, LINE_COLOR, p1, p2, 3)

    # Desenho dos Nós (Interseções/Restaurantes)
    for node in nodes:
        pygame.draw.circle(screen, NODE_COLOR, pos[node], 4)

    # Atualização e Desenho dos Entregadores
    for e in entregadores:
        e.update()
        e.draw(screen)

    # UI Gráfica
    btn_ent_menos.draw(screen)
    btn_ent_mais.draw(screen)
    screen.blit(font.render(f"Entregadores: {len(entregadores)}", True, TEXT_COLOR), (50, 65))
    
    btn_ped_menos.draw(screen)
    btn_ped_mais.draw(screen)
    screen.blit(font.render(f"Fila Entregas: {entregas_pendentes}", True, TEXT_COLOR), (WIDTH - 190, 65))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()