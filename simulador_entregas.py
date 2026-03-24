import pygame
import networkx as nx
import osmnx as ox
import os
import random
import math
import threading
import csv
import time

# --- CONFIGURAÇÕES ESTÉTICAS (MINI METRO) ---
WIDTH, HEIGHT = 1100, 750
BG_COLOR = (242, 238, 230)      # Off-white clássico
UI_PANEL = (230, 225, 215)      # Painel lateral/superior
TEXT_COLOR = (60, 60, 60)
LINE_EMPTY = (210, 210, 210)    # Ruas inativas
ROUTE_COLORS = [(255, 51, 102), (0, 194, 209), (255, 204, 0), (0, 153, 102), (155, 89, 182)]

# --- PROTEÇÃO DE LOG (THREAD-SAFE) ---
log_lock = threading.Lock()
LOG_FILE = "log_entregas.csv"

def registrar_evento(id_e, id_r, status):
    def _write():
        with log_lock:
            existe = os.path.exists(LOG_FILE)
            with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not existe:
                    writer.writerow(["Timestamp", "Entregador_ID", "Loja_ID", "Status"])
                writer.writerow([time.strftime("%H:%M:%S"), id_e, id_r, status])
    threading.Thread(target=_write, daemon=True).start()

# --- CLASSES DO SISTEMA ---

class Entregador:
    def __init__(self, data, start_node, pos_map):
        self.id = data['id']
        self.tipo = data['tipo']
        self.vel = float(data['velocidade'])
        self.cap = int(data['capacidade'])
        self.node = start_node
        self.x, self.y = pos_map[start_node]
        self.color = random.choice(ROUTE_COLORS)
        
        # Estados: "IDLE", "TO_SHOP", "TO_DEST"
        self.state = "IDLE"
        self.target_node = None
        self.path = []
        self.current_job = None

    def update(self, G, pos_map):
        if self.state == "IDLE":
            if not self.target_node:
                viz = list(G.neighbors(self.node))
                if viz: self.target_node = random.choice(viz)
        
        if self.target_node:
            tx, ty = pos_map[self.target_node]
            dx, dy = tx - self.x, ty - self.y
            dist = math.hypot(dx, dy)
            
            if dist < self.vel:
                self.node = self.target_node
                self.x, self.y = tx, ty
                if self.path:
                    self.target_node = self.path.pop(0)
                else:
                    self.target_node = None
                    self.handle_arrival()
            else:
                self.x += (dx/dist) * self.vel
                self.y += (dy/dist) * self.vel

    def handle_arrival(self):
        if self.state == "TO_SHOP":
            self.state = "TO_DEST"
            # Aqui ele iniciaria o p2 do caminho
        elif self.state == "TO_DEST":
            registrar_evento(self.id, self.current_job['loja_id'], "ENTREGUE")
            self.state = "IDLE"
            self.current_job = None
            self.path = []

    def draw(self, surf, pos_map):
        if self.state != "IDLE" and self.path:
            pts = [(self.x, self.y)] + [pos_map[n] for n in self.path]
            if len(pts) > 1: pygame.draw.lines(surf, self.color, False, pts, 7)
        
        # Mini Metro icons
        pygame.draw.circle(surf, self.color, (int(self.x), int(self.y)), 10)
        if self.tipo == "carro":
            pygame.draw.rect(surf, (40,40,40), (int(self.x)-12, int(self.y)-12, 24, 24), 2)

class Botao:
    def __init__(self, x, y, w, h, text, color=(220,220,220)):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.color = color
    def draw(self, surf, font):
        pygame.draw.rect(surf, self.color, self.rect, border_radius=8)
        txt_surf = font.render(self.text, True, TEXT_COLOR)
        surf.blit(txt_surf, (self.rect.centerx - txt_surf.get_width()//2, self.rect.centery - txt_surf.get_height()//2))

# --- MOTOR PRINCIPAL ---

class Simulador:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.font = pygame.font.SysFont("segoeui", 18, bold=True)
        self.title_font = pygame.font.SysFont("segoeui", 32, bold=True)
        self.clock = pygame.time.Clock()
        self.running = True
        self.state = "MENU"
        self.map_choice = None
        
        # Dados
        self.db_entregadores = self.load_csv("entregadores.csv")
        self.db_lojas = self.load_csv("lojas.csv")
        self.ativos = []
        self.fila_pedidos = 0

    def load_csv(self, path):
        if not os.path.exists(path): return []
        with open(path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def setup_map(self, filename):
        # Garante que o caminho seja relativo ao local do script .py
        diretorio_script = os.path.dirname(os.path.abspath(__file__))
        caminho_completo = os.path.join(diretorio_script, filename)

        if not os.path.exists(caminho_completo):
            print(f"\n⚠️ ERRO: Arquivo não encontrado!")
            print(f"Buscando em: {caminho_completo}")
            print("Certifique-se de rodar o script de download para esta região primeiro.\n")
            return # Sai da função sem carregar nada e sem travar

        print(f"Lendo {filename}...")
        try:
            G_raw = ox.load_graphml(caminho_completo)
            self.G = G_raw.to_undirected()
            self.nodes = list(self.G.nodes)
            nodes_data = dict(self.G.nodes(data=True))
            
            # Normalização de escala
            x_coords = [d['x'] for d in nodes_data.values()]
            y_coords = [d['y'] for d in nodes_data.values()]
            self.min_x, self.max_x = min(x_coords), max(x_coords)
            self.min_y, self.max_y = min(y_coords), max(y_coords)
            
            self.pos_map = {n: self.to_px(nodes_data[n]['x'], nodes_data[n]['y']) for n in self.nodes}
            self.state = "SIM"
            print(f"Sucesso! {filename} carregado.")
        except Exception as e:
            print(f"Erro ao processar o grafo: {e}")

    def to_px(self, lon, lat):
        pad = 100
        x = pad + (lon - self.min_x) / (self.max_x - self.min_x) * (WIDTH - 2*pad)
        y = pad + (self.max_y - lat) / (self.max_y - self.min_y) * (HEIGHT - 2*pad)
        return x, y

    def despachar(self):
        livres = [e for e in self.ativos if e.state == "IDLE"]
        if livres and self.fila_pedidos > 0:
            e = livres[0]
            loja = random.choice(self.db_lojas)
            destino = random.choice(self.nodes)
            try:
                # Logica de rota Mini Metro: Entregador -> Restaurante -> Destino
                p1 = nx.shortest_path(self.G, e.node, int(loja['node_id']), weight='length')
                p2 = nx.shortest_path(self.G, int(loja['node_id']), destino, weight='length')
                
                e.path = p1[1:] + p2[1:]
                e.target_node = e.path.pop(0)
                e.current_job = {"loja_id": loja['id'], "destino": destino}
                e.state = "TO_SHOP"
                self.fila_pedidos -= 1
                registrar_evento(e.id, loja['id'], "EM_ROTA")
            except: pass

    def run(self):
        # Botões de Menu
        btn_mack = Botao(WIDTH//2-100, 250, 200, 50, "MACKENZIE")
        btn_itaim = Botao(WIDTH//2-100, 320, 200, 50, "ITAIM BIBI")
        btn_pinheiros = Botao(WIDTH//2-100, 390, 200, 50, "PINHEIROS")
        
        # Botões UI Simulação
        btn_e_plus = Botao(30, 20, 40, 40, "+", (200,255,200))
        btn_e_minus = Botao(80, 20, 40, 40, "-", (255,200,200))
        btn_p_plus = Botao(WIDTH-130, 20, 40, 40, "+", (200,255,200))
        btn_p_minus = Botao(WIDTH-80, 20, 40, 40, "-", (255,200,200))

        while self.running:
            self.screen.fill(BG_COLOR)
            events = pygame.event.get()
            for ev in events:
                if ev.type == pygame.QUIT: self.running = False
                
                if ev.type == pygame.MOUSEBUTTONDOWN:
                    if self.state == "MENU":
                        if btn_mack.rect.collidepoint(ev.pos): self.setup_map("mapa_mackenzie.graphml")
                        if btn_itaim.rect.collidepoint(ev.pos): self.setup_map("mapa_itaim.graphml")
                        if btn_pinheiros.rect.collidepoint(ev.pos): self.setup_map("mapa_pinheiros.graphml")
                    
                    elif self.state == "SIM":
                        if btn_e_plus.rect.collidepoint(ev.pos) and len(self.ativos) < len(self.db_entregadores):
                            new_data = self.db_entregadores[len(self.ativos)]
                            self.ativos.append(Entregador(new_data, random.choice(self.nodes), self.pos_map))
                        if btn_e_minus.rect.collidepoint(ev.pos) and self.ativos: self.ativos.pop()
                        if btn_p_plus.rect.collidepoint(ev.pos): self.fila_pedidos += 1
                        if btn_p_minus.rect.collidepoint(ev.pos) and self.fila_pedidos > 0: self.fila_pedidos -= 1

            if self.state == "MENU":
                txt = self.title_font.render("SELECIONE A REGIÃO", True, TEXT_COLOR)
                self.screen.blit(txt, (WIDTH//2 - txt.get_width()//2, 150))
                btn_mack.draw(self.screen, self.font)
                btn_itaim.draw(self.screen, self.font)
                btn_pinheiros.draw(self.screen, self.font)

            elif self.state == "SIM":
                # Background UI
                pygame.draw.rect(self.screen, UI_PANEL, (0, 0, WIDTH, 75))
                
                # Malha de ruas
                for u, v in self.G.edges():
                    pygame.draw.line(self.screen, LINE_EMPTY, self.pos_map[u], self.pos_map[v], 2)
                
                # Lojas
                for l in self.db_lojas:
                    nid = int(l['node_id'])
                    if nid in self.pos_map:
                        pygame.draw.rect(self.screen, (70,70,70), (*self.pos_map[nid], 15, 15))

                # Atualizar e Desenhar Entregadores
                self.despachar()
                for e in self.ativos:
                    e.update(self.G, self.pos_map)
                    e.draw(self.screen, self.pos_map)
                
                # UI Texto
                btn_e_plus.draw(self.screen, self.font)
                btn_e_minus.draw(self.screen, self.font)
                btn_p_plus.draw(self.screen, self.font)
                btn_p_minus.draw(self.screen, self.font)
                
                self.screen.blit(self.font.render(f"FROTA: {len(self.ativos)}", True, TEXT_COLOR), (135, 30))
                self.screen.blit(self.font.render(f"PEDIDOS: {self.fila_pedidos}", True, TEXT_COLOR), (WIDTH-250, 30))

            pygame.display.flip()
            self.clock.tick(60)
        pygame.quit()

if __name__ == "__main__":
    Simulador().run()