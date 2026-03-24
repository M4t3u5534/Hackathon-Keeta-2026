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
# GOTA DE CHUVA
# ---------------------------------------------------------------------------
class Gota:
    def __init__(self, width, height):
        self.reset(width, height)

    def reset(self, width, height):
        self.x      = random.randint(0, width)
        self.y      = random.uniform(-height * 0.5, 0)
        self.length = random.randint(8, 20)
        self.speed  = random.uniform(6, 14)
        self.alpha  = random.randint(80, 180)

    def update(self, height):
        self.y += self.speed
        if self.y > height + 20:
            self.y = random.uniform(-100, 0)
            self.x = random.randint(0, 2000)   # largura máxima razoável

    def draw(self, surf):
        end_x = self.x + self.length * 0.3
        end_y = self.y + self.length
        # Desenha linha semi-transparente simulando gota
        color = (150, 180, 255, self.alpha)
        start = (int(self.x), int(self.y))
        end   = (int(end_x),  int(end_y))
        pygame.draw.line(surf, (150, 180, 255), start, end, 1)

# ---------------------------------------------------------------------------
# CLASSE ENTREGADOR
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
        self.wait_start   = 0

    def update(self, G, pos_map, edge_speed_kph, meters_per_pixel, time_scale, current_time,
               mod_carro, mod_moto, edge_transito, edge_acidente):
        if self.state in ["WAIT_SHOP", "WAIT_DEST"]:
            if current_time - self.wait_start >= (10.0 / time_scale) * 1000:
                if self.state == "WAIT_SHOP":
                    self.state = "TO_DEST"
                    registrar_evento(self.id, self.current_job['loja_id'], "COLETADO")
                elif self.state == "WAIT_DEST":
                    self.carga_atual -= 1
                    if self.carga_atual <= 0:
                        registrar_evento(self.id, self.current_job['loja_id'], "ENTREGUE")
                        self.state, self.current_job, self.path = "IDLE", None, []
            return

        ref_node = self.target_node if self.target_node else self.node
        base_speed = min(self.vel_kph, edge_speed_kph.get((self.node, ref_node), DEFAULT_ROAD_SPEED_KPH))

        # Modificadores globais (chuva)
        mod = mod_carro if self.tipo == "carro" else mod_moto

        # Modificadores de aresta (trânsito / acidente na rua específica)
        edge_key = (self.node, ref_node)
        edge_key_rev = (ref_node, self.node)
        edge_mod = 1.0
        if edge_key in edge_transito or edge_key_rev in edge_transito:
            edge_mod *= 0.40 if self.tipo == "carro" else 0.80
        if edge_key in edge_acidente or edge_key_rev in edge_acidente:
            edge_mod *= 0.20 if self.tipo == "carro" else 0.50

        actual_speed = base_speed * mod * edge_mod

        dist_a_percorrer = ((actual_speed * 1000 / 3600) / meters_per_pixel / 60) * time_scale

        while dist_a_percorrer > 0:
            if not self.target_node:
                if self.path:
                    self.target_node = self.path.pop(0)
                else:
                    if self.state == "IDLE":
                        vizinhos = list(G.neighbors(self.node))
                        if vizinhos: self.target_node = random.choice(vizinhos)
                        else: break
                    else:
                        self.handle_arrival(current_time)
                        break

            tx, ty = pos_map[self.target_node]
            dx, dy = tx - self.x, ty - self.y
            dist_ao_no = math.hypot(dx, dy)

            if dist_ao_no <= dist_a_percorrer:
                self.x, self.y = tx, ty
                self.node = self.target_node
                self.target_node = None
                dist_a_percorrer -= dist_ao_no
            else:
                self.x += (dx / dist_ao_no) * dist_a_percorrer
                self.y += (dy / dist_ao_no) * dist_a_percorrer
                dist_a_percorrer = 0

    def handle_arrival(self, current_time):
        if self.state == "TO_SHOP":
            self.state = "WAIT_SHOP"
            self.wait_start = current_time
            registrar_evento(self.id, self.current_job['loja_id'], "AGUARDANDO COLETAR")
        elif self.state == "TO_DEST":
            self.state = "WAIT_DEST"
            self.wait_start = current_time
            registrar_evento(self.id, self.current_job['loja_id'], "AGUARDANDO ENTREGAR")

    def draw(self, surf, pos_map):
        if self.state not in ["IDLE", "WAIT_SHOP", "WAIT_DEST"]:
            pts = [(self.x, self.y)]
            if self.target_node:
                pts.append(pos_map[self.target_node])
            pts += [pos_map[n] for n in self.path]
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
# BOTÃO
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
        surf.blit(txt, (
            self.rect.centerx - txt.get_width()  // 2,
            self.rect.centery - txt.get_height() // 2
        ))

# ---------------------------------------------------------------------------
# SIMULADOR PRINCIPAL
# ---------------------------------------------------------------------------
class Simulador:
    def __init__(self):
        pygame.init()
        self.width, self.height = 1100, 750
        self.screen     = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
        pygame.display.set_caption("Hackathon 2026: Logística Dinâmica")
        self.font       = pygame.font.SysFont("segoeui", 16, bold=True)
        self.title_font = pygame.font.SysFont("segoeui", 28, bold=True)
        self.small_font = pygame.font.SysFont("segoeui", 12)
        self.clock       = pygame.time.Clock()
        self.running    = True
        self.state      = "MENU"
        self.time_scale = 4.0

        self.db_entregadores  = self.carregar_csv("entregadores.csv")
        self.db_lojas_raw     = self.carregar_csv("lojas.csv")
        self.lojas_no_mapa    = []
        self.ativos           = []
        self.pedidos_pendentes = 0
        self.qtd_lojas_visiveis = 3

        self.meters_per_pixel = 2.13
        self.edge_speed_kph   = {}
        self.nodes            = []
        self.G                = None

        # Variáveis de Eventos Dinâmicos (nível/quantidade)
        self.nivel_transito   = 0
        self.nivel_acidentes  = 0
        self.chuva_ativa      = False

        # Conjuntos de arestas afetadas por trânsito e acidente
        self.edge_transito    = set()   # set de (u, v)
        self.edge_acidente    = set()   # set de (u, v)

        # Gotas de chuva
        self.gotas = [Gota(self.width, self.height) for _ in range(200)]
        # Surface para gotas (semitransparente)
        self.rain_surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

    # -----------------------------------------------------------------------
    # UTILITÁRIOS DE ARESTA
    # -----------------------------------------------------------------------
    def _adicionar_intemperies_aresta(self, conjunto, novo_nivel, cor_log=""):
        """Ajusta o conjunto de arestas afetadas para o novo nível desejado."""
        if not self.G:
            return
        todas_arestas = list(self.G.edges())
        if not todas_arestas:
            return

        atual = len(conjunto)
        if novo_nivel > atual:
            # Adiciona arestas aleatórias ainda não presentes
            disponiveis = [e for e in todas_arestas if e not in conjunto and (e[1], e[0]) not in conjunto]
            random.shuffle(disponiveis)
            para_add = disponiveis[:novo_nivel - atual]
            for e in para_add:
                conjunto.add(e)
        elif novo_nivel < atual:
            # Remove arestas aleatórias até chegar no nível desejado
            lista = list(conjunto)
            random.shuffle(lista)
            para_rem = lista[:atual - novo_nivel]
            for e in para_rem:
                conjunto.discard(e)

    # -----------------------------------------------------------------------
    def carregar_csv(self, path):
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _calcular_metros_por_pixel(self):
        lat_center   = (self.min_y + self.max_y) / 2.0
        lon_deg_to_m = 111_320.0 * math.cos(math.radians(lat_center))
        map_width_m  = (self.max_x - self.min_x) * lon_deg_to_m
        canvas_px    = self.width - 2 * 80
        return map_width_m / max(1, canvas_px)

    def _recalcular_mapa(self):
        if self.G:
            nodes_data = dict(self.G.nodes(data=True))
            self.pos_map = {n: self.to_px(nodes_data[n]['x'], nodes_data[n]['y']) for n in self.nodes}
            self.meters_per_pixel = self._calcular_metros_por_pixel()
            for e in self.ativos:
                if not e.target_node:
                    e.x, e.y = self.pos_map[e.node]

    def setup_map(self, filename):
        print(f"Carregando {filename}...")
        try:
            G_raw = ox.load_graphml(filename)
            hwy_speeds = {
                'motorway': 90, 'trunk': 70, 'primary': 60,
                'secondary': 45, 'tertiary': 35, 'residential': 30,
                'unclassified': 30, 'service': 20
            }
            G_directed = ox.add_edge_speeds(G_raw, hwy_speeds=hwy_speeds)
            self.G = G_directed.to_undirected()
            self.nodes = list(self.G.nodes)
            nodes_data = dict(self.G.nodes(data=True))

            xs = [d['x'] for d in nodes_data.values()]; ys = [d['y'] for d in nodes_data.values()]
            self.min_x, self.max_x = min(xs), max(xs)
            self.min_y, self.max_y = min(ys), max(ys)

            self._recalcular_mapa()

            self.edge_speed_kph = {}
            for u, v, data in self.G.edges(data=True):
                spd = data.get('speed_kph', DEFAULT_ROAD_SPEED_KPH)
                spd = float(spd[0]) if isinstance(spd, list) else float(spd)
                self.edge_speed_kph[(u, v)] = spd
                self.edge_speed_kph[(v, u)] = spd

            self.lojas_no_mapa = []
            for loja in self.db_lojas_raw:
                random.seed(loja['id'])
                loja_p = loja.copy()
                loja_p['node_id'] = random.choice(self.nodes)
                self.lojas_no_mapa.append(loja_p)

            # Reseta eventos ao trocar de mapa
            self.ativos          = []
            self.edge_transito   = set()
            self.edge_acidente   = set()
            self.nivel_transito  = 0
            self.nivel_acidentes = 0
            self.state = "SIM"
        except Exception as e:
            print(f"Erro: {e}")

    def to_px(self, lon, lat):
        pad = 80
        x = pad + (lon - self.min_x) / (self.max_x - self.min_x) * (self.width  - 2 * pad)
        y = pad + (self.max_y - lat) / (self.max_y - self.min_y) * (self.height - 2 * pad)
        return x, y

    def despachar(self):
        disponiveis = [e for e in self.ativos if e.state == "IDLE" or (e.tipo == "carro" and e.carga_atual < e.cap_max)]
        lojas_ativas = self.lojas_no_mapa[:self.qtd_lojas_visiveis]

        if disponiveis and self.pedidos_pendentes > 0 and lojas_ativas:
            e = random.choice(disponiveis)
            loja = random.choice(lojas_ativas)
            destino = random.choice(self.nodes)

            ponto_partida = e.target_node if e.target_node else e.node

            try:
                l_node = loja['node_id']
                p1 = nx.shortest_path(self.G, ponto_partida, l_node, weight='length')
                p2 = nx.shortest_path(self.G, l_node, destino, weight='length')

                e.path = p1[1:] + p2[1:]
                e.current_job = {"loja_id": loja['id']}
                e.state = "TO_SHOP"
                e.carga_atual += 1
                self.pedidos_pendentes -= 1
                registrar_evento(e.id, loja['id'], "DESPACHADO")
            except:
                pass

    # -----------------------------------------------------------------------
    # ANIMAÇÃO DE CHUVA
    # -----------------------------------------------------------------------
    def _update_chuva(self):
        """Atualiza posição das gotas."""
        for g in self.gotas:
            g.update(self.height)
            # Reposiciona x se a tela foi redimensionada
            if g.x > self.width:
                g.x = random.randint(0, self.width)

    def _draw_chuva(self):
        """Desenha animação de gotas de chuva sobre a tela."""
        self.rain_surf.fill((0, 0, 0, 0))   # limpa transparente
        for g in self.gotas:
            end_x = int(g.x + g.length * 0.25)
            end_y = int(g.y + g.length)
            pygame.draw.line(self.rain_surf, (140, 170, 255, g.alpha),
                             (int(g.x), int(g.y)), (end_x, end_y), 1)
        self.screen.blit(self.rain_surf, (0, 0))

    # -----------------------------------------------------------------------
    # DESENHO DAS RUAS COM INTEMPÉRIES
    # -----------------------------------------------------------------------
    def _draw_edges(self):
        """Desenha todas as arestas, destacando trânsito e acidentes."""
        for u, v in self.G.edges():
            edge_key     = (u, v)
            edge_key_rev = (v, u)

            tem_acidente  = edge_key in self.edge_acidente  or edge_key_rev in self.edge_acidente
            tem_transito  = edge_key in self.edge_transito  or edge_key_rev in self.edge_transito

            if tem_acidente:
                color = (220, 20, 20)   # vermelho forte = acidente
                width = 4
            elif tem_transito:
                color = (255, 165, 0)   # laranja = trânsito
                width = 3
            else:
                spd   = self.edge_speed_kph.get(edge_key, DEFAULT_ROAD_SPEED_KPH)
                color = self._road_color(spd)
                width = 1

            pygame.draw.line(self.screen, color,
                             self.pos_map[u], self.pos_map[v], width)

        # Ícones de acidente (X) e trânsito (T) no meio da aresta
        for edge_key in self.edge_acidente:
            u, v = edge_key
            if u in self.pos_map and v in self.pos_map:
                mx = int((self.pos_map[u][0] + self.pos_map[v][0]) / 2)
                my = int((self.pos_map[u][1] + self.pos_map[v][1]) / 2)
                lbl = self.small_font.render("✖", True, (200, 0, 0))
                self.screen.blit(lbl, (mx - lbl.get_width()//2, my - lbl.get_height()//2))

        for edge_key in self.edge_transito:
            u, v = edge_key
            if u in self.pos_map and v in self.pos_map:
                mx = int((self.pos_map[u][0] + self.pos_map[v][0]) / 2)
                my = int((self.pos_map[u][1] + self.pos_map[v][1]) / 2)
                # Só desenha T se não houver acidente no mesmo trecho
                edge_rev = (v, u)
                if edge_key not in self.edge_acidente and edge_rev not in self.edge_acidente:
                    lbl = self.small_font.render("▲", True, (200, 100, 0))
                    self.screen.blit(lbl, (mx - lbl.get_width()//2, my - lbl.get_height()//2))

    # -----------------------------------------------------------------------
    # LOOP PRINCIPAL
    # -----------------------------------------------------------------------
    def run(self):
        while self.running:
            current_time = pygame.time.get_ticks()

            btn_mack      = Botao(self.width//2-150, 250, 300, 50, "MACKENZIE / HIGIENÓPOLIS")
            btn_itaim     = Botao(self.width//2-150, 320, 300, 50, "ITAIM BIBI")
            btn_pinheiros = Botao(self.width//2-150, 390, 300, 50, "PINHEIROS")

            # LINHA 1 DE UI (Controles Originais)
            btn_v         = Botao(15, 15, 80, 45, "VOLTAR", (200, 200, 200))
            btn_e_m       = Botao(110, 15, 40, 45, "-", (255, 200, 200))
            btn_e_p       = Botao(155, 15, 40, 45, "+", (200, 255, 200))
            btn_l_m       = Botao(self.width//2-130, 15, 40, 45, "-", (255, 200, 200))
            btn_l_p       = Botao(self.width//2-85,  15, 40, 45, "+", (200, 255, 200))
            btn_p_m       = Botao(self.width-220, 15, 40, 45, "-", (255, 200, 200))
            btn_p_p       = Botao(self.width-175, 15, 40, 45, "+", (200, 255, 200))
            btn_t_m       = Botao(self.width-90,  15, 35, 45, " << ", (220, 220, 255))
            btn_t_p       = Botao(self.width-50,  15, 35, 45, " >> ", (220, 220, 255))

            # LINHA 2 DE UI (Controles Dinâmicos)
            btn_tr_m      = Botao(110, 65, 40, 40, "-", (255, 200, 200))
            btn_tr_p      = Botao(155, 65, 40, 40, "+", (200, 255, 200))
            btn_ac_m      = Botao(380, 65, 40, 40, "-", (255, 200, 200))
            btn_ac_p      = Botao(425, 65, 40, 40, "+", (200, 255, 200))

            chuva_cor     = (180, 200, 255) if self.chuva_ativa else (220, 220, 220)
            txt_chuva     = "[X] CHUVA" if self.chuva_ativa else "[ ] CHUVA"
            btn_chuva     = Botao(650, 65, 140, 40, txt_chuva, chuva_cor)

            # Fundo
            tela_bg = (220, 228, 235) if self.chuva_ativa else BG_COLOR
            self.screen.fill(tela_bg)

            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                elif ev.type == pygame.VIDEORESIZE:
                    self.width, self.height = ev.w, ev.h
                    self.screen = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
                    self.rain_surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
                    self._recalcular_mapa()

                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if self.state == "MENU":
                        if btn_mack.rect.collidepoint(ev.pos):      self.setup_map("mapa_mackenzie.graphml")
                        if btn_itaim.rect.collidepoint(ev.pos):     self.setup_map("mapa_itaim.graphml")
                        if btn_pinheiros.rect.collidepoint(ev.pos): self.setup_map("mapa_pinheiros.graphml")

                    elif self.state == "SIM":
                        # Botões originais
                        if btn_v.rect.collidepoint(ev.pos):   self.state = "MENU"
                        if btn_e_p.rect.collidepoint(ev.pos) and len(self.ativos) < len(self.db_entregadores):
                            d = self.db_entregadores[len(self.ativos)]
                            self.ativos.append(Entregador(d, random.choice(self.nodes), self.pos_map))
                        if btn_e_m.rect.collidepoint(ev.pos) and self.ativos: self.ativos.pop()
                        if btn_l_p.rect.collidepoint(ev.pos) and self.qtd_lojas_visiveis < len(self.lojas_no_mapa): self.qtd_lojas_visiveis += 1
                        if btn_l_m.rect.collidepoint(ev.pos) and self.qtd_lojas_visiveis > 1: self.qtd_lojas_visiveis -= 1
                        if btn_p_p.rect.collidepoint(ev.pos): self.pedidos_pendentes += 1
                        if btn_p_m.rect.collidepoint(ev.pos) and self.pedidos_pendentes > 0: self.pedidos_pendentes -= 1
                        if btn_t_p.rect.collidepoint(ev.pos): self.time_scale = min(100, self.time_scale + 2)
                        if btn_t_m.rect.collidepoint(ev.pos): self.time_scale = max(1, self.time_scale - 2)

                        # Trânsito: ajusta arestas afetadas
                        if btn_tr_p.rect.collidepoint(ev.pos):
                            novo = self.nivel_transito + 1
                            self._adicionar_intemperies_aresta(self.edge_transito, novo)
                            self.nivel_transito = len(self.edge_transito)
                        if btn_tr_m.rect.collidepoint(ev.pos) and self.nivel_transito > 0:
                            novo = self.nivel_transito - 1
                            self._adicionar_intemperies_aresta(self.edge_transito, novo)
                            self.nivel_transito = len(self.edge_transito)

                        # Acidentes: ajusta arestas afetadas
                        if btn_ac_p.rect.collidepoint(ev.pos):
                            novo = self.nivel_acidentes + 1
                            self._adicionar_intemperies_aresta(self.edge_acidente, novo)
                            self.nivel_acidentes = len(self.edge_acidente)
                        if btn_ac_m.rect.collidepoint(ev.pos) and self.nivel_acidentes > 0:
                            novo = self.nivel_acidentes - 1
                            self._adicionar_intemperies_aresta(self.edge_acidente, novo)
                            self.nivel_acidentes = len(self.edge_acidente)

                        # Chuva
                        if btn_chuva.rect.collidepoint(ev.pos): self.chuva_ativa = not self.chuva_ativa

            # ---------------------------------------------------------------
            if self.state == "MENU":
                txt = self.title_font.render("SIMULADOR LOGÍSTICA URBANA", True, TEXT_COLOR)
                self.screen.blit(txt, (self.width//2 - txt.get_width()//2, 150))
                btn_mack.draw(self.screen, self.font)
                btn_itaim.draw(self.screen, self.font)
                btn_pinheiros.draw(self.screen, self.font)

            elif self.state == "SIM":
                # Ruas com indicadores de trânsito/acidente por aresta
                self._draw_edges()

                # Lojas
                for l in self.lojas_no_mapa[:self.qtd_lojas_visiveis]:
                    nid = l['node_id']
                    pygame.draw.rect(self.screen, (60, 60, 60), (*self.pos_map[nid], 12, 12))
                    lbl = pygame.font.SysFont("arial", 10).render(l['nome'][:15], True, (100, 100, 100))
                    self.screen.blit(lbl, (self.pos_map[nid][0]-10, self.pos_map[nid][1]-15))

                self.despachar()

                # Modificadores globais
                mod_carro = 1.0
                mod_moto  = 1.0
                if self.chuva_ativa:
                    mod_carro *= 0.60
                    mod_moto  *= 0.60

                for e in self.ativos:
                    e.update(self.G, self.pos_map, self.edge_speed_kph, self.meters_per_pixel,
                             self.time_scale, current_time, mod_carro, mod_moto,
                             self.edge_transito, self.edge_acidente)
                    e.draw(self.screen, self.pos_map)

                self._draw_speed_legend()

                # Animação de chuva (sobre o mapa, antes do painel)
                if self.chuva_ativa:
                    self._update_chuva()
                    self._draw_chuva()

                # UI PANEL
                pygame.draw.rect(self.screen, UI_PANEL, (0, 0, self.width, 120))

                # Botões linha 1
                btn_v.draw(self.screen, self.font)
                btn_e_m.draw(self.screen, self.font); btn_e_p.draw(self.screen, self.font)
                btn_l_m.draw(self.screen, self.font); btn_l_p.draw(self.screen, self.font)
                btn_p_m.draw(self.screen, self.font); btn_p_p.draw(self.screen, self.font)
                btn_t_m.draw(self.screen, self.font); btn_t_p.draw(self.screen, self.font)

                # Botões linha 2
                btn_tr_m.draw(self.screen, self.font); btn_tr_p.draw(self.screen, self.font)
                btn_ac_m.draw(self.screen, self.font); btn_ac_p.draw(self.screen, self.font)
                btn_chuva.draw(self.screen, self.font)

                # Textos linha 1
                self.screen.blit(self.font.render(f"FROTA: {len(self.ativos)}", True, TEXT_COLOR), (205, 27))
                self.screen.blit(self.font.render(f"LOJAS ATIVAS: {self.qtd_lojas_visiveis}", True, TEXT_COLOR), (self.width//2 - 30, 27))
                self.screen.blit(self.font.render(f"PEDIDOS: {self.pedidos_pendentes}", True, TEXT_COLOR), (self.width - 340, 27))
                self.screen.blit(self.small_font.render(f"Escala: {self.meters_per_pixel:.2f} m/px", True, (120, 120, 120)), (self.width - 150, 95))
                self.screen.blit(self.font.render(f"TIME: {self.time_scale}x", True, TEXT_COLOR), (self.width - 155, 10))

                # Textos linha 2
                self.screen.blit(self.font.render(f"TRÂNSITO: {self.nivel_transito}", True, TEXT_COLOR), (205, 77))
                self.screen.blit(self.font.render(f"ACIDENTES: {self.nivel_acidentes}", True, TEXT_COLOR), (475, 77))

                # Legenda de intempéries
                lx, ly = 10, self.height - 120
                pygame.draw.rect(self.screen, (255, 165, 0), (lx, ly, 14, 10))
                self.screen.blit(self.small_font.render("▲ Trânsito na rua", True, TEXT_COLOR), (lx + 18, ly - 1))
                ly += 16
                pygame.draw.rect(self.screen, (220, 20, 20), (lx, ly, 14, 10))
                self.screen.blit(self.small_font.render("✖ Acidente na rua", True, TEXT_COLOR), (lx + 18, ly - 1))

            pygame.display.flip()
            self.clock.tick(60)
        pygame.quit()

    @staticmethod
    def _road_color(speed_kph):
        if speed_kph <= 30: return (0, 200, 80)
        if speed_kph <= 45: return (255, 215, 0)
        if speed_kph <= 60: return (255, 140, 0)
        return (220, 20, 60)

    def _draw_speed_legend(self):
        items = [
            ((0, 200, 80),   "≤30 km/h  Residencial"),
            ((255, 200, 0),  "≤50 km/h  Via local"),
            ((255, 140, 0),  "≤70 km/h  Avenida"),
            ((230, 30, 30),  " >70 km/h  Via expressa"),
        ]
        fx, fy = 10, self.height - 90
        for color, label in items:
            pygame.draw.rect(self.screen, color, (fx, fy, 14, 10))
            lbl = self.small_font.render(label, True, TEXT_COLOR)
            self.screen.blit(lbl, (fx + 18, fy - 1))
            fy += 16

if __name__ == "__main__":
    Simulador().run()