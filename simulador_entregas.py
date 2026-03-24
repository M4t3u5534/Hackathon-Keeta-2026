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
COLOR_RAIN = (100, 149, 237)
COLOR_ACCIDENT = (255, 69, 0)

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
        self.acidentes = {} 
        self.niveis_transito = {}
        self.modo_manual = False # Inicia em automático
        
    def atualizar(self):
        # O trânsito sempre flutua (é o "ruído" da cidade)
        for u, v, k, data in self.G.edges(data=True, keys=True):
            if random.random() < 0.01 or (u, v) not in self.niveis_transito:
                self.niveis_transito[(u, v)] = random.choices([1.0, 0.6, 0.3], weights=[70, 20, 10])[0]

        # Lógica Automática vs Manual
        if not self.modo_manual:
            # Chuva automática
            if not self.chuva_ativa and random.random() < 0.002:
                self.chuva_ativa = True
            elif self.chuva_ativa and random.random() < 0.005:
                self.chuva_ativa = False
            
            # Acidentes automáticos
            self.acidentes = {edge: t - 1 for edge, t in self.acidentes.items() if t > 0}
            if random.random() < 0.003:
                edges = list(self.G.edges())
                if edges:
                    e = random.choice(edges)
                    self.acidentes[(e[0], e[1])] = random.randint(300, 800)
        
        # Aplica os pesos no grafo
        for u, v, k, data in self.G.edges(data=True, keys=True):
            p_chuva = 0.8 if self.chuva_ativa else 1.0
            p_acid = 0.05 if (u, v) in self.acidentes else 1.0
            f_transito = self.niveis_transito.get((u, v), 1.0)
            
            fator_final = p_chuva * p_acid * f_transito
            data['fator_velocidade'] = fator_final
            data['peso_dinamico'] = data['length'] / max(0.01, fator_final)

    def trigger_acidente(self):
        edges = list(self.G.edges())
        if edges:
            e = random.choice(edges)
            self.acidentes[(e[0], e[1])] = 1000 # Longa duração no manual

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
                else: self.handle_arrival(eventos)

        if self.target_node is not None:
            edge_data = G.get_edge_data(self.node, self.target_node)
            fator = 1.0
            if edge_data:
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
            if len(pts) > 1: pygame.draw.lines(surf, self.color, False, pts, 4)
        
        pos = (int(self.x), int(self.y))
        pygame.draw.circle(surf, self.color, pos, 6)
        pygame.draw.circle(surf, (255,255,255), pos, 6, 1)

class Botao:
    def __init__(self, x, y, w, h, text, color=(220,220,220), text_size=14):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.color = color
        self.font = pygame.font.SysFont("segoeui", text_size, bold=True)
    def draw(self, surf):
        pygame.draw.rect(surf, self.color, self.rect, border_radius=5)
        pygame.draw.rect(surf, (150,150,150), self.rect, 1, border_radius=5)
        txt = self.font.render(self.text, True, TEXT_COLOR)
        surf.blit(txt, (self.rect.centerx - txt.get_width()//2, self.rect.centery - txt.get_height()//2))

class Simulador:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Hackathon 2026: Logística de Precisão")
        self.font = pygame.font.SysFont("segoeui", 14, bold=True)
        self.title_font = pygame.font.SysFont("segoeui", 28, bold=True)
        self.clock = pygame.time.Clock()
        self.running = True
        self.state = "MENU"
        self.sim_speed = 60 # FPS Original
        
        self.db_entregadores = self.carregar_csv("entregadores.csv")
        self.db_lojas_raw = self.carregar_csv("lojas.csv")
        self.ativos = []
        self.pedidos_pendentes = 0
        self.qtd_lojas_visiveis = 3
        self.eventos = None

    def carregar_csv(self, path):
        if not os.path.exists(path): return []
        with open(path, "r", encoding="utf-8") as f: return list(csv.DictReader(f))

    def setup_map(self, filename):
        G_raw = ox.load_graphml(filename)
        self.G = G_raw.to_undirected()
        self.nodes = list(self.G.nodes)
        nodes_data = dict(self.G.nodes(data=True))
        xs = [d['x'] for d in nodes_data.values()]
        ys = [d['y'] for d in nodes_data.values()]
        self.min_x, self.max_x, self.min_y, self.max_y = min(xs), max(xs), min(ys), max(ys)
        self.pos_map = {n: self.to_px(nodes_data[n]['x'], nodes_data[n]['y']) for n in self.nodes}
        self.eventos = GerenciadorEventos(self.G)
        self.lojas_no_mapa = []
        for l in self.db_lojas_raw:
            random.seed(l['id']); node_idx = random.randint(0, len(self.nodes)-1)
            lp = l.copy(); lp['node_id'] = self.nodes[node_idx]
            self.lojas_no_mapa.append(lp)
        self.state = "SIM"

    def to_px(self, lon, lat):
        pad = 80
        x = pad + (lon - self.min_x) / (self.max_x - self.min_x) * (WIDTH - 2*pad)
        y = pad + (self.max_y - lat) / (self.max_y - self.min_y) * (HEIGHT - 2*pad)
        return x, y

    def despachar(self):
        disp = [e for e in self.ativos if e.state == "IDLE"]
        lojas = self.lojas_no_mapa[:self.qtd_lojas_visiveis]
        if disp and self.pedidos_pendentes > 0 and lojas:
            e = random.choice(disp); loja = random.choice(lojas); destino = random.choice(self.nodes)
            try:
                p1 = nx.shortest_path(self.G, e.node, loja['node_id'], weight='peso_dinamico')
                p2 = nx.shortest_path(self.G, loja['node_id'], destino, weight='peso_dinamico')
                e.path = p1[1:] + p2[1:]; e.current_job = {"loja_id": loja['id']}
                e.state = "TO_SHOP"; e.carga_atual += 1; self.pedidos_pendentes -= 1
                registrar_evento(e.id, loja['id'], "DESPACHADO", "Chuva" if self.eventos.chuva_ativa else "Limpo")
            except: pass

    def run(self):
        # Botões de Controle
        btn_voltar = Botao(15, 10, 80, 35, "VOLTAR")
        btn_modo = Botao(105, 10, 100, 35, "MODO: AUTO", (200, 255, 200))
        btn_chuva = Botao(215, 10, 100, 35, "CHUVA: OFF")
        btn_acid_plus = Botao(325, 10, 100, 35, "+ ACIDENTE", (255, 200, 200))
        btn_acid_clear = Botao(435, 10, 100, 35, "LIMPAR", (220, 220, 220))
        
        btn_vel_minus = Botao(WIDTH-120, 10, 45, 35, "<<")
        btn_vel_plus = Botao(WIDTH-60, 10, 45, 35, ">>")

        while self.running:
            self.screen.fill(BG_COLOR)
            m_pos = pygame.mouse.get_pos()
            
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT: self.running = False
                if ev.type == pygame.MOUSEBUTTONDOWN:
                    if self.state == "MENU":
                        if pygame.Rect(WIDTH//2-150, 320, 300, 50).collidepoint(m_pos): self.setup_map("mapa_itaim.graphml")
                    elif self.state == "SIM":
                        if btn_voltar.rect.collidepoint(m_pos): self.state = "MENU"; self.ativos = []
                        
                        # Alternar Modo
                        if btn_modo.rect.collidepoint(m_pos):
                            self.eventos.modo_manual = not self.eventos.modo_manual
                            btn_modo.text = "MODO: MANUAL" if self.eventos.modo_manual else "MODO: AUTO"
                            btn_modo.color = (255, 230, 150) if self.eventos.modo_manual else (200, 255, 200)
                        
                        # Controles Manuais
                        if self.eventos.modo_manual:
                            if btn_chuva.rect.collidepoint(m_pos):
                                self.eventos.chuva_ativa = not self.eventos.chuva_ativa
                                btn_chuva.text = "CHUVA: ON" if self.eventos.chuva_ativa else "CHUVA: OFF"
                            if btn_acid_plus.rect.collidepoint(m_pos): self.eventos.trigger_acidente()
                            if btn_acid_clear.rect.collidepoint(m_pos): self.eventos.acidentes = {}

                        # Velocidade
                        if btn_vel_plus.rect.collidepoint(m_pos): self.sim_speed = min(240, self.sim_speed + 30)
                        if btn_vel_minus.rect.collidepoint(m_pos): self.sim_speed = max(30, self.sim_speed - 30)
                        
                        # Frota e Pedidos (Simulado por cliques rápidos no teclado para facilitar)
                        if m_pos[1] > 100: # Se clicar no mapa, gera pedido
                            self.pedidos_pendentes += 1
                            if len(self.ativos) < 10:
                                d = self.db_entregadores[len(self.ativos) % len(self.db_entregadores)]
                                self.ativos.append(Entregador(d, random.choice(self.nodes), self.pos_map))

            if self.state == "MENU":
                txt = self.title_font.render("LOGÍSTICA URBANA 2026", True, TEXT_COLOR)
                self.screen.blit(txt, (WIDTH//2 - txt.get_width()//2, 200))
                Botao(WIDTH//2-150, 320, 300, 50, "INICIAR SIMULAÇÃO (ITAIM)").draw(self.screen)
            
            elif self.state == "SIM":
                self.eventos.atualizar()
                
                # Desenho do Mapa
                for u, v, k, data in self.G.edges(data=True, keys=True):
                    color = COLOR_ACCIDENT if (u, v) in self.eventos.acidentes else LINE_EMPTY
                    width = 3 if (u, v) in self.eventos.acidentes else 1
                    pygame.draw.line(self.screen, color, self.pos_map[u], self.pos_map[v], width)
                
                self.despachar()
                for e in self.ativos:
                    e.update(self.G, self.pos_map, self.eventos)
                    e.draw(self.screen, self.pos_map)
                
                if self.eventos.chuva_ativa:
                    s = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); s.fill((100, 149, 237, 40))
                    self.screen.blit(s, (0,0))

                # Painel UI
                pygame.draw.rect(self.screen, UI_PANEL, (0, 0, WIDTH, 60))
                btn_voltar.draw(self.screen); btn_modo.draw(self.screen)
                btn_vel_minus.draw(self.screen); btn_vel_plus.draw(self.screen)
                
                if self.eventos.modo_manual:
                    btn_chuva.draw(self.screen); btn_acid_plus.draw(self.screen); btn_acid_clear.draw(self.screen)

                # Info Status
                status_txt = f"Frota: {len(self.ativos)} | Pedidos: {self.pedidos_pendentes} | Speed: {self.sim_speed} FPS"
                self.screen.blit(self.font.render(status_txt, True, TEXT_COLOR), (15, 65))
                if self.eventos.acidentes:
                    self.screen.blit(self.font.render(f"AVISO: {len(self.eventos.acidentes)} VIAS BLOQUEADAS", True, COLOR_ACCIDENT), (WIDTH-250, 65))

            pygame.display.flip()
            self.clock.tick(self.sim_speed)
        pygame.quit()

if __name__ == "__main__":
    Simulador().run()