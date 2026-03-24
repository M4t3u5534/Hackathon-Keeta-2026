import pygame
import networkx as nx
import osmnx as ox
import os
import random
import math
import threading
import csv
import time

# --- CONFIGURAÇÕES ESTÉTICAS ---
WIDTH, HEIGHT = 1100, 750
BG_COLOR = (242, 238, 230)      
UI_PANEL = (230, 225, 215)      
TEXT_COLOR = (60, 60, 60)
LINE_EMPTY = (210, 210, 210)    
ROUTE_COLORS = [(255, 51, 102), (0, 194, 209), (255, 204, 0), (0, 153, 102), (155, 89, 182)]

# Cores de Eventos
COLOR_RAIN = (100, 149, 237) # CornflowerBlue
COLOR_ACCIDENT = (255, 69, 0) # Red-Orange

# --- PROTEÇÃO DE LOG ---
log_lock = threading.Lock()
LOG_FILE = "log_entregas.csv"

def registrar_evento(id_e, id_r, status, clima="Limpo"):
    def _write():
        with log_lock:
            existe = os.path.exists(LOG_FILE)
            with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not existe:
                    writer.writerow(["Timestamp", "Entregador_ID", "Loja_ID", "Status", "Clima"])
                writer.writerow([time.strftime("%H:%M:%S"), id_e, id_r, status, clima])
    threading.Thread(target=_write, daemon=True).start()

# --- CLASSES DE EVENTOS ---

class GerenciadorEventos:
    def __init__(self, G):
        self.G = G
        self.chuva_ativa = False
        self.chuva_timer = 0
        self.acidentes = {} # {(u, v): tempo_restante}
        self.niveis_transito = {} # {(u, v): fator_multiplicador}
        
    def atualizar(self):
        # 1. Gerenciar Chuva
        if self.chuva_ativa:
            self.chuva_timer -= 1
            if self.chuva_timer <= 0:
                self.chuva_ativa = False
        else:
            if random.random() < 0.002: # 0.2% de chance por frame de começar a chover
                self.chuva_ativa = True
                self.chuva_timer = random.randint(300, 1000)

        # 2. Gerenciar Acidentes
        # Limpar acidentes antigos
        self.acidentes = {edge: t - 1 for edge, t in self.acidentes.items() if t > 0}
        # Chance de novo acidente
        if random.random() < 0.005:
            edges = list(self.G.edges())
            if edges:
                e = random.choice(edges)
                self.acidentes[(e[0], e[1])] = random.randint(200, 600)

        # 3. Gerenciar Trânsito (Atualização dinâmica de pesos)
        # Níveis: 1.0 (Livre), 0.6 (Moderado), 0.3 (Pesado)
        for u, v, k, data in self.G.edges(data=True, keys=True):
            # Mudança aleatória de tráfego
            if random.random() < 0.01 or (u, v) not in self.niveis_transito:
                fator = random.choices([1.0, 0.6, 0.3], weights=[70, 20, 10])[0]
                self.niveis_transito[(u, v)] = fator
            
            # Cálculo de penalidade total
            penalidade_chuva = 0.8 if self.chuva_ativa else 1.0
            penalidade_acidente = 0.1 if (u, v) in self.acidentes else 1.0
            fator_transito = self.niveis_transito[(u, v)]
            
            # Peso dinâmico = comprimento / (velocidade_ajustada)
            # Simplificado: comprimento * (1 / fatores)
            multiplicador_atraso = 1.0 / (penalidade_chuva * penalidade_acidente * fator_transito)
            data['peso_dinamico'] = data['length'] * multiplicador_atraso
            data['fator_velocidade'] = (penalidade_chuva * penalidade_acidente * fator_transito)

# --- CLASSES CORE ---

class Entregador:
    def __init__(self, data, start_node, pos_map):
        self.id = data.get('id', '999')
        self.tipo = data.get('tipo', 'moto')
        self.base_vel = max(0.8, float(data.get('velocidade', 2.5))) 
        self.vel = self.base_vel
        self.cap_max = int(data.get('capacidade', 1))
        self.carga_atual = 0
        
        self.node = start_node
        self.x, self.y = pos_map[start_node]
        self.color = random.choice(ROUTE_COLORS)
        
        self.state = "IDLE" 
        self.target_node = None
        self.path = []
        self.current_job = None

    def update(self, G, pos_map, eventos):
        if self.target_node is None:
            if self.path:
                self.target_node = self.path.pop(0)
            else:
                if self.state == "IDLE":
                    vizinhos = list(G.neighbors(self.node))
                    if vizinhos: self.target_node = random.choice(vizinhos)
                else:
                    self.handle_arrival(eventos)

        if self.target_node is not None:
            # Ajustar velocidade baseada na via atual
            edge_data = G.get_edge_data(self.node, self.target_node)
            fator = 1.0
            if edge_data:
                # Pega o primeiro valor se for multigraph
                data = list(edge_data.values())[0] if isinstance(edge_data, dict) and 0 in edge_data else edge_data
                fator = data.get('fator_velocidade', 1.0)
            
            self.vel = self.base_vel * fator

            tx, ty = pos_map[self.target_node]
            dx, dy = tx - self.x, ty - self.y
            dist = math.hypot(dx, dy)
            
            if dist <= self.vel:
                self.x, self.y = tx, ty
                self.node = self.target_node
                self.target_node = None 
            else:
                self.x += (dx/dist) * self.vel
                self.y += (dy/dist) * self.vel

    def handle_arrival(self, eventos):
        clima_str = "Chuva" if eventos.chuva_ativa else "Limpo"
        if self.state == "TO_SHOP":
            self.state = "TO_DEST"
            registrar_evento(self.id, self.current_job['loja_id'], "COLETADO", clima_str)
        elif self.state == "TO_DEST":
            self.carga_atual -= 1
            if self.carga_atual <= 0:
                registrar_evento(self.id, self.current_job['loja_id'], "ENTREGUE", clima_str)
                self.state = "IDLE"
                self.current_job = None
                self.path = []

    def draw(self, surf, pos_map):
        if self.state != "IDLE":
            pts = [(self.x, self.y)]
            if self.target_node is not None: pts.append(pos_map[self.target_node])
            for n in self.path: pts.append(pos_map[n])
            if len(pts) > 1:
                pygame.draw.lines(surf, self.color, False, pts, 4)
        
        pos = (int(self.x), int(self.y))
        if self.tipo == "carro":
            pygame.draw.rect(surf, self.color, (pos[0]-8, pos[1]-8, 16, 16))
            pygame.draw.rect(surf, (255,255,255), (pos[0]-8, pos[1]-8, 16, 16), 1)
        else:
            pygame.draw.circle(surf, self.color, pos, 6)
            pygame.draw.circle(surf, (255,255,255), pos, 6, 1)

class Botao:
    def __init__(self, x, y, w, h, text, color=(220,220,220)):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.color = color
    def draw(self, surf, font):
        pygame.draw.rect(surf, self.color, self.rect, border_radius=8)
        pygame.draw.rect(surf, (150,150,150), self.rect, 2, border_radius=8)
        txt = font.render(self.text, True, TEXT_COLOR)
        surf.blit(txt, (self.rect.centerx - txt.get_width()//2, self.rect.centery - txt.get_height()//2))

class Simulador:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Hackathon 2026: Logística de Precisão")
        self.font = pygame.font.SysFont("segoeui", 16, bold=True)
        self.shop_font = pygame.font.SysFont("arial", 10, bold=True)
        self.title_font = pygame.font.SysFont("segoeui", 28, bold=True)
        self.clock = pygame.time.Clock()
        self.running = True
        self.state = "MENU"
        
        self.db_entregadores = self.carregar_csv("entregadores.csv")
        self.db_lojas_raw = self.carregar_csv("lojas.csv")
        self.lojas_no_mapa = []
        self.ativos = []
        self.pedidos_pendentes = 0
        self.qtd_lojas_visiveis = 3
        self.eventos = None

    def carregar_csv(self, path):
        if not os.path.exists(path): return []
        with open(path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def setup_map(self, filename):
        try:
            G_raw = ox.load_graphml(filename)
            self.G = G_raw.to_undirected()
            self.nodes = list(self.G.nodes)
            nodes_data = dict(self.G.nodes(data=True))
            xs = [d['x'] for d in nodes_data.values()]
            ys = [d['y'] for d in nodes_data.values()]
            self.min_x, self.max_x = min(xs), max(xs)
            self.min_y, self.max_y = min(ys), max(ys)
            self.pos_map = {n: self.to_px(nodes_data[n]['x'], nodes_data[n]['y']) for n in self.nodes}
            
            # Inicializa Eventos para este mapa
            self.eventos = GerenciadorEventos(self.G)
            
            self.lojas_no_mapa = []
            for loja in self.db_lojas_raw:
                random.seed(loja['id']) 
                node_idx = random.randint(0, len(self.nodes)-1)
                loja_proc = loja.copy()
                loja_proc['node_id'] = self.nodes[node_idx]
                self.lojas_no_mapa.append(loja_proc)
            
            self.ativos = []
            self.state = "SIM"
        except Exception as e: print(f"Erro ao carregar mapa: {e}")

    def to_px(self, lon, lat):
        pad = 80
        x = pad + (lon - self.min_x) / (self.max_x - self.min_x) * (WIDTH - 2*pad)
        y = pad + (self.max_y - lat) / (self.max_y - self.min_y) * (HEIGHT - 2*pad)
        return x, y

    def despachar(self):
        disponiveis = [e for e in self.ativos if e.state == "IDLE" or (e.tipo == "carro" and e.carga_atual < e.cap_max)]
        lojas_ativas = self.lojas_no_mapa[:self.qtd_lojas_visiveis]
        
        if disponiveis and self.pedidos_pendentes > 0 and lojas_ativas:
            e = random.choice(disponiveis)
            loja = random.choice(lojas_ativas)
            destino = random.choice(self.nodes)
            try:
                l_node = loja['node_id']
                # AGORA USA O PESO DINÂMICO QUE CONSIDERA TRÂNSITO E ACIDENTES
                p1 = nx.shortest_path(self.G, e.node, l_node, weight='peso_dinamico')
                p2 = nx.shortest_path(self.G, l_node, destino, weight='peso_dinamico')
                full_path = p1[1:] + p2[1:]
                
                if full_path:
                    e.path = full_path
                    e.current_job = {"loja_id": loja['id']}
                    e.state = "TO_SHOP"
                    e.carga_atual += 1
                    self.pedidos_pendentes -= 1
                    clima_str = "Chuva" if self.eventos.chuva_ativa else "Limpo"
                    registrar_evento(e.id, loja['id'], "DESPACHADO", clima_str)
            except: pass

    def run(self):
        btn_mack = Botao(WIDTH//2-150, 250, 300, 50, "MACKENZIE / HIGIENÓPOLIS")
        btn_itaim = Botao(WIDTH//2-150, 320, 300, 50, "ITAIM BIBI")
        btn_pinheiros = Botao(WIDTH//2-150, 390, 300, 50, "PINHEIROS")
        
        btn_voltar = Botao(20, 15, 100, 45, "VOLTAR", (200, 200, 200)) 
        btn_e_minus = Botao(140, 15, 45, 45, "-", (255, 200, 200))
        btn_e_plus = Botao(195, 15, 45, 45, "+", (200, 255, 200))
        btn_l_minus = Botao(WIDTH//2 - 90, 15, 45, 45, "-", (255, 200, 200))
        btn_l_plus = Botao(WIDTH//2 - 35, 15, 45, 45, "+", (200, 255, 200))
        btn_p_minus = Botao(WIDTH-130, 15, 45, 45, "-", (255, 200, 200))
        btn_p_plus = Botao(WIDTH-75, 15, 45, 45, "+", (200, 255, 200))

        while self.running:
            self.screen.fill(BG_COLOR)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT: self.running = False
                if ev.type == pygame.MOUSEBUTTONDOWN:
                    if self.state == "MENU":
                        if btn_mack.rect.collidepoint(ev.pos): self.setup_map("mapa_mackenzie.graphml")
                        if btn_itaim.rect.collidepoint(ev.pos): self.setup_map("mapa_itaim.graphml")
                        if btn_pinheiros.rect.collidepoint(ev.pos): self.setup_map("mapa_pinheiros.graphml")
                    elif self.state == "SIM":
                        if btn_voltar.rect.collidepoint(ev.pos):
                            self.state = "MENU"
                            self.ativos = [] 
                        
                        if btn_e_plus.rect.collidepoint(ev.pos) and len(self.ativos) < len(self.db_entregadores):
                            d = self.db_entregadores[len(self.ativos)]
                            self.ativos.append(Entregador(d, random.choice(self.nodes), self.pos_map))
                        if btn_e_minus.rect.collidepoint(ev.pos) and self.ativos: self.ativos.pop()
                        if btn_l_plus.rect.collidepoint(ev.pos) and self.qtd_lojas_visiveis < len(self.lojas_no_mapa):
                            self.qtd_lojas_visiveis += 1
                        if btn_l_minus.rect.collidepoint(ev.pos) and self.qtd_lojas_visiveis > 1:
                            self.qtd_lojas_visiveis -= 1
                        if btn_p_plus.rect.collidepoint(ev.pos): self.pedidos_pendentes += 1
                        if btn_p_minus.rect.collidepoint(ev.pos) and self.pedidos_pendentes > 0:
                            self.pedidos_pendentes -= 1

            if self.state == "MENU":
                txt = self.title_font.render("SIMULADOR LOGÍSTICA URBANA", True, TEXT_COLOR)
                self.screen.blit(txt, (WIDTH//2 - txt.get_width()//2, 150))
                btn_mack.draw(self.screen, self.font); btn_itaim.draw(self.screen, self.font); btn_pinheiros.draw(self.screen, self.font)
            
            elif self.state == "SIM":
                # Atualizar Eventos
                self.eventos.atualizar()

                # Desenhar Arestas (Vias) com cores dinâmicas para trânsito/acidente
                for u, v, k, data in self.G.edges(data=True, keys=True):
                    color = LINE_EMPTY
                    width = 1
                    if (u, v) in self.eventos.acidentes:
                        color = COLOR_ACCIDENT
                        width = 3
                    elif data.get('fator_velocidade', 1.0) < 0.5:
                        color = (200, 150, 0) # Alerta Trânsito
                    
                    pygame.draw.line(self.screen, color, self.pos_map[u], self.pos_map[v], width)
                
                # Desenhar Lojas
                for l in self.lojas_no_mapa[:self.qtd_lojas_visiveis]:
                    nid = l['node_id']
                    px, py = self.pos_map[nid]
                    pygame.draw.rect(self.screen, (60, 60, 60), (px-6, py-6, 12, 12))
                    txt_loja = self.shop_font.render(l['nome'].upper(), True, (80, 80, 80))
                    self.screen.blit(txt_loja, (px + 10, py - 5))
                
                self.despachar()
                for e in self.ativos:
                    e.update(self.G, self.pos_map, self.eventos)
                    e.draw(self.screen, self.pos_map)
                
                # Efeito visual de Chuva na tela inteira (opcional, gotas sutis)
                if self.eventos.chuva_ativa:
                    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                    overlay.fill((100, 149, 237, 30)) # Azul transparente
                    self.screen.blit(overlay, (0,0))

                # Interface superior
                pygame.draw.rect(self.screen, UI_PANEL, (0, 0, WIDTH, 85))
                btn_voltar.draw(self.screen, self.font)
                btn_e_minus.draw(self.screen, self.font); btn_e_plus.draw(self.screen, self.font)
                btn_l_minus.draw(self.screen, self.font); btn_l_plus.draw(self.screen, self.font)
                btn_p_minus.draw(self.screen, self.font); btn_p_plus.draw(self.screen, self.font)
                
                # Info de Texto
                self.screen.blit(self.font.render(f"FROTA: {len(self.ativos)}", True, TEXT_COLOR), (250, 15))
                self.screen.blit(self.font.render(f"LOJAS: {self.qtd_lojas_visiveis}", True, TEXT_COLOR), (WIDTH//2 + 20, 15))
                self.screen.blit(self.font.render(f"PEDIDOS: {self.pedidos_pendentes}", True, TEXT_COLOR), (WIDTH - 310, 15))

                # INFO DE EVENTOS NO PAINEL
                clima_txt = "LIMPO" if not self.eventos.chuva_ativa else "CHUVA (Vel -20%)"
                clima_col = TEXT_COLOR if not self.eventos.chuva_ativa else COLOR_RAIN
                self.screen.blit(self.font.render(f"CLIMA: {clima_txt}", True, clima_col), (250, 45))
                
                acidentes_count = len(self.eventos.acidentes)
                acid_txt = f"ACIDENTES: {acidentes_count}" if acidentes_count > 0 else "VIAS LIBERADAS"
                acid_col = COLOR_ACCIDENT if acidentes_count > 0 else (0, 150, 0)
                self.screen.blit(self.font.render(acid_txt, True, acid_col), (WIDTH//2 + 20, 45))

            pygame.display.flip()
            self.clock.tick(60)
        pygame.quit()

if __name__ == "__main__":
    Simulador().run()