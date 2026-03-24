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
BG_COLOR     = (242, 238, 230)
UI_PANEL     = (230, 225, 215)
TEXT_COLOR   = (60, 60, 60)
LINE_EMPTY   = (210, 210, 210)
ROUTE_COLORS = [(255, 51, 102), (0, 194, 209), (255, 204, 0), (0, 153, 102), (155, 89, 182)]

DEFAULT_ROAD_SPEED_KPH = 30.0

# --- PROTEÇÃO DE LOG ---
log_lock = threading.Lock()
LOG_FILE  = "log_entregas.csv"

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

# ---------------------------------------------------------------------------
# CLASSE ENTREGADOR (LOGICA DE MOVIMENTAÇÃO CORRIGIDA)
# ---------------------------------------------------------------------------
class Entregador:
    def __init__(self, data, start_node, pos_map):
        self.id       = data.get('id', '999')
        self.tipo     = data.get('tipo', 'moto')
        self.vel_kph  = float(data.get('velocidade', 30.0))
        self.cap_max      = int(data.get('capacidade', 1))
        self.carga_atual  = 0
        self.node         = start_node
        self.x, self.y    = pos_map[start_node]
        self.color        = random.choice(ROUTE_COLORS)
        self.state        = "IDLE"
        self.target_node  = None
        self.path         = []
        self.current_job  = None
        self._current_vel_px = 0.0

    def _vel_px_frame(self, next_node, edge_speed_kph, meters_per_pixel, time_scale, fps=60):
        road_kph   = edge_speed_kph.get((self.node, next_node), DEFAULT_ROAD_SPEED_KPH)
        actual_kph = min(self.vel_kph, road_kph)
        speed_ms   = actual_kph * 1000.0 / 3600.0
        speed_px_s = speed_ms / meters_per_pixel
        return (speed_px_s / fps) * time_scale

    def update(self, G, pos_map, edge_speed_kph, meters_per_pixel, time_scale):
        # 1. Busca novo alvo apenas se não tiver um
        if self.target_node is None:
            if self.path:
                self.target_node = self.path.pop(0)
            else:
                if self.state == "IDLE":
                    vizinhos = list(G.neighbors(self.node))
                    if vizinhos: self.target_node = random.choice(vizinhos)
                else:
                    self.handle_arrival()

        # 2. Movimentação Estrita Nó-a-Nó
        if self.target_node is not None:
            self._current_vel_px = self._vel_px_frame(self.target_node, edge_speed_kph, meters_per_pixel, time_scale)
            tx, ty = pos_map[self.target_node]
            dx, dy = tx - self.x, ty - self.y
            dist   = math.hypot(dx, dy)

            if dist <= self._current_vel_px:
                # CHEGADA EXATA NO NÓ (Evita cortar caminho)
                self.x, self.y = tx, ty
                self.node = self.target_node
                self.target_node = None 
            else:
                self.x += (dx / dist) * self._current_vel_px
                self.y += (dy / dist) * self._current_vel_px

    def handle_arrival(self):
        if self.state == "TO_SHOP":
            self.state = "TO_DEST"
            registrar_evento(self.id, self.current_job['loja_id'], "COLETADO")
        elif self.state == "TO_DEST":
            self.carga_atual -= 1
            if self.carga_atual <= 0:
                registrar_evento(self.id, self.current_job['loja_id'], "ENTREGUE")
                self.state, self.current_job, self.path = "IDLE", None, []

    def draw(self, surf, pos_map):
        # Desenha a rota passando pelo target_node para não cortar curvas
        if self.state != "IDLE":
            pts = [(self.x, self.y)]
            if self.target_node: pts.append(pos_map[self.target_node])
            for n in self.path: pts.append(pos_map[n])
            if len(pts) > 1:
                pygame.draw.lines(surf, self.color, False, pts, 4)

        pos = (int(self.x), int(self.y))
        if self.tipo == "carro":
            pygame.draw.rect(surf, self.color, (pos[0]-8, pos[1]-8, 16, 16))
            pygame.draw.rect(surf, (255, 255, 255), (pos[0]-8, pos[1]-8, 16, 16), 1)
        else:
            pygame.draw.circle(surf, self.color, pos, 6)
            pygame.draw.circle(surf, (255, 255, 255), pos, 6, 1)

# ---------------------------------------------------------------------------
# INTERFACE E SIMULADOR
# ---------------------------------------------------------------------------
class Botao:
    def __init__(self, x, y, w, h, text, color=(220, 220, 220)):
        self.rect  = pygame.Rect(x, y, w, h)
        self.text  = text
        self.color = color
    def draw(self, surf, font):
        pygame.draw.rect(surf, self.color, self.rect, border_radius=8)
        pygame.draw.rect(surf, (150, 150, 150), self.rect, 2, border_radius=8)
        txt = font.render(self.text, True, TEXT_COLOR)
        surf.blit(txt, (self.rect.centerx - txt.get_width()//2, self.rect.centery - txt.get_height()//2))

class Simulador:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.font = pygame.font.SysFont("segoeui", 14, bold=True)
        self.title_font = pygame.font.SysFont("segoeui", 28, bold=True)
        self.clock = pygame.time.Clock()
        self.state = "MENU"
        self.time_scale = 4.0
        self.running = True
        
        self.db_entregadores = self.carregar_csv("entregadores.csv")
        self.db_lojas_raw = self.carregar_csv("lojas.csv")
        self.lojas_no_mapa = []
        self.ativos = []
        self.pedidos_pendentes = 0
        self.qtd_lojas_visiveis = 3
        self.meters_per_pixel = 1.0
        self.edge_speed_kph = {}

    def carregar_csv(self, path):
        if not os.path.exists(path): return []
        with open(path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def setup_map(self, filename):
        try:
            G_raw = ox.load_graphml(filename)
            G_directed = ox.add_edge_speeds(G_raw)
            self.G = G_directed.to_undirected()
            self.nodes = list(self.G.nodes)
            nodes_data = dict(self.G.nodes(data=True))
            xs = [d['x'] for d in nodes_data.values()]; ys = [d['y'] for d in nodes_data.values()]
            self.min_x, self.max_x, self.min_y, self.max_y = min(xs), max(xs), min(ys), max(ys)
            self.pos_map = {n: self.to_px(nodes_data[n]['x'], nodes_data[n]['y']) for n in self.nodes}
            
            # Escala
            lat_center = (self.min_y + self.max_y) / 2.0
            map_width_m = (self.max_x - self.min_x) * (111320.0 * math.cos(math.radians(lat_center)))
            self.meters_per_pixel = map_width_m / (WIDTH - 160)

            self.edge_speed_kph = {}
            for u, v, d in self.G.edges(data=True):
                spd = d.get('speed_kph', DEFAULT_ROAD_SPEED_KPH)
                spd = float(spd[0]) if isinstance(spd, list) else float(spd)
                self.edge_speed_kph[(u, v)] = self.edge_speed_kph[(v, u)] = spd

            self.lojas_no_mapa = []
            for loja in self.db_lojas_raw:
                random.seed(loja['id'])
                node_idx = random.randint(0, len(self.nodes) - 1)
                loja_p = loja.copy(); loja_p['node_id'] = self.nodes[node_idx]
                self.lojas_no_mapa.append(loja_p)

            self.ativos, self.state = [], "SIM"
        except Exception as e: print(f"Erro: {e}")

    def to_px(self, lon, lat):
        pad = 80
        x = pad + (lon - self.min_x) / (self.max_x - self.min_x) * (WIDTH - 2*pad)
        y = pad + (self.max_y - lat) / (self.max_y - self.min_y) * (HEIGHT - 2*pad)
        return x, y

    def despachar(self):
        disponiveis = [e for e in self.ativos if e.state == "IDLE" or (e.tipo == "carro" and e.carga_atual < e.cap_max)]
        if disponiveis and self.pedidos_pendentes > 0:
            e, loja = random.choice(disponiveis), random.choice(self.lojas_no_mapa[:self.qtd_lojas_visiveis])
            try:
                p1 = nx.shortest_path(self.G, e.node, loja['node_id'], weight='length')
                p2 = nx.shortest_path(self.G, loja['node_id'], random.choice(self.nodes), weight='length')
                e.path, e.current_job, e.state = p1[1:] + p2[1:], {"loja_id": loja['id']}, "TO_SHOP"
                e.carga_atual += 1; self.pedidos_pendentes -= 1
                registrar_evento(e.id, loja['id'], "DESPACHADO")
            except: pass

    def run(self):
        btn_mack = Botao(WIDTH//2-150, 250, 300, 50, "MACKENZIE / HIGIENÓPOLIS")
        btn_itaim = Botao(WIDTH//2-150, 320, 300, 50, "ITAIM BIBI")
        btn_pinheiros = Botao(WIDTH//2-150, 390, 300, 50, "PINHEIROS")

        # Controles
        btn_v = Botao(15, 15, 80, 45, "VOLTAR", (200, 200, 200))
        btn_e_m = Botao(110, 15, 40, 45, "-", (255, 200, 200)); btn_e_p = Botao(155, 15, 40, 45, "+", (200, 255, 200))
        btn_l_m = Botao(WIDTH//2-130, 15, 40, 45, "-", (255, 200, 200)); btn_l_p = Botao(WIDTH//2-85, 15, 40, 45, "+", (200, 255, 200))
        btn_p_m = Botao(WIDTH-220, 15, 40, 45, "-", (255, 200, 200)); btn_p_p = Botao(WIDTH-175, 15, 40, 45, "+", (200, 255, 200))
        
        # TIME SCALE CONTROLS
        btn_t_m = Botao(WIDTH-90, 15, 35, 45, " << ", (220, 220, 255))
        btn_t_p = Botao(WIDTH-50, 15, 35, 45, " >> ", (220, 220, 255))

        while self.running:
            self.screen.fill(BG_COLOR)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT: self.running = False
                if ev.type == pygame.MOUSEBUTTONDOWN:
                    if self.state == "MENU":
                        if btn_mack.rect.collidepoint(ev.pos): self.setup_map("mapa_mackenzie.graphml")
                        if btn_itaim.rect.collidepoint(ev.pos): self.setup_map("mapa_itaim.graphml")
                        if btn_pinheiros.rect.collidepoint(ev.pos): self.setup_map("mapa_pinheiros.graphml")
                    else:
                        if btn_v.rect.collidepoint(ev.pos): self.state = "MENU"
                        if btn_e_p.rect.collidepoint(ev.pos) and len(self.ativos) < len(self.db_entregadores):
                            d = self.db_entregadores[len(self.ativos)]
                            self.ativos.append(Entregador(d, random.choice(self.nodes), self.pos_map))
                        if btn_e_m.rect.collidepoint(ev.pos) and self.ativos: self.ativos.pop()
                        if btn_l_p.rect.collidepoint(ev.pos): self.qtd_lojas_visiveis += 1
                        if btn_l_m.rect.collidepoint(ev.pos) and self.qtd_lojas_visiveis > 1: self.qtd_lojas_visiveis -= 1
                        if btn_p_p.rect.collidepoint(ev.pos): self.pedidos_pendentes += 1
                        if btn_p_m.rect.collidepoint(ev.pos) and self.pedidos_pendentes > 0: self.pedidos_pendentes -= 1
                        if btn_t_p.rect.collidepoint(ev.pos): self.time_scale = min(100, self.time_scale + 2)
                        if btn_t_m.rect.collidepoint(ev.pos): self.time_scale = max(1, self.time_scale - 2)

            if self.state == "MENU":
                txt = self.title_font.render("SIMULADOR LOGÍSTICA URBANA", True, TEXT_COLOR)
                self.screen.blit(txt, (WIDTH//2 - txt.get_width()//2, 150))
                btn_mack.draw(self.screen, self.font); btn_itaim.draw(self.screen, self.font); btn_pinheiros.draw(self.screen, self.font)
            else:
                for u, v in self.G.edges():
                    pygame.draw.line(self.screen, LINE_EMPTY, self.pos_map[u], self.pos_map[v], 1)
                
                for l in self.lojas_no_mapa[:self.qtd_lojas_visiveis]:
                    px, py = self.pos_map[l['node_id']]
                    pygame.draw.rect(self.screen, (60, 60, 60), (px-6, py-6, 12, 12))
                    txt_loja = pygame.font.SysFont("arial", 10, bold=True).render(l['nome'].upper(), True, (80, 80, 80))
                    self.screen.blit(txt_loja, (px + 10, py - 5))

                self.despachar()
                for e in self.ativos:
                    e.update(self.G, self.pos_map, self.edge_speed_kph, self.meters_per_pixel, self.time_scale)
                    e.draw(self.screen, self.pos_map)

                pygame.draw.rect(self.screen, UI_PANEL, (0, 0, WIDTH, 75))
                btn_v.draw(self.screen, self.font); btn_e_m.draw(self.screen, self.font); btn_e_p.draw(self.screen, self.font)
                btn_l_m.draw(self.screen, self.font); btn_l_p.draw(self.screen, self.font)
                btn_p_m.draw(self.screen, self.font); btn_p_p.draw(self.screen, self.font)
                btn_t_m.draw(self.screen, self.font); btn_t_p.draw(self.screen, self.font)

                self.screen.blit(self.font.render(f"FROTA: {len(self.ativos)}", True, TEXT_COLOR), (200, 27))
                self.screen.blit(self.font.render(f"LOJAS: {self.qtd_lojas_visiveis}", True, TEXT_COLOR), (WIDTH//2 - 40, 27))
                self.screen.blit(self.font.render(f"PEDIDOS: {self.pedidos_pendentes}", True, TEXT_COLOR), (WIDTH - 350, 27))
                self.screen.blit(self.font.render(f"TIME: {self.time_scale}x", True, TEXT_COLOR), (WIDTH - 155, 27))

            pygame.display.flip()
            self.clock.tick(60)
        pygame.quit()

if __name__ == "__main__":
    Simulador().run()