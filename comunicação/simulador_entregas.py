import pygame
import networkx as nx
import osmnx as ox
import os
import random
import math
import threading
import csv
import time

# ─── ESTÉTICA ──────────────────────────────────────────────────────────────────
BG_COLOR     = (242, 238, 230)
UI_PANEL     = (230, 225, 215)
TEXT_COLOR   = (60, 60, 60)
ROUTE_COLORS = [(255, 51, 102), (0, 194, 209), (255, 204, 0), (0, 153, 102), (155, 89, 182)]

DEFAULT_ROAD_SPEED_KPH = 30.0

# Painel maior para acomodar labels acima dos botões (2 linhas)
UI_PANEL_HEIGHT = 155

# Posições internas do painel — Row 1 e Row 2
Y_R1_LBL, Y_R1_BTN, H_R1 = 8,   28, 40   # label y, botão y, altura do botão
Y_R2_LBL, Y_R2_BTN, H_R2 = 82, 100, 38

# ─── PRECIFICAÇÃO ──────────────────────────────────────────────────────────────
PRECO_BASE_KM  = 2.50   # R$ / km  (restaurante → destino)
PRECO_POR_ITEM = 0.50   # R$ / item transportado
RAIN_BONUS     = 0.15   # +15 % de bônus em caso de chuva

# ─── LOG ───────────────────────────────────────────────────────────────────────
log_lock = threading.Lock()
LOG_FILE  = "log_entregas.csv"


def registrar_entrega_final(id_e, id_r, delta_t_s, dist_m, qtd_itens,
                             chuva_ativa, nivel_transito, nivel_acidente):
    """Grava APENAS o status final ENTREGUE com todas as métricas no CSV."""
    def _write():
        with log_lock:
            existe = os.path.exists(LOG_FILE)
            with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if not existe:
                    w.writerow([
                        "Timestamp", "Entregador_ID", "Restaurante_ID",
                        "Status_Final", "Tempo_Entrega_s",
                        "Preco_Corrida_R$", "Intemperismo"
                    ])
                # Cálculo do preço
                dist_km = dist_m / 1000.0
                preco   = dist_km * PRECO_BASE_KM + qtd_itens * PRECO_POR_ITEM
                if chuva_ativa:
                    preco *= (1.0 + RAIN_BONUS)

                # Descrição do intemperismo no momento da entrega
                intemp = []
                if chuva_ativa:        intemp.append("Chuva")
                if nivel_transito > 0: intemp.append("Trânsito")
                if nivel_acidente > 0: intemp.append("Acidente")

                w.writerow([
                    time.strftime("%H:%M:%S"),
                    id_e, id_r,
                    "ENTREGUE",
                    round(delta_t_s, 1),
                    f"R$ {preco:.2f}",
                    ", ".join(intemp) if intemp else "Nenhum"
                ])
    threading.Thread(target=_write, daemon=True).start()


# ─── GOTA DE CHUVA ─────────────────────────────────────────────────────────────
class Gota:
    def __init__(self, width, height):
        self.reset(width, height)

    def reset(self, width, height):
        self.x      = random.randint(0, width)
        self.y      = random.uniform(-height * 0.5, 0)
        self.length = random.randint(18, 42)
        self.width  = random.randint(2, 4)
        self.speed  = random.uniform(10, 22)
        self.alpha  = random.randint(140, 230)

    def update(self, height):
        self.y += self.speed
        if self.y > height + 30:
            self.y = random.uniform(-150, 0)
            self.x = random.randint(0, 2000)

    def draw(self, surf):
        end_x = int(self.x + self.length * 0.3)
        end_y = int(self.y + self.length)
        pygame.draw.line(surf, (150, 185, 255, self.alpha),
                         (int(self.x), int(self.y)), (end_x, end_y), self.width)


# ─── ENTREGADOR ────────────────────────────────────────────────────────────────
class Entregador:
    """
    Sistema multi-parada: o veículo coleta pedidos em até cap_max restaurantes
    e entrega nos respectivos destinos antes de voltar ao estado IDLE.

    Fila de paradas (stop_queue): lista de dicts
        {'node': int, 'phase': 'SHOP'|'DEST', 'job': {...}}

    Estados internos: IDLE | MOVING | WAITING
    """

    def __init__(self, data, start_node, pos_map):
        self.id          = data.get('id', '999')
        self.tipo        = data.get('tipo', 'moto')
        self.vel_kph     = float(data.get('velocidade', 30.0))
        self.cap_max     = max(1, int(data.get('capacidade', 1)))
        self.carga_atual = 0
        self.node        = start_node
        self.x, self.y   = pos_map[start_node]
        self.color       = random.choice(ROUTE_COLORS)
        self.state       = "IDLE"      # IDLE | MOVING | WAITING
        self.target_node = None
        self.path        = []
        self.stop_queue  = []          # paradas pendentes
        self.wait_start  = 0

    # ── Atualização de física e lógica ────────────────────────────────────────
    def update(self, G, pos_map, edge_speed_kph, meters_per_pixel, time_scale,
               current_time, mod_carro, mod_moto, edge_transito, edge_acidente,
               chuva_ativa, nivel_transito, nivel_acidentes):

        # ── WAITING: aguardando na parada atual (coleta ou entrega) ──────────
        if self.state == "WAITING":
            if current_time - self.wait_start < (10.0 / time_scale) * 1000:
                return                             # ainda aguardando

            if not self.stop_queue:
                self.state       = "IDLE"
                self.carga_atual = 0
                return

            stop = self.stop_queue.pop(0)

            if stop['phase'] == "DEST":
                # Registrar entrega final
                job     = stop['job']
                delta_t = (current_time - job['accept_time']) / 1000.0
                registrar_entrega_final(
                    self.id, job['loja_id'],
                    delta_t, job['dist_m'], job['qtd_itens'],
                    chuva_ativa, nivel_transito, nivel_acidentes
                )
                self.carga_atual = max(0, self.carga_atual - 1)
            # SHOP: coleta realizada — sem log (apenas final)

            if self.stop_queue:
                next_node = self.stop_queue[0]['node']
                try:
                    p = nx.shortest_path(G, self.node, next_node, weight='length')
                    self.path = p[1:]
                except Exception:
                    self.path = []
                self.state = "MOVING"
            else:
                self.carga_atual = 0
                self.state       = "IDLE"
            return

        # ── Cálculo de velocidade ─────────────────────────────────────────────
        ref_node   = self.target_node if self.target_node else self.node
        base_speed = min(self.vel_kph,
                         edge_speed_kph.get((self.node, ref_node), DEFAULT_ROAD_SPEED_KPH))
        mod = mod_carro if self.tipo == "carro" else mod_moto

        ek  = (self.node, ref_node)
        ekr = (ref_node, self.node)
        em  = 1.0
        if ek in edge_transito or ekr in edge_transito:
            em *= 0.40 if self.tipo == "carro" else 0.80
        if ek in edge_acidente or ekr in edge_acidente:
            em *= 0.20 if self.tipo == "carro" else 0.50

        actual_speed     = base_speed * mod * em
        dist_a_percorrer = ((actual_speed * 1000 / 3600) / meters_per_pixel / 60) * time_scale

        # ── Movimento ────────────────────────────────────────────────────────
        while dist_a_percorrer > 0:
            if not self.target_node:
                if self.path:
                    self.target_node = self.path.pop(0)
                else:
                    if self.state == "IDLE":
                        viz = list(G.neighbors(self.node))
                        if viz:
                            self.target_node = random.choice(viz)
                        else:
                            break
                    else:                          # MOVING → chegou na parada
                        self.state      = "WAITING"
                        self.wait_start = current_time
                        break

            tx, ty = pos_map[self.target_node]
            dx, dy = tx - self.x, ty - self.y
            dist_ao_no = math.hypot(dx, dy)

            if dist_ao_no <= dist_a_percorrer:
                self.x, self.y   = tx, ty
                self.node        = self.target_node
                self.target_node = None
                dist_a_percorrer -= dist_ao_no
            else:
                self.x += (dx / dist_ao_no) * dist_a_percorrer
                self.y += (dy / dist_ao_no) * dist_a_percorrer
                dist_a_percorrer = 0

    # ── Desenho ──────────────────────────────────────────────────────────────
    def draw(self, surf, pos_map):
        # Rota projetada visível enquanto em movimento
        if self.state == "MOVING":
            pts = [(self.x, self.y)]
            if self.target_node and self.target_node in pos_map:
                pts.append(pos_map[self.target_node])
            pts += [pos_map[n] for n in self.path if n in pos_map]
            if len(pts) > 1:
                pygame.draw.lines(surf, self.color, False, pts, 4)

        pos = (int(self.x), int(self.y))
        if self.tipo == "carro":
            pygame.draw.rect(surf, self.color, (pos[0]-8, pos[1]-8, 16, 16))
            pygame.draw.rect(surf, (255, 255, 255), (pos[0]-8, pos[1]-8, 16, 16), 1)
        else:
            pygame.draw.circle(surf, self.color, pos, 6)
            pygame.draw.circle(surf, (255, 255, 255), pos, 6, 1)


# ─── BOTÃO ─────────────────────────────────────────────────────────────────────
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


# ─── SIMULADOR PRINCIPAL ───────────────────────────────────────────────────────
class Simulador:
    def __init__(self):
        pygame.init()
        self.width, self.height = 1100, 750
        self.screen      = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
        pygame.display.set_caption("Hackathon 2026: Logística Dinâmica")
        self.font        = pygame.font.SysFont("segoeui", 16, bold=True)
        self.title_font  = pygame.font.SysFont("segoeui", 28, bold=True)
        self.small_font  = pygame.font.SysFont("segoeui", 12)
        self.medium_font = pygame.font.SysFont("segoeui", 20, bold=True)
        self.clock       = pygame.time.Clock()
        self.running     = True
        self.state       = "MENU"
        self.time_scale  = 4.0

        self.db_entregadores    = self.carregar_csv("entregadores.csv")
        self.db_lojas_raw       = self.carregar_csv("lojas.csv")
        self.lojas_no_mapa      = []
        self.ativos             = []
        self.pedidos_pendentes  = 0
        self.qtd_lojas_visiveis = 3

        self.meters_per_pixel = 2.13
        self.edge_speed_kph   = {}
        self.nodes            = []
        self.G                = None

        self.nivel_transito  = 0
        self.nivel_acidentes = 0
        self.chuva_ativa     = False

        self.edge_transito = set()
        self.edge_acidente = set()

        self.gotas     = [Gota(self.width, self.height) for _ in range(400)]
        self.rain_surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

        # Modo automático
        self.auto_mode = False
        self._auto_chuva_interval_base    = 25_000
        self._auto_transito_interval_base = 18_000
        self._auto_acidente_interval_base = 30_000
        self._auto_last_chuva    = 0
        self._auto_last_transito = 0
        self._auto_last_acidente = 0

    # ── Utilitários de aresta ─────────────────────────────────────────────────
    def _adicionar_intemperies_aresta(self, conjunto, novo_nivel):
        if not self.G:
            return
        todas = list(self.G.edges())
        if not todas:
            return
        atual = len(conjunto)
        if novo_nivel > atual:
            disp = [e for e in todas
                    if e not in conjunto and (e[1], e[0]) not in conjunto]
            random.shuffle(disp)
            for e in disp[:novo_nivel - atual]:
                conjunto.add(e)
        elif novo_nivel < atual:
            lista = list(conjunto)
            random.shuffle(lista)
            for e in lista[:atual - novo_nivel]:
                conjunto.discard(e)

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
            nd = dict(self.G.nodes(data=True))
            self.pos_map = {n: self.to_px(nd[n]['x'], nd[n]['y']) for n in self.nodes}
            self.meters_per_pixel = self._calcular_metros_por_pixel()
            for e in self.ativos:
                if not e.target_node:
                    e.x, e.y = self.pos_map[e.node]

    def setup_map(self, filename):
        print(f"Carregando {filename}...")
        try:
            G_raw      = ox.load_graphml(filename)
            hwy_speeds = {
                'motorway': 90, 'trunk': 70, 'primary': 60,
                'secondary': 45, 'tertiary': 35, 'residential': 30,
                'unclassified': 30, 'service': 20
            }
            G_directed  = ox.add_edge_speeds(G_raw, hwy_speeds=hwy_speeds)
            self.G      = G_directed.to_undirected()
            self.nodes  = list(self.G.nodes)
            nd          = dict(self.G.nodes(data=True))

            xs = [d['x'] for d in nd.values()]
            ys = [d['y'] for d in nd.values()]
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
                lp = loja.copy()
                lp['node_id'] = random.choice(self.nodes)
                self.lojas_no_mapa.append(lp)

            self.ativos          = []
            self.edge_transito   = set()
            self.edge_acidente   = set()
            self.nivel_transito  = 0
            self.nivel_acidentes = 0
            self.state = "SIM"
        except Exception as e:
            print(f"Erro ao carregar mapa: {e}")

    def to_px(self, lon, lat):
        pad_top  = UI_PANEL_HEIGHT + 10
        pad_side = 80
        pad_bot  = 60
        x = pad_side + (lon - self.min_x) / (self.max_x - self.min_x) * (self.width  - 2 * pad_side)
        y = pad_top  + (self.max_y - lat) / (self.max_y - self.min_y)  * (self.height - pad_top - pad_bot)
        return x, y

    # ── Despacho de pedidos (suporta capacidade multi-parada) ─────────────────
    def despachar(self):
        lojas_ativas = self.lojas_no_mapa[:self.qtd_lojas_visiveis]
        if not lojas_ativas or self.pedidos_pendentes <= 0:
            return

        for e in self.ativos:
            if e.state != "IDLE":
                continue
            if self.pedidos_pendentes <= 0:
                break

            # Quantos pedidos este veículo pode assumir agora
            n_orders = min(e.cap_max, self.pedidos_pendentes, len(lojas_ativas))
            if n_orders <= 0:
                continue

            now            = pygame.time.get_ticks()
            selected_lojas = random.sample(lojas_ativas, n_orders)
            destinos       = [random.choice(self.nodes) for _ in range(n_orders)]

            jobs = []
            for loja, dest in zip(selected_lojas, destinos):
                # Distância euclidiana (px → metros) entre restaurante e destino
                l_pos  = self.pos_map.get(loja['node_id'], (0, 0))
                d_pos  = self.pos_map.get(dest, (0, 0))
                dist_m = math.hypot(d_pos[0] - l_pos[0],
                                    d_pos[1] - l_pos[1]) * self.meters_per_pixel
                jobs.append({
                    'loja_id':    loja['id'],
                    'loja_node':  loja['node_id'],
                    'dest_node':  dest,
                    'accept_time': now,
                    'qtd_itens':  1,
                    'dist_m':     max(dist_m, 100.0),   # mínimo 100 m
                })

            # Fila: todos os restaurantes primeiro, depois todos os destinos
            stop_queue = (
                [{'node': j['loja_node'], 'phase': 'SHOP', 'job': j} for j in jobs] +
                [{'node': j['dest_node'], 'phase': 'DEST', 'job': j} for j in jobs]
            )

            ponto = e.target_node if e.target_node else e.node
            try:
                p = nx.shortest_path(self.G, ponto, stop_queue[0]['node'], weight='length')
                e.path        = p[1:]
                e.stop_queue  = stop_queue
                e.carga_atual = n_orders
                e.state       = "MOVING"
                self.pedidos_pendentes -= n_orders
            except Exception:
                pass

    # ── Modo automático ───────────────────────────────────────────────────────
    def _update_auto(self, current_time):
        if not self.G:
            return
        ts = max(1.0, self.time_scale)

        if current_time - self._auto_last_chuva >= self._auto_chuva_interval_base / ts:
            self._auto_last_chuva = current_time
            self.chuva_ativa = not self.chuva_ativa

        if current_time - self._auto_last_transito >= self._auto_transito_interval_base / ts:
            self._auto_last_transito = current_time
            if self.chuva_ativa:
                if self.nivel_transito < 6:
                    novo = self.nivel_transito + random.randint(1, 2)
                    self._adicionar_intemperies_aresta(self.edge_transito, novo)
                    self.nivel_transito = len(self.edge_transito)
            else:
                if self.nivel_transito > 0:
                    novo = max(0, self.nivel_transito - random.randint(1, 2))
                    self._adicionar_intemperies_aresta(self.edge_transito, novo)
                    self.nivel_transito = len(self.edge_transito)

        if current_time - self._auto_last_acidente >= self._auto_acidente_interval_base / ts:
            self._auto_last_acidente = current_time
            if self.nivel_acidentes < 3:
                if random.random() < 0.65:
                    novo = self.nivel_acidentes + 1
                    self._adicionar_intemperies_aresta(self.edge_acidente, novo)
                    self.nivel_acidentes = len(self.edge_acidente)
            else:
                novo = max(0, self.nivel_acidentes - random.randint(1, 2))
                self._adicionar_intemperies_aresta(self.edge_acidente, novo)
                self.nivel_acidentes = len(self.edge_acidente)

    # ── Animação de chuva ─────────────────────────────────────────────────────
    def _update_chuva(self):
        for g in self.gotas:
            g.update(self.height)
            if g.x > self.width:
                g.x = random.randint(0, self.width)

    def _draw_chuva(self):
        self.rain_surf.fill((0, 0, 0, 0))
        for g in self.gotas:
            end_x = int(g.x + g.length * 0.28)
            end_y = int(g.y + g.length)
            pygame.draw.line(self.rain_surf, (150, 185, 255, g.alpha),
                             (int(g.x), int(g.y)), (end_x, end_y), g.width)
        self.screen.blit(self.rain_surf, (0, 0))

    # ── Desenho de ruas ───────────────────────────────────────────────────────
    def _draw_edges(self):
        for u, v in self.G.edges():
            ek  = (u, v)
            ekr = (v, u)
            tem_ac = ek in self.edge_acidente or ekr in self.edge_acidente
            tem_tr = ek in self.edge_transito or ekr in self.edge_transito
            if tem_ac:
                color, width = (220, 20, 20), 4
            elif tem_tr:
                color, width = (255, 165, 0), 3
            else:
                spd   = self.edge_speed_kph.get(ek, DEFAULT_ROAD_SPEED_KPH)
                color = self._road_color(spd)
                width = 1
            pygame.draw.line(self.screen, color, self.pos_map[u], self.pos_map[v], width)

        for ek in self.edge_acidente:
            u, v = ek
            if u in self.pos_map and v in self.pos_map:
                mx = int((self.pos_map[u][0] + self.pos_map[v][0]) / 2)
                my = int((self.pos_map[u][1] + self.pos_map[v][1]) / 2)
                lbl = self.small_font.render("✖", True, (200, 0, 0))
                self.screen.blit(lbl, (mx - lbl.get_width()//2, my - lbl.get_height()//2))

        for ek in self.edge_transito:
            u, v = ek
            if u in self.pos_map and v in self.pos_map:
                mx = int((self.pos_map[u][0] + self.pos_map[v][0]) / 2)
                my = int((self.pos_map[u][1] + self.pos_map[v][1]) / 2)
                if ek not in self.edge_acidente and (v, u) not in self.edge_acidente:
                    lbl = self.small_font.render("▲", True, (200, 100, 0))
                    self.screen.blit(lbl, (mx - lbl.get_width()//2, my - lbl.get_height()//2))

    @staticmethod
    def _road_color(speed_kph):
        if speed_kph <= 30: return (0, 200, 80)
        if speed_kph <= 45: return (255, 215, 0)
        if speed_kph <= 60: return (255, 140, 0)
        return (220, 20, 60)

    def _draw_speed_legend(self):
        items = [
            ((0,   200, 80),  "≤30 km/h  Residencial"),
            ((255, 200,  0),  "≤50 km/h  Via local"),
            ((255, 140,  0),  "≤70 km/h  Avenida"),
            ((230,  30, 30),  " >70 km/h  Via expressa"),
        ]
        fx, fy = 10, self.height - 90
        for color, label in items:
            pygame.draw.rect(self.screen, color, (fx, fy, 14, 10))
            self.screen.blit(self.small_font.render(label, True, TEXT_COLOR), (fx + 18, fy - 1))
            fy += 16

    # ── Loop principal ────────────────────────────────────────────────────────
    def run(self):
        while self.running:
            current_time = pygame.time.get_ticks()
            cx = self.width // 2

            # ── Botões de MENU ────────────────────────────────────────────
            btn_mack      = Botao(cx - 150, 250, 300, 50, "MACKENZIE / HIGIENÓPOLIS")
            btn_itaim     = Botao(cx - 150, 320, 300, 50, "ITAIM BIBI")
            btn_pinheiros = Botao(cx - 150, 390, 300, 50, "PINHEIROS")

            # ── ROW 1 — posições dos botões ───────────────────────────────
            # VOLTAR
            btn_v   = Botao(10,        Y_R1_BTN, 80, H_R1, "◀ VOLTAR",  (200, 200, 200))

            # FROTA (entregadores)
            btn_e_m = Botao(110,       Y_R1_BTN, 32, H_R1, "-",         (255, 200, 200))
            btn_e_p = Botao(147,       Y_R1_BTN, 32, H_R1, "+",         (200, 255, 200))

            # LOJAS (centralizadas)
            btn_l_m = Botao(cx -  80,  Y_R1_BTN, 32, H_R1, "-",         (255, 200, 200))
            btn_l_p = Botao(cx -  44,  Y_R1_BTN, 32, H_R1, "+",         (200, 255, 200))

            # PEDIDOS
            btn_p_m = Botao(cx + 100,  Y_R1_BTN, 32, H_R1, "-",         (255, 200, 200))
            btn_p_p = Botao(cx + 136,  Y_R1_BTN, 32, H_R1, "+",         (200, 255, 200))

            # TIME SCALE (canto direito)
            btn_t_m = Botao(self.width - 200, Y_R1_BTN, 40, H_R1, "<<", (220, 220, 255))
            btn_t_p = Botao(self.width -  52, Y_R1_BTN, 40, H_R1, ">>", (220, 220, 255))

            # ── ROW 2 — posições dos botões ───────────────────────────────
            # TRÂNSITO
            btn_tr_m = Botao(110,  Y_R2_BTN, 32, H_R2, "-",             (255, 200, 200))
            btn_tr_p = Botao(147,  Y_R2_BTN, 32, H_R2, "+",             (200, 255, 200))

            # ACIDENTES
            btn_ac_m = Botao(380,  Y_R2_BTN, 32, H_R2, "-",             (255, 200, 200))
            btn_ac_p = Botao(417,  Y_R2_BTN, 32, H_R2, "+",             (200, 255, 200))

            # CHUVA (checkbox)
            chuva_cor = (180, 200, 255) if self.chuva_ativa else (220, 220, 220)
            txt_chuva = "[✓] ATIVA"  if self.chuva_ativa else "[ ] INATIVA"
            btn_chuva = Botao(600, Y_R2_BTN, 130, H_R2, txt_chuva, chuva_cor)

            # AUTO (checkbox)
            auto_cor  = (180, 255, 180) if self.auto_mode else (220, 220, 220)
            txt_auto  = "[✓] LIGADO" if self.auto_mode  else "[ ] DESLIG."
            btn_auto  = Botao(755, Y_R2_BTN, 130, H_R2, txt_auto,  auto_cor)

            # ── Fundo ─────────────────────────────────────────────────────
            self.screen.fill((220, 228, 235) if self.chuva_ativa else BG_COLOR)

            # ── Eventos ───────────────────────────────────────────────────
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False

                elif ev.type == pygame.VIDEORESIZE:
                    self.width, self.height = ev.w, ev.h
                    self.screen    = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
                    self.rain_surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
                    self._recalcular_mapa()

                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if self.state == "MENU":
                        if btn_mack.rect.collidepoint(ev.pos):
                            self.setup_map("mapa_mackenzie.graphml")
                        if btn_itaim.rect.collidepoint(ev.pos):
                            self.setup_map("mapa_itaim.graphml")
                        if btn_pinheiros.rect.collidepoint(ev.pos):
                            self.setup_map("mapa_pinheiros.graphml")

                    elif self.state == "SIM":
                        if btn_v.rect.collidepoint(ev.pos):
                            self.state = "MENU"

                        # Frota
                        if btn_e_p.rect.collidepoint(ev.pos):
                            if len(self.ativos) < len(self.db_entregadores):
                                d = self.db_entregadores[len(self.ativos)]
                                self.ativos.append(
                                    Entregador(d, random.choice(self.nodes), self.pos_map))
                        if btn_e_m.rect.collidepoint(ev.pos) and self.ativos:
                            self.ativos.pop()

                        # Lojas
                        if btn_l_p.rect.collidepoint(ev.pos):
                            if self.qtd_lojas_visiveis < len(self.lojas_no_mapa):
                                self.qtd_lojas_visiveis += 1
                        if btn_l_m.rect.collidepoint(ev.pos) and self.qtd_lojas_visiveis > 1:
                            self.qtd_lojas_visiveis -= 1

                        # Pedidos
                        if btn_p_p.rect.collidepoint(ev.pos):
                            self.pedidos_pendentes += 1
                        if btn_p_m.rect.collidepoint(ev.pos) and self.pedidos_pendentes > 0:
                            self.pedidos_pendentes -= 1

                        # Time scale
                        if btn_t_p.rect.collidepoint(ev.pos):
                            self.time_scale = min(100, self.time_scale + 2)
                        if btn_t_m.rect.collidepoint(ev.pos):
                            self.time_scale = max(1,   self.time_scale - 2)

                        # Trânsito
                        if btn_tr_p.rect.collidepoint(ev.pos):
                            self._adicionar_intemperies_aresta(
                                self.edge_transito, self.nivel_transito + 1)
                            self.nivel_transito = len(self.edge_transito)
                        if btn_tr_m.rect.collidepoint(ev.pos) and self.nivel_transito > 0:
                            self._adicionar_intemperies_aresta(
                                self.edge_transito, self.nivel_transito - 1)
                            self.nivel_transito = len(self.edge_transito)

                        # Acidentes
                        if btn_ac_p.rect.collidepoint(ev.pos):
                            self._adicionar_intemperies_aresta(
                                self.edge_acidente, self.nivel_acidentes + 1)
                            self.nivel_acidentes = len(self.edge_acidente)
                        if btn_ac_m.rect.collidepoint(ev.pos) and self.nivel_acidentes > 0:
                            self._adicionar_intemperies_aresta(
                                self.edge_acidente, self.nivel_acidentes - 1)
                            self.nivel_acidentes = len(self.edge_acidente)

                        # Chuva / Auto
                        if btn_chuva.rect.collidepoint(ev.pos):
                            self.chuva_ativa = not self.chuva_ativa
                        if btn_auto.rect.collidepoint(ev.pos):
                            self.auto_mode = not self.auto_mode
                            if self.auto_mode:
                                self._auto_last_chuva    = current_time
                                self._auto_last_transito = current_time
                                self._auto_last_acidente = current_time

            # ── Renderização ──────────────────────────────────────────────
            if self.state == "MENU":
                txt = self.title_font.render("SIMULADOR LOGÍSTICA URBANA", True, TEXT_COLOR)
                self.screen.blit(txt, (cx - txt.get_width()//2, 150))
                btn_mack.draw(self.screen, self.font)
                btn_itaim.draw(self.screen, self.font)
                btn_pinheiros.draw(self.screen, self.font)

            elif self.state == "SIM":
                if self.auto_mode:
                    self._update_auto(current_time)

                # Mapa e entidades
                self._draw_edges()

                for l in self.lojas_no_mapa[:self.qtd_lojas_visiveis]:
                    nid = l['node_id']
                    pygame.draw.rect(self.screen, (60, 60, 60),
                                     (*self.pos_map[nid], 12, 12))
                    lbl = pygame.font.SysFont("arial", 10).render(
                        l['nome'][:15], True, (100, 100, 100))
                    self.screen.blit(lbl,
                                     (self.pos_map[nid][0]-10, self.pos_map[nid][1]-15))

                self.despachar()

                mod_carro = 0.60 if self.chuva_ativa else 1.0
                mod_moto  = 0.60 if self.chuva_ativa else 1.0

                for e in self.ativos:
                    e.update(self.G, self.pos_map, self.edge_speed_kph,
                             self.meters_per_pixel, self.time_scale, current_time,
                             mod_carro, mod_moto,
                             self.edge_transito, self.edge_acidente,
                             self.chuva_ativa, self.nivel_transito, self.nivel_acidentes)
                    e.draw(self.screen, self.pos_map)

                self._draw_speed_legend()

                if self.chuva_ativa:
                    self._update_chuva()
                    self._draw_chuva()

                # ── Painel UI (desenhado por cima do mapa) ────────────────
                pygame.draw.rect(self.screen, UI_PANEL,
                                 (0, 0, self.width, UI_PANEL_HEIGHT))
                pygame.draw.line(self.screen, (180, 175, 165),
                                 (0, UI_PANEL_HEIGHT), (self.width, UI_PANEL_HEIGHT), 2)

                # Linha separadora entre Row 1 e Row 2
                sep_y = Y_R2_LBL - 4
                pygame.draw.line(self.screen, (200, 196, 185),
                                 (10, sep_y), (self.width - 10, sep_y), 1)

                # Desenhar botões
                for btn in [btn_v, btn_e_m, btn_e_p, btn_l_m, btn_l_p,
                             btn_p_m, btn_p_p, btn_t_m, btn_t_p,
                             btn_tr_m, btn_tr_p, btn_ac_m, btn_ac_p,
                             btn_chuva, btn_auto]:
                    btn.draw(self.screen, self.font)

                # ── Labels acima de cada grupo de botões ──────────────────
                def lbl_acima(texto, cx_pos, y_pos, fonte=None, cor=TEXT_COLOR):
                    f = fonte or self.font
                    s = f.render(texto, True, cor)
                    self.screen.blit(s, (int(cx_pos - s.get_width() / 2), y_pos))

                # — Row 1 (y = Y_R1_LBL = 8) —
                frota_cx   = (btn_e_m.rect.left  + btn_e_p.rect.right)  // 2
                lojas_cx   = (btn_l_m.rect.left  + btn_l_p.rect.right)  // 2
                pedidos_cx = (btn_p_m.rect.left  + btn_p_p.rect.right)  // 2
                time_cx    = (btn_t_m.rect.left  + btn_t_p.rect.right)  // 2

                lbl_acima(f"FROTA: {len(self.ativos)}",
                          frota_cx,   Y_R1_LBL)
                lbl_acima(f"LOJAS: {self.qtd_lojas_visiveis}",
                          lojas_cx,   Y_R1_LBL)
                lbl_acima(f"PEDIDOS: {self.pedidos_pendentes}",
                          pedidos_cx, Y_R1_LBL)
                lbl_acima(f"TIME: {self.time_scale:.0f}x",
                          time_cx,    Y_R1_LBL,
                          fonte=self.medium_font, cor=(50, 50, 180))

                # — Row 2 (y = Y_R2_LBL = 82) —
                transito_cx = (btn_tr_m.rect.left + btn_tr_p.rect.right) // 2
                acidente_cx = (btn_ac_m.rect.left + btn_ac_p.rect.right) // 2

                lbl_acima(f"TRÂNSITO: {self.nivel_transito}",
                          transito_cx,             Y_R2_LBL)
                lbl_acima(f"ACIDENTES: {self.nivel_acidentes}",
                          acidente_cx,             Y_R2_LBL)
                lbl_acima("CHUVA",
                          btn_chuva.rect.centerx,  Y_R2_LBL)
                lbl_acima("MODO AUTO",
                          btn_auto.rect.centerx,   Y_R2_LBL)

                # Escala
                self.screen.blit(
                    self.small_font.render(
                        f"Escala: {self.meters_per_pixel:.2f} m/px", True, (120, 120, 120)),
                    (self.width - 160, self.height - 18))

                # Legenda de intempéries (canto inferior esquerdo)
                lx, ly = 10, self.height - 120
                pygame.draw.rect(self.screen, (255, 165, 0), (lx, ly, 14, 10))
                self.screen.blit(
                    self.small_font.render("▲ Trânsito na rua", True, TEXT_COLOR),
                    (lx + 18, ly - 1))
                ly += 16
                pygame.draw.rect(self.screen, (220, 20, 20), (lx, ly, 14, 10))
                self.screen.blit(
                    self.small_font.render("✖ Acidente na rua", True, TEXT_COLOR),
                    (lx + 18, ly - 1))

            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()


if __name__ == "__main__":
    Simulador().run()