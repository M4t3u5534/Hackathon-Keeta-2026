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

# Fator de tortuosidade urbana: converte distância em linha reta → distância real em rua
# Valor típico para malha urbana densa (~35% mais longo que linha reta)
TORTUOSITY_FACTOR = 1.35

# Painel maior para acomodar labels acima dos botões (2 linhas)
UI_PANEL_HEIGHT = 155

# Posições internas do painel — Row 1 e Row 2
Y_R1_LBL, Y_R1_BTN, H_R1 = 8,   28, 40   # label y, botão y, altura do botão
Y_R2_LBL, Y_R2_BTN, H_R2 = 82, 100, 38

# ─── PRECIFICAÇÃO (valores reais iFood / Keeta) ────────────────────────────────
# Moto
PRECO_BASE_MOTO    = 2.00   # R$ taxa base fixa (moto)
PRECO_KM_MOTO      = 1.50   # R$ / km  (moto)
PRECO_MINIMO_MOTO  = 7.50   # R$ mínimo garantido (moto)
# Carro
PRECO_BASE_CARRO   = 3.00   # R$ taxa base fixa (carro)
PRECO_KM_CARRO     = 2.00   # R$ / km  (carro)
PRECO_MINIMO_CARRO = 7.50   # R$ mínimo garantido (carro)
# Bike — mínimo corrigido para 7.50 (mesmo padrão dos demais)
PRECO_BASE_BIKE    = 1.50   # R$ taxa base fixa (bike)
PRECO_KM_BIKE      = 0.80   # R$ / km  (bike)
PRECO_MINIMO_BIKE  = 7.50   # R$ mínimo garantido (bike) — CORRIGIDO de 4.00 para 7.50
# Ajustes dinâmicos
RAIN_BONUS         = 0.25   # +25 % de bônus em caso de chuva
HOLDING_BONUS      = 0.30   # +30% de bônus para pedidos aceitos via holding time

# ─── PROBABILIDADE DE MACHUCADO POR FRAME (enquanto em aresta de acidente) ────
INJURY_PROB_MOTO  = 1 #0.0012   # ~7% por segundo real a 60fps
INJURY_PROB_CARRO = 0.0005   # ~3% por segundo real a 60fps
INJURY_PROB_BIKE  = 0.0018   # ~10% por segundo real a 60fps (bike mais perigosa)
INJURY_MIN_S      = 5.0      # mínimo de segundos parado lesionado
INJURY_MAX_S      = 18.0     # máximo de segundos parado lesionado

# ─── HOLDING TIME ─────────────────────────────────────────────────────────────
HOLDING_MIN_S     = 5.0      # tempo mínimo de espera (segundos reais)
HOLDING_MAX_S     = 15.0     # tempo máximo de espera (segundos reais)

# ─── REDUÇÃO DE FROTA NA CHUVA ────────────────────────────────────────────────
CHUVA_REDUCAO_FROTA = 0.20   # 20% dos entregadores não-entregando ficam de fora na chuva

# ─── LOG ───────────────────────────────────────────────────────────────────────
log_lock = threading.Lock()
LOG_FILE  = "log_entregas.csv"


def calcular_preco(dist_m, tipo_veiculo, chuva_ativa, holding_bonus=False):
    """Calcula o preço de um pedido no modelo real de food delivery.
    Todos os veículos têm preço mínimo garantido de R$ 7,50.
    """
    dist_km = dist_m / 1000.0
    if tipo_veiculo == "carro":
        preco = PRECO_BASE_CARRO + dist_km * PRECO_KM_CARRO
        preco = max(preco, PRECO_MINIMO_CARRO)
    elif tipo_veiculo == "bike":
        preco = PRECO_BASE_BIKE + dist_km * PRECO_KM_BIKE
        preco = max(preco, PRECO_MINIMO_BIKE)   # mínimo 7.50
    else:   # moto (padrão)
        preco = PRECO_BASE_MOTO + dist_km * PRECO_KM_MOTO
        preco = max(preco, PRECO_MINIMO_MOTO)
    if chuva_ativa:
        preco *= (1.0 + RAIN_BONUS)
    if holding_bonus:
        preco *= (1.0 + HOLDING_BONUS)
    return preco


def registrar_entrega_final(id_e, tipo_veiculo, id_r,
                             delta_t_s, preco_pedido,
                             total_corrida, pedidos_corrida,
                             chuva_ativa, nivel_transito, nivel_acidente,
                             time_scale,
                             atraso_s=0.0,
                             machucado=False,
                             estornado=False):
    """
    Grava o status final ENTREGUE/ESTORNADO com todas as métricas no CSV.
    Coluna ATRASO: positivo = atrasado (s), negativo = adiantado (s).
    """
    def _write():
        with log_lock:
            existe = os.path.exists(LOG_FILE)
            with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if not existe:
                    w.writerow([
                        "Timestamp", "Entregador_ID", "Tipo_Veiculo",
                        "Restaurante_ID", "Status_Final",
                        "Tempo_Entrega_s", "Preco_Pedido_R$",
                        "Total_Corrida_R$", "Pedidos_na_Corrida",
                        "Time_Scale", "Intemperismo",
                        "Atraso_s"
                    ])

                intemp = []
                if chuva_ativa:        intemp.append("Chuva")
                if nivel_transito > 0: intemp.append("Trânsito")
                if nivel_acidente > 0: intemp.append("Acidente")
                if machucado:          intemp.append("Machucado")

                total_str  = f"R$ {total_corrida:.2f}" if total_corrida is not None else "—"
                atraso_str = f"{atraso_s:+.1f}s"   # +3.5s ou -1.2s
                status     = "ESTORNADO" if estornado else "ENTREGUE"
                preco_str  = "R$ 0.00" if estornado else f"R$ {preco_pedido:.2f}"

                w.writerow([
                    time.strftime("%H:%M:%S"),
                    id_e,
                    tipo_veiculo,
                    id_r,
                    status,
                    round(delta_t_s, 1),
                    preco_str,
                    total_str,
                    pedidos_corrida,
                    f"{time_scale:.0f}x",
                    ", ".join(intemp) if intemp else "Nenhum",
                    atraso_str
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


# ─── AMBULÂNCIA ───────────────────────────────────────────────────────────────
class Ambulancia:
    """
    Animação de ambulância que vem de fora do mapa, entra pelas ruas,
    segue a rota até o local do acidente, para brevemente e some.
    Quando active=False a animação terminou.
    """

    def __init__(self, start_pos, target_pos, pos_map, G, edge_speed_kph,
                 meters_per_pixel, time_scale):
        self.start_pos        = start_pos
        self.target_pos       = target_pos
        self.pos_map          = pos_map
        self.G                = G
        self.edge_speed_kph   = edge_speed_kph
        self.meters_per_pixel = meters_per_pixel
        # time_scale inicial — usado apenas como fallback; update() recebe o
        # valor atual a cada frame para reagir a mudanças em tempo real.
        self.time_scale       = time_scale
        self.x, self.y        = float(start_pos[0]), float(start_pos[1])

        # target_node permanece None — o path é quem dita o movimento
        self.target_node      = None
        self.path             = []
        self.active           = True

        # Fase: "going" → chegou ao local | "arrived" → esperando
        self._phase           = "going"
        self._arrived_timer   = 0     # ms simulados acumulados na fase "arrived"
        self._arrived_wait    = 700   # ms reais de pausa no local do acidente
        self._siren_tick      = 0     # contador de frames para piscar sirene

        # ── Encontra nó mais próximo do DESTINO (acidente) ───────────────────
        closest_node = None
        min_dist     = float('inf')
        for node, (nx_, ny_) in pos_map.items():
            d = math.hypot(nx_ - target_pos[0], ny_ - target_pos[1])
            if d < min_dist:
                min_dist     = d
                closest_node = node

        if closest_node is None:
            return

        # ── Encontra nó mais próximo do ponto de ENTRADA (borda do mapa) ─────
        start_node     = None
        min_dist_start = float('inf')
        for node, (nx_, ny_) in pos_map.items():
            d = math.hypot(nx_ - start_pos[0], ny_ - start_pos[1])
            if d < min_dist_start:
                min_dist_start = d
                start_node     = node

        try:
            # Path completo incluindo start_node — sem o [1:]
            self.path = nx.shortest_path(
                G, start_node, closest_node, weight='length'
            )
        except Exception:
            self.path = [closest_node]

    # ─────────────────────────────────────────────────────────────────────────
    def update(self, time_scale=None):
        """
        Atualiza a posição da ambulância.
        Recebe time_scale como parâmetro para reagir a mudanças em tempo real.
        """
        if not self.active:
            return

        # Usa o time_scale passado no frame atual; fallback para o inicial
        ts = time_scale if time_scale is not None else self.time_scale

        self._siren_tick += 1

        if self._phase == "arrived":
            # Acumula ms proporcionais ao time_scale para a pausa escalar junto
            self._arrived_timer += 16 * ts
            if self._arrived_timer >= self._arrived_wait:
                self.active = False
            return

        # Velocidade da ambulância: 40 km/h com sirene
        speed_kph      = 40.0
        speed_mps      = speed_kph * (1000.0 / 3600.0)
        dist_per_frame = (speed_mps / self.meters_per_pixel / 60) * ts

        while dist_per_frame > 0:
            if not self.target_node:
                if self.path:
                    self.target_node = self.path.pop(0)
                else:
                    self._phase    = "arrived"
                    self.x, self.y = self.target_pos
                    return

            tx, ty = self.pos_map.get(
                self.target_node,
                (self.target_pos[0], self.target_pos[1])
            )
            dx, dy       = tx - self.x, ty - self.y
            dist_to_node = math.hypot(dx, dy)

            if dist_to_node <= dist_per_frame:
                self.x, self.y   = tx, ty
                self.target_node = None
                dist_per_frame  -= dist_to_node
            else:
                self.x += (dx / dist_to_node) * dist_per_frame
                self.y += (dy / dist_to_node) * dist_per_frame
                dist_per_frame   = 0

        if self.target_node is None and not self.path:
            self._phase    = "arrived"
            self.x, self.y = self.target_pos

    # ─────────────────────────────────────────────────────────────────────────
    def draw(self, surf):
        if not self.active:
            return

        cx, cy = int(self.x), int(self.y)
        W, H   = 30, 16

        # ── Rodas ─────────────────────────────────────────────────────────────
        wheel_col = (40, 40, 40)
        for wx, wy in [
            (cx - W // 2 - 2, cy - H // 2),
            (cx + W // 2 - 2, cy - H // 2),
            (cx - W // 2 - 2, cy + H // 2 - 4),
            (cx + W // 2 - 2, cy + H // 2 - 4),
        ]:
            pygame.draw.rect(surf, wheel_col, (wx, wy, 4, 4), border_radius=1)

        # ── Corpo principal ───────────────────────────────────────────────────
        body = pygame.Rect(cx - W // 2, cy - H // 2, W, H)
        pygame.draw.rect(surf, (250, 250, 250), body, border_radius=3)

        # ── Faixa azul no topo ────────────────────────────────────────────────
        stripe = pygame.Rect(cx - W // 2, cy - H // 2, W, 5)
        pygame.draw.rect(surf, (20, 90, 200), stripe, border_radius=3)

        # ── Para-brisa / cabine ───────────────────────────────────────────────
        pygame.draw.rect(
            surf, (80, 110, 160),
            (cx - W // 2 + 2, cy - H // 2 + 5, 7, H - 6),
            border_radius=1
        )

        # ── Cruz vermelha ─────────────────────────────────────────────────────
        qx = cx + 6
        pygame.draw.rect(surf, (215, 20, 20), (qx - 5, cy + 1, 10, 3))
        pygame.draw.rect(surf, (215, 20, 20), (qx - 1, cy - 3,  3, 9))

        # ── Contorno vermelho ─────────────────────────────────────────────────
        pygame.draw.rect(surf, (180, 10, 10), body, 1, border_radius=3)

        # ── Sirenes piscantes ─────────────────────────────────────────────────
        fase     = (self._siren_tick // 8) % 2
        col_azul = (50, 140, 255) if fase == 0 else (20,  50, 130)
        col_verm = (255,  50, 50) if fase == 1 else (130, 20,  20)
        pygame.draw.circle(surf, col_azul, (cx - 7, cy - H // 2 + 2), 3)
        pygame.draw.circle(surf, col_verm, (cx,     cy - H // 2 + 2), 3)


# ─── ENTREGADOR ────────────────────────────────────────────────────────────────
class Entregador:
    """
    Sistema multi-parada: coleta pedidos em até cap_max restaurantes
    e entrega nos respectivos destinos antes de voltar ao estado IDLE.

    Fila de paradas (stop_queue): lista de dicts
        {'node': int, 'phase': 'SHOP'|'DEST', 'job': {...}}

    Estados: IDLE | MOVING | WAITING | HOLDING

    Timer de entrega:
        delivery_start  : ticks quando entregador recolheu o 1º pedido (SHOP)
        ideal_time_s    : tempo ideal real (s) calculado no despacho sem intemperismos,
                          usando TORTUOSITY_FACTOR e velocidade efetiva da via.

    Machucado:
        machucado       : True ao se lesionar
        jobs_to_restore : TODOS os jobs restantes na fila (SHOP + DEST) para estorno
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
        self.state       = "IDLE"      # IDLE | MOVING | WAITING | HOLDING
        self.target_node = None
        self.path        = []
        self.stop_queue  = []
        self.wait_start  = 0

        # Holding Time
        self.holding_start          = 0
        self.holding_duration       = 0
        self.holding_hotspot_center = None

        # Rastreamento de corrida
        self._corrida_jobs_total      = 0
        self._corrida_delivered_count = 0
        self._corrida_total_preco     = 0.0

        # Timer de entrega
        self.delivery_start = None   # ticks (set ao pegar no 1.º SHOP)
        self.ideal_time_s   = None   # segundos reais ideais para a corrida

        # Estado de lesão
        self.machucado        = False
        self.machucado_until  = 0
        self.machucado_ocorreu = False
        # jobs_to_restore: TODOS os jobs da fila quando ocorre a lesão (SHOP + DEST)
        self.jobs_to_restore  = []

        # Fonte do timer (criada uma vez)
        self._timer_font = pygame.font.SysFont("segoeui", 11, bold=True)

    def _encerrar_corrida(self):
        """Limpa o timer e reinicia contadores de corrida."""
        self.delivery_start    = None
        self.ideal_time_s      = None
        self.machucado_ocorreu = False

    def update(self, G, pos_map, edge_speed_kph, meters_per_pixel, time_scale,
               current_time, mod_carro, mod_moto, mod_bike,
               edge_transito, edge_acidente,
               chuva_ativa, nivel_transito, nivel_acidentes,
               hotspot_ativo=False, hotspot_centers=None):

        # ── MACHUCADO: imobilizado ────────────────────────────────────────────
        # Nota: a remoção definitiva do entregador é feita pelo Simulador.
        # Aqui apenas bloqueamos qualquer processamento adicional.
        if self.machucado:
            return   # imobilizado — aguarda remoção pelo Simulador

        # ── HOLDING: aguardando novos pedidos em hotspot ──────────────────────
        if self.state == "HOLDING":
            if current_time - self.holding_start >= self.holding_duration:
                self.state                    = "IDLE"
                self.holding_start            = 0
                self.holding_duration         = 0
                self.holding_hotspot_center   = None
            return

        # ── WAITING: aguardando na parada atual ──────────────────────────────
        if self.state == "WAITING":
            if current_time - self.wait_start < (10.0 / time_scale) * 1000:
                return

            if not self.stop_queue:
                self.state       = "IDLE"
                self.carga_atual = 0
                self._encerrar_corrida()
                return

            stop = self.stop_queue.pop(0)

            if stop['phase'] == "DEST":
                job      = stop['job']
                delta_t  = (current_time - job['accept_time']) / 1000.0
                preco    = calcular_preco(job['dist_m'], self.tipo,
                                          chuva_ativa, job.get('holding_bonus', False))

                # Calcula atraso usando o horário de coleta no SHOP
                pickup_time      = job.get('pickup_time', job['accept_time'])
                actual_delivery_s = (current_time - pickup_time) / 1000.0
                ideal_delivery_s  = job.get('ideal_delivery_s', None)
                atraso_s = actual_delivery_s - ideal_delivery_s if (ideal_delivery_s and ideal_delivery_s > 0) else 0.0

                self._corrida_delivered_count += 1
                self._corrida_total_preco     += preco

                total_corrida = (self._corrida_total_preco
                                 if self._corrida_delivered_count >= self._corrida_jobs_total
                                 else None)

                registrar_entrega_final(
                    id_e            = self.id,
                    tipo_veiculo    = self.tipo,
                    id_r            = job['loja_id'],
                    delta_t_s       = delta_t,
                    preco_pedido    = preco,
                    total_corrida   = total_corrida,
                    pedidos_corrida = self._corrida_jobs_total,
                    chuva_ativa     = chuva_ativa,
                    nivel_transito  = nivel_transito,
                    nivel_acidente  = nivel_acidentes,
                    time_scale      = time_scale,
                    atraso_s        = atraso_s,
                    machucado       = self.machucado_ocorreu,
                )
                self.carga_atual = max(0, self.carga_atual - 1)

            else:
                # SHOP: coleta realizada — marca horário de pickup
                job = stop['job']
                job['pickup_time'] = current_time
                if self.delivery_start is None:
                    self.delivery_start = current_time

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
                self._encerrar_corrida()
            return

        # ── LESÃO POR ACIDENTE (verifica antes de mover) ─────────────────────
        if self.state == "MOVING" and self.target_node and not self.machucado:
            ek  = (self.node, self.target_node)
            ekr = (self.target_node, self.node)
            if ek in edge_acidente or ekr in edge_acidente:
                prob = (INJURY_PROB_BIKE if self.tipo == "bike"
                        else INJURY_PROB_CARRO if self.tipo == "carro"
                        else INJURY_PROB_MOTO)
                if random.random() < prob:
                    self.machucado        = True
                    self.machucado_until  = current_time + int(
                        random.uniform(INJURY_MIN_S, INJURY_MAX_S) * 1000)
                    self.machucado_ocorreu = True
                    # Preserva TODOS os jobs restantes (SHOP e DEST) para estorno
                    self.jobs_to_restore  = [s['job'] for s in self.stop_queue]
                    return

        # ── Cálculo de velocidade ─────────────────────────────────────────────
        ref_node   = self.target_node if self.target_node else self.node
        base_speed = min(self.vel_kph,
                         edge_speed_kph.get((self.node, ref_node), DEFAULT_ROAD_SPEED_KPH))
        mod = mod_bike if self.tipo == "bike" else mod_carro if self.tipo == "carro" else mod_moto

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
                            if hotspot_ativo and hotspot_centers and random.random() < 0.80:
                                px, py = pos_map.get(self.node, (self.x, self.y))
                                nearest_hc = min(
                                    hotspot_centers,
                                    key=lambda c: math.hypot(c[0] - px, c[1] - py))
                                def _dist_hs(n_node):
                                    npx, npy = pos_map.get(n_node, (px, py))
                                    return math.hypot(npx - nearest_hc[0], npy - nearest_hc[1])
                                self.target_node = min(viz, key=_dist_hs)
                            else:
                                self.target_node = random.choice(viz)
                        else:
                            break
                    else:
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

    def start_holding(self, duration_ms, hotspot_center):
        """Inicia o estado de holding time."""
        self.state                  = "HOLDING"
        self.holding_start          = pygame.time.get_ticks()
        self.holding_duration       = duration_ms
        self.holding_hotspot_center = hotspot_center

    # ── Desenho ──────────────────────────────────────────────────────────────
    def draw(self, surf, pos_map, current_time=0):
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
        elif self.tipo == "bike":
            # Triângulo
            points = [(pos[0], pos[1]-7), (pos[0]-6, pos[1]+4), (pos[0]+6, pos[1]+4)]
            pygame.draw.polygon(surf, self.color, points)
            pygame.draw.polygon(surf, (255, 255, 255), points, 1)
        else:  # moto
            pygame.draw.circle(surf, self.color, pos, 6)
            pygame.draw.circle(surf, (255, 255, 255), pos, 6, 1)

        # ── HOLDING TIME: badge roxo ───────────────────────────────────────────
        if self.state == "HOLDING":
            badge_color = (128, 0, 128)
            txt_surf    = self._timer_font.render("HOLDING", True, (255, 255, 255))
            pad  = 3
            bw   = txt_surf.get_width()  + pad * 2
            bh   = txt_surf.get_height() + pad * 2
            bx   = pos[0] - bw // 2
            by   = pos[1] - 30 - bh
            pygame.draw.rect(surf, badge_color, (bx, by, bw, bh), border_radius=4)
            surf.blit(txt_surf, (bx + pad, by + pad))

        # ── TIMER de entrega ──────────────────────────────────────────────────
        if self.delivery_start is not None and self.ideal_time_s is not None:
            elapsed_s   = (current_time - self.delivery_start) / 1000.0
            remaining_s = self.ideal_time_s - elapsed_s

            if remaining_s >= 0:
                badge_color = (30, 160, 30)    # verde = dentro do prazo
                mins        = int(remaining_s) // 60
                secs        = int(remaining_s) % 60
                badge_txt   = f"+{mins}:{secs:02d}"
            else:
                badge_color = (200, 20, 20)    # vermelho = atrasado
                abs_s       = int(abs(remaining_s))
                mins        = abs_s // 60
                secs        = abs_s % 60
                badge_txt   = f"-{mins}:{secs:02d}"

            txt_surf = self._timer_font.render(badge_txt, True, (255, 255, 255))
            pad  = 3
            bw   = txt_surf.get_width()  + pad * 2
            bh   = txt_surf.get_height() + pad * 2
            bx   = pos[0] - bw // 2
            by   = pos[1] - 30 - bh
            pygame.draw.rect(surf, badge_color, (bx, by, bw, bh), border_radius=4)
            surf.blit(txt_surf, (bx + pad, by + pad))


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
        self._auto_chuva_interval_base      = 25_000
        self._auto_transito_interval_base   = 18_000
        self._auto_acidente_interval_base   = 30_000
        self._auto_pedido_interval_base     = 12_000   # auto-adiciona pedidos
        self._auto_entregador_interval_base = 20_000   # auto-adiciona entregador se necessário
        self._auto_last_chuva      = 0
        self._auto_last_transito   = 0
        self._auto_last_acidente   = 0
        self._auto_last_pedido     = 0
        self._auto_last_entregador = 0

        # ── HotSpot ──────────────────────────────────────────────────────────
        self.hotspot_ativo  = False
        self._hotspot_surf  = None

        # ── Holding Time ─────────────────────────────────────────────────────
        self.holding_ativo  = False

        # ── Ambulâncias ──────────────────────────────────────────────────────
        self.ambulancias = []

        # ── Posições de acidente visual (cruz vermelha) ───────────────────────
        # Cada item: {'x': float, 'y': float, 'ambulancia': Ambulancia}
        # A cruz permanece enquanto ambulancia.active == True
        self.acidentes_visuais = []

        # ── Controle de entregadores na chuva ────────────────────────────────
        # Guarda os entregadores removidos temporariamente durante a chuva
        self.entregadores_ativos_original = []
        self.chuva_anterior               = False

    # ── HotSpot: calcula centros (até 3 lojas visíveis) ──────────────────────
    def _get_hotspot_centers(self):
        centers = []
        lojas   = self.lojas_no_mapa[:self.qtd_lojas_visiveis]
        for loja in lojas[:3]:
            nid = loja.get('node_id')
            if nid and nid in self.pos_map:
                centers.append(self.pos_map[nid])
        return centers

    # ── HotSpot: desenha círculos semi-transparentes ──────────────────────────
    def _draw_hotspots(self):
        centers = self._get_hotspot_centers()
        if not centers:
            return

        RADIUS     = 70
        FILL_ALPHA = 55
        RING_ALPHA = 200
        FILL_COLOR = (220, 30, 30)
        RING_COLOR = (200, 10, 10)

        if (self._hotspot_surf is None
                or self._hotspot_surf.get_width()  != self.width
                or self._hotspot_surf.get_height() != self.height):
            self._hotspot_surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

        self._hotspot_surf.fill((0, 0, 0, 0))
        for cx, cy in centers:
            icx, icy = int(cx), int(cy)
            pygame.draw.circle(self._hotspot_surf,
                               (*FILL_COLOR, FILL_ALPHA), (icx, icy), RADIUS)
            pygame.draw.circle(self._hotspot_surf,
                               (*RING_COLOR, RING_ALPHA), (icx, icy), RADIUS, 3)

        self.screen.blit(self._hotspot_surf, (0, 0))

    # ── Cruz de acidente visual ───────────────────────────────────────────────
    def _draw_acidente_cruz(self, x, y):
        """
        Desenha um símbolo de '+' vermelho com borda branca no local do acidente.
        Permanece visível enquanto a ambulância está a caminho.
        """
        px, py = int(x), int(y)
        arm   = 10   # metade do comprimento do braço
        thick = 5    # espessura do braço
        # Borda branca (área ligeiramente maior)
        pygame.draw.rect(self.screen, (255, 255, 255),
                         (px - arm - 2, py - thick // 2 - 2, (arm + 2) * 2, thick + 4))
        pygame.draw.rect(self.screen, (255, 255, 255),
                         (px - thick // 2 - 2, py - arm - 2, thick + 4, (arm + 2) * 2))
        # Cruz vermelha
        pygame.draw.rect(self.screen, (220, 20, 20),
                         (px - arm, py - thick // 2, arm * 2, thick))
        pygame.draw.rect(self.screen, (220, 20, 20),
                         (px - thick // 2, py - arm, thick, arm * 2))

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
            self._hotspot_surf = None

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

            self.ativos              = []
            self.ambulancias         = []
            self.acidentes_visuais   = []
            self.edge_transito       = set()
            self.edge_acidente       = set()
            self.nivel_transito      = 0
            self.nivel_acidentes     = 0
            self._hotspot_surf       = None
            self.entregadores_ativos_original = []
            self.chuva_anterior      = False
            self.state               = "SIM"
        except Exception as e:
            print(f"Erro ao carregar mapa: {e}")

    def to_px(self, lon, lat):
        pad_top  = UI_PANEL_HEIGHT + 10
        pad_side = 80
        pad_bot  = 60
        x = pad_side + (lon - self.min_x) / (self.max_x - self.min_x) * (self.width  - 2 * pad_side)
        y = pad_top  + (self.max_y - lat) / (self.max_y - self.min_y)  * (self.height - pad_top - pad_bot)
        return x, y

    # ── Remoção de entregador machucado ───────────────────────────────────────
    def _remover_entregador_machucado(self, entregador, current_time):
        """
        Remove entregador machucado:
        1. Estorna TODOS os jobs pendentes (SHOP e DEST) no log.
        2. Restaura pedidos ao pool de pendentes.
        3. Remove da lista de ativos.
        4. Cria ambulância e registra posição do acidente para exibir a cruz '+'.
        """
        # Estorna todos os jobs na fila (coletados ou não)
        for job in entregador.jobs_to_restore:
            self.pedidos_pendentes += 1
            registrar_entrega_final(
                id_e            = entregador.id,
                tipo_veiculo    = entregador.tipo,
                id_r            = job.get('loja_id', '?'),
                delta_t_s       = 0,
                preco_pedido    = 0,
                total_corrida   = None,
                pedidos_corrida = 0,
                chuva_ativa     = self.chuva_ativa,
                nivel_transito  = self.nivel_transito,
                nivel_acidente  = self.nivel_acidentes,
                time_scale      = self.time_scale,
                atraso_s        = 0,
                machucado       = True,
                estornado       = True
            )

        # Remove da lista de ativos e também da lista de originais (chuva)
        if entregador in self.ativos:
            self.ativos.remove(entregador)
        if entregador in self.entregadores_ativos_original:
            self.entregadores_ativos_original.remove(entregador)

        # Ambulância vem da esquerda da tela (fora do mapa)
        pos_acidente  = (entregador.x, entregador.y)
        offscreen_pos = (-100, random.randint(
            UI_PANEL_HEIGHT + 30, self.height - 30))

        ambulancia = Ambulancia(
            offscreen_pos,
            pos_acidente,
            self.pos_map,
            self.G,
            self.edge_speed_kph,
            self.meters_per_pixel,
            self.time_scale
        )
        self.ambulancias.append(ambulancia)

        # Registra posição do acidente para mostrar cruz '+' até ambulância chegar
        self.acidentes_visuais.append({
            'x':          entregador.x,
            'y':          entregador.y,
            'ambulancia': ambulancia
        })

    # ── Atualização de entregadores na chuva (20% redução) ───────────────────
    def _atualizar_entregadores_chuva(self):
        """
        Chuva ativa: remove até 20% dos entregadores não-entregando (IDLE + HOLDING).
        Chuva desativa: devolve todos os removidos (que não foram machucados).
        Trata os casos de 0 e 1 entregadores disponíveis.
        """
        if self.chuva_ativa == self.chuva_anterior:
            return

        if self.chuva_ativa:
            # Guarda snapshot atual para restaurar depois
            self.entregadores_ativos_original = self.ativos.copy()

            # Entregadores elegíveis para remoção: IDLE ou HOLDING (não entregando)
            nao_entregando = [e for e in self.ativos if e.state in ("IDLE", "HOLDING")]
            n_total = len(nao_entregando)

            if n_total <= 1:
                # 0 ou 1: ninguém é removido (preservar pelo menos 1)
                pass
            else:
                n_remover = max(1, int(n_total * CHUVA_REDUCAO_FROTA))
                n_remover = min(n_remover, n_total - 1)  # sempre deixa ao menos 1
                remover   = random.sample(nao_entregando, n_remover)
                for e in remover:
                    if e in self.ativos:
                        self.ativos.remove(e)
        else:
            # Restaura entregadores que foram apenas removidos pela chuva
            # (machucados já foram removidos de entregadores_ativos_original também)
            for e in self.entregadores_ativos_original:
                if e not in self.ativos:
                    self.ativos.append(e)
            self.entregadores_ativos_original = []

        self.chuva_anterior = self.chuva_ativa

    # ── Despacho de pedidos ───────────────────────────────────────────────────
    def despachar(self):
        """
        Associa entregadores a pedidos:
        - Entregadores em HOLDING têm prioridade.
        - Mais próximo do cluster de lojas recebe a corrida.
        - Com HotSpot ativo, lojas próximas a hotspot têm 80% de prioridade.
        - Entregador na capacidade máxima não aceita mais pedidos até entregar todos.
        - Tempo ideal calculado com TORTUOSITY_FACTOR e velocidade efetiva da via.
        """
        lojas_ativas = self.lojas_no_mapa[:self.qtd_lojas_visiveis]
        if not lojas_ativas or self.pedidos_pendentes <= 0:
            return

        # Velocidade média das vias (para cálculo de tempo ideal)
        avg_road_speed_kph = (
            sum(self.edge_speed_kph.values()) / max(1, len(self.edge_speed_kph))
            if self.edge_speed_kph else DEFAULT_ROAD_SPEED_KPH
        )

        holding_list   = [e for e in self.ativos if e.state == "HOLDING"]
        idle_list      = [e for e in self.ativos if e.state == "IDLE"]
        candidate_list = holding_list + idle_list
        if not candidate_list:
            return

        hotspot_centers = self._get_hotspot_centers() if self.hotspot_ativo else []
        now = pygame.time.get_ticks()

        def _loja_hotspot_dist(loja):
            if not hotspot_centers:
                return float('inf')
            lp = self.pos_map.get(loja['node_id'], (0, 0))
            return min(math.hypot(lp[0] - hc[0], lp[1] - hc[1]) for hc in hotspot_centers)

        while self.pedidos_pendentes > 0 and candidate_list:
            # Seleciona pool de lojas (com viés hotspot)
            if self.hotspot_ativo and hotspot_centers and random.random() < 0.80:
                lojas_sorted = sorted(lojas_ativas, key=_loja_hotspot_dist)
                n_pool       = max(1, (len(lojas_sorted) + 1) // 2)
                lojas_pool   = lojas_sorted[:n_pool]
            else:
                lojas_pool = lojas_ativas

            if not lojas_pool:
                break

            max_cap  = max(e.cap_max for e in candidate_list)
            n_orders = min(max_cap, self.pedidos_pendentes, len(lojas_pool))
            if n_orders <= 0:
                break

            selected_lojas = random.sample(lojas_pool, n_orders)

            cx_lojas = sum(self.pos_map.get(l['node_id'], (0, 0))[0]
                           for l in selected_lojas) / n_orders
            cy_lojas = sum(self.pos_map.get(l['node_id'], (0, 0))[1]
                           for l in selected_lojas) / n_orders

            # Entregador mais próximo do cluster de lojas
            best_e = min(candidate_list,
                         key=lambda e: math.hypot(e.x - cx_lojas, e.y - cy_lojas))

            # Verifica bônus holding
            holding_bonus = False
            if best_e.state == "HOLDING" and best_e.holding_hotspot_center:
                dist_to_hotspot = math.hypot(
                    best_e.x - best_e.holding_hotspot_center[0],
                    best_e.y - best_e.holding_hotspot_center[1])
                if dist_to_hotspot < 100:
                    holding_bonus = True

            # Limita n_orders à capacidade real do entregador selecionado
            n_orders       = min(best_e.cap_max, n_orders)
            selected_lojas = selected_lojas[:n_orders]
            if n_orders <= 0:
                candidate_list.remove(best_e)
                continue

            # Velocidade efetiva: mínimo entre vel. do entregador e vel. média da via
            vel_efetiva_kph = min(best_e.vel_kph, avg_road_speed_kph)
            vel_efetiva_ms  = vel_efetiva_kph * (1000.0 / 3600.0)

            destinos = [random.choice(self.nodes) for _ in range(n_orders)]

            jobs = []
            for loja, dest in zip(selected_lojas, destinos):
                l_pos  = self.pos_map.get(loja['node_id'], (0, 0))
                d_pos  = self.pos_map.get(dest, (0, 0))
                # Distância em linha reta * metros/pixel * fator tortuosidade
                dist_m = (math.hypot(d_pos[0] - l_pos[0], d_pos[1] - l_pos[1])
                          * self.meters_per_pixel * TORTUOSITY_FACTOR)
                dist_m = max(dist_m, 100.0)

                # Tempo ideal por job: distância real / velocidade efetiva (sem intemperismos)
                ideal_delivery_s = dist_m / vel_efetiva_ms / self.time_scale + (10.0 / self.time_scale)

                jobs.append({
                    'loja_id':          loja['id'],
                    'loja_node':        loja['node_id'],
                    'dest_node':        dest,
                    'accept_time':      now,
                    'pickup_time':      None,
                    'qtd_itens':        1,
                    'dist_m':           dist_m,
                    'ideal_delivery_s': ideal_delivery_s,
                    'holding_bonus':    holding_bonus,
                })

            # Fila: todos os restaurantes primeiro, depois todos os destinos
            stop_queue = (
                [{'node': j['loja_node'], 'phase': 'SHOP', 'job': j} for j in jobs] +
                [{'node': j['dest_node'], 'phase': 'DEST', 'job': j} for j in jobs]
            )

            # Tempo ideal para o TIMER VISUAL da corrida completa
            # (percurso: shop1→shop2→...→dest1→...→destN)
            timer_nodes   = [s['node'] for s in stop_queue]
            total_dist_px = 0.0
            for i in range(len(timer_nodes) - 1):
                p1 = self.pos_map.get(timer_nodes[i],   (0, 0))
                p2 = self.pos_map.get(timer_nodes[i+1], (0, 0))
                total_dist_px += math.hypot(p2[0] - p1[0], p2[1] - p1[1])

            total_dist_m_corrida = total_dist_px * self.meters_per_pixel * TORTUOSITY_FACTOR
            n_stops_corrida      = len(stop_queue)
            ideal_travel_s       = total_dist_m_corrida / vel_efetiva_ms / self.time_scale
            wait_overhead_s      = n_stops_corrida * (10.0 / self.time_scale)
            corrida_ideal_s      = ideal_travel_s + wait_overhead_s

            ponto = best_e.target_node if best_e.target_node else best_e.node
            try:
                p = nx.shortest_path(self.G, ponto, stop_queue[0]['node'], weight='length')
                best_e.path                     = p[1:]
                best_e.stop_queue               = stop_queue
                best_e.carga_atual              = n_orders
                best_e.state                    = "MOVING"
                best_e._corrida_jobs_total      = n_orders
                best_e._corrida_delivered_count = 0
                best_e._corrida_total_preco     = 0.0
                best_e.delivery_start           = None   # setado ao pegar no SHOP
                best_e.ideal_time_s             = corrida_ideal_s
                best_e.machucado_ocorreu        = False
                best_e.jobs_to_restore          = []
                self.pedidos_pendentes         -= n_orders
            except Exception:
                pass

            candidate_list.remove(best_e)

    # ── Algoritmo de Holding Time ──────────────────────────────────────────────
    def _atualizar_holding_time(self, current_time):
        """
        Coloca entregadores IDLE próximos a hotspots em estado HOLDING.
        Bônus de 30% é aplicado nos pedidos aceitos em estado HOLDING.
        """
        if not self.holding_ativo or not self.hotspot_ativo:
            return

        hotspot_centers = self._get_hotspot_centers()
        if not hotspot_centers:
            return

        for e in self.ativos:
            if e.state == "IDLE":
                for hc in hotspot_centers:
                    dist = math.hypot(e.x - hc[0], e.y - hc[1])
                    if dist < 80:
                        duration_ms = (random.uniform(HOLDING_MIN_S, HOLDING_MAX_S)
                                       * 1000 / self.time_scale)
                        e.start_holding(duration_ms, hc)
                        break

    # ── Modo automático ───────────────────────────────────────────────────────
    def _update_auto(self, current_time):
        """
        Automatiza: chuva, trânsito, acidentes, pedidos e frota.
        Hotspot e Holding são ativados junto com o modo auto.
        """
        if not self.G:
            return
        ts = max(1.0, self.time_scale)

        # Alterna chuva
        if current_time - self._auto_last_chuva >= self._auto_chuva_interval_base / ts:
            self._auto_last_chuva = current_time
            self.chuva_ativa      = not self.chuva_ativa
            self._atualizar_entregadores_chuva()

        # Ajusta trânsito (aumenta com chuva, diminui sem)
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

        # Ajusta acidentes (aparecem e somem aleatoriamente)
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

        # Auto-adiciona pedidos periodicamente
        if current_time - self._auto_last_pedido >= self._auto_pedido_interval_base / ts:
            self._auto_last_pedido  = current_time
            self.pedidos_pendentes += random.randint(1, 3)

        # Auto-adiciona entregador se há pedidos pendentes sem ninguém disponível
        if current_time - self._auto_last_entregador >= self._auto_entregador_interval_base / ts:
            self._auto_last_entregador = current_time
            n_disponiveis = len([e for e in self.ativos
                                 if e.state in ("IDLE", "HOLDING")])
            if (self.pedidos_pendentes > 0
                    and n_disponiveis == 0
                    and len(self.ativos) < len(self.db_entregadores)):
                d = self.db_entregadores[len(self.ativos)]
                self.ativos.append(
                    Entregador(d, random.choice(self.nodes), self.pos_map))

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

    # ── Legenda de velocidades das vias (canto inferior direito) ──────────────
    def _draw_speed_legend(self):
        """
        Legenda de cores das vias — posicionada no canto inferior DIREITO
        para não colidir com a legenda de intempéries/veículos (canto esquerdo).
        """
        items = [
            ((0,   200, 80),  "≤30 km/h  Residencial"),
            ((255, 200,  0),  "≤45 km/h  Via local"),
            ((255, 140,  0),  "≤60 km/h  Avenida"),
            ((220,  20, 60),  " >60 km/h  Via expressa"),
        ]
        fx = self.width - 195
        fy = self.height - 75
        for color, label in items:
            pygame.draw.rect(self.screen, color, (fx, fy, 14, 10))
            self.screen.blit(
                self.small_font.render(label, True, TEXT_COLOR), (fx + 18, fy - 1))
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

            # ── ROW 1 ─────────────────────────────────────────────────────
            btn_v   = Botao(10,        Y_R1_BTN, 80, H_R1, "◀ VOLTAR",  (200, 200, 200))
            btn_e_m = Botao(110,       Y_R1_BTN, 32, H_R1, "-",         (255, 200, 200))
            btn_e_p = Botao(147,       Y_R1_BTN, 32, H_R1, "+",         (200, 255, 200))
            btn_l_m = Botao(cx -  80,  Y_R1_BTN, 32, H_R1, "-",         (255, 200, 200))
            btn_l_p = Botao(cx -  44,  Y_R1_BTN, 32, H_R1, "+",         (200, 255, 200))
            btn_p_m = Botao(cx + 100,  Y_R1_BTN, 32, H_R1, "-",         (255, 200, 200))
            btn_p_p = Botao(cx + 136,  Y_R1_BTN, 32, H_R1, "+",         (200, 255, 200))
            btn_t_m = Botao(self.width - 200, Y_R1_BTN, 40, H_R1, "<<", (220, 220, 255))
            btn_t_p = Botao(self.width -  52, Y_R1_BTN, 40, H_R1, ">>", (220, 220, 255))

            # ── ROW 2 ─────────────────────────────────────────────────────
            btn_tr_m = Botao(110,  Y_R2_BTN, 32, H_R2, "-",             (255, 200, 200))
            btn_tr_p = Botao(147,  Y_R2_BTN, 32, H_R2, "+",             (200, 255, 200))
            btn_ac_m = Botao(380,  Y_R2_BTN, 32, H_R2, "-",             (255, 200, 200))
            btn_ac_p = Botao(417,  Y_R2_BTN, 32, H_R2, "+",             (200, 255, 200))

            chuva_cor = (180, 200, 255) if self.chuva_ativa  else (220, 220, 220)
            txt_chuva = "[✓] ATIVA"  if self.chuva_ativa     else "[ ] INATIVA"
            btn_chuva = Botao(590, Y_R2_BTN, 120, H_R2, txt_chuva, chuva_cor)

            auto_cor  = (180, 255, 180) if self.auto_mode    else (220, 220, 220)
            txt_auto  = "[✓] LIGADO" if self.auto_mode       else "[ ] DESLIG."
            btn_auto  = Botao(730, Y_R2_BTN, 120, H_R2, txt_auto,  auto_cor)

            hs_cor    = (255, 160, 160) if self.hotspot_ativo else (220, 220, 220)
            txt_hs    = "[✓] ATIVO"  if self.hotspot_ativo   else "[ ] DESLIG."
            btn_hs    = Botao(870, Y_R2_BTN, 120, H_R2, txt_hs,    hs_cor)

            hold_cor  = (180, 180, 255) if self.holding_ativo else (220, 220, 220)
            txt_hold  = "[✓] HOLD" if self.holding_ativo      else "[ ] HOLD"
            btn_hold  = Botao(1010, Y_R2_BTN, 80, H_R2, txt_hold,  hold_cor)

            # ── Fundo ─────────────────────────────────────────────────────
            self.screen.fill((220, 228, 235) if self.chuva_ativa else BG_COLOR)

            # ── Eventos ───────────────────────────────────────────────────
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False

                elif ev.type == pygame.VIDEORESIZE:
                    self.width, self.height = ev.w, ev.h
                    self.screen    = pygame.display.set_mode(
                        (self.width, self.height), pygame.RESIZABLE)
                    self.rain_surf = pygame.Surface(
                        (self.width, self.height), pygame.SRCALPHA)
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
                            self.time_scale = max(1, self.time_scale - 2)

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

                        # Chuva
                        if btn_chuva.rect.collidepoint(ev.pos):
                            self.chuva_ativa = not self.chuva_ativa
                            self._atualizar_entregadores_chuva()

                        # Modo Auto — ao ligar, habilita hotspot e holding automaticamente
                        if btn_auto.rect.collidepoint(ev.pos):
                            self.auto_mode = not self.auto_mode
                            if self.auto_mode:
                                self.hotspot_ativo      = True
                                self.holding_ativo      = True
                                self._hotspot_surf      = None
                                self._auto_last_chuva      = current_time
                                self._auto_last_transito   = current_time
                                self._auto_last_acidente   = current_time
                                self._auto_last_pedido     = current_time
                                self._auto_last_entregador = current_time

                        # HotSpot
                        if btn_hs.rect.collidepoint(ev.pos):
                            self.hotspot_ativo = not self.hotspot_ativo
                            self._hotspot_surf = None

                        # Holding
                        if btn_hold.rect.collidepoint(ev.pos):
                            self.holding_ativo = not self.holding_ativo

            # ── Renderização ──────────────────────────────────────────────
            if self.state == "MENU":
                txt = self.title_font.render(
                    "SIMULADOR LOGÍSTICA URBANA", True, TEXT_COLOR)
                self.screen.blit(txt, (cx - txt.get_width()//2, 150))
                btn_mack.draw(self.screen, self.font)
                btn_itaim.draw(self.screen, self.font)
                btn_pinheiros.draw(self.screen, self.font)

            elif self.state == "SIM":
                if self.auto_mode:
                    self._update_auto(current_time)

                # Mapa e ruas
                self._draw_edges()

                # Hotspot circles (abaixo dos entregadores)
                if self.hotspot_ativo:
                    self._draw_hotspots()

                # Lojas
                for l in self.lojas_no_mapa[:self.qtd_lojas_visiveis]:
                    nid = l['node_id']
                    pygame.draw.rect(self.screen, (60, 60, 60),
                                     (*self.pos_map[nid], 12, 12))
                    lbl = pygame.font.SysFont("arial", 10).render(
                        l['nome'][:15], True, (100, 100, 100))
                    self.screen.blit(lbl,
                                     (self.pos_map[nid][0]-10, self.pos_map[nid][1]-15))

                self.despachar()
                self._atualizar_holding_time(current_time)

                mod_carro = 0.60 if self.chuva_ativa else 1.0
                mod_moto  = 0.60 if self.chuva_ativa else 1.0
                mod_bike  = 0.50 if self.chuva_ativa else 1.0

                hotspot_centers = self._get_hotspot_centers() if self.hotspot_ativo else []

                # Atualiza e desenha entregadores
                for e in list(self.ativos):   # cópia para permitir remoção segura
                    e.update(self.G, self.pos_map, self.edge_speed_kph,
                             self.meters_per_pixel, self.time_scale, current_time,
                             mod_carro, mod_moto, mod_bike,
                             self.edge_transito, self.edge_acidente,
                             self.chuva_ativa, self.nivel_transito, self.nivel_acidentes,
                             hotspot_ativo=self.hotspot_ativo,
                             hotspot_centers=hotspot_centers)
                    # Entregador machucado → remove imediatamente, cria ambulância e cruz
                    if e.machucado:
                        self._remover_entregador_machucado(e, current_time)
                        continue   # não desenha o entregador removido

                    e.draw(self.screen, self.pos_map, current_time)

                # Desenha cruzes '+' nos locais de acidente (enquanto ambulância a caminho)
                for av in list(self.acidentes_visuais):
                    if av['ambulancia'].active:
                        self._draw_acidente_cruz(av['x'], av['y'])
                    else:
                        self.acidentes_visuais.remove(av)

                # Atualiza e desenha ambulâncias
                for amb in list(self.ambulancias):
                    amb.update(self.time_scale)
                    amb.draw(self.screen)
                    if not amb.active:
                        self.ambulancias.remove(amb)

                self._draw_speed_legend()

                if self.chuva_ativa:
                    self._update_chuva()
                    self._draw_chuva()

                # ── Painel UI (desenhado por cima do mapa) ────────────────
                pygame.draw.rect(self.screen, UI_PANEL,
                                 (0, 0, self.width, UI_PANEL_HEIGHT))
                pygame.draw.line(self.screen, (180, 175, 165),
                                 (0, UI_PANEL_HEIGHT), (self.width, UI_PANEL_HEIGHT), 2)
                sep_y = Y_R2_LBL - 4
                pygame.draw.line(self.screen, (200, 196, 185),
                                 (10, sep_y), (self.width - 10, sep_y), 1)

                for btn in [btn_v, btn_e_m, btn_e_p, btn_l_m, btn_l_p,
                             btn_p_m, btn_p_p, btn_t_m, btn_t_p,
                             btn_tr_m, btn_tr_p, btn_ac_m, btn_ac_p,
                             btn_chuva, btn_auto, btn_hs, btn_hold]:
                    btn.draw(self.screen, self.font)

                def lbl_acima(texto, cx_pos, y_pos, fonte=None, cor=TEXT_COLOR):
                    f = fonte or self.font
                    s = f.render(texto, True, cor)
                    self.screen.blit(s, (int(cx_pos - s.get_width() / 2), y_pos))

                frota_cx   = (btn_e_m.rect.left  + btn_e_p.rect.right)  // 2
                lojas_cx   = (btn_l_m.rect.left  + btn_l_p.rect.right)  // 2
                pedidos_cx = (btn_p_m.rect.left  + btn_p_p.rect.right)  // 2
                time_cx    = (btn_t_m.rect.left  + btn_t_p.rect.right)  // 2

                lbl_acima(f"FROTA: {len(self.ativos)}",         frota_cx,   Y_R1_LBL)
                lbl_acima(f"LOJAS: {self.qtd_lojas_visiveis}",  lojas_cx,   Y_R1_LBL)
                lbl_acima(f"PEDIDOS: {self.pedidos_pendentes}",  pedidos_cx, Y_R1_LBL)
                lbl_acima(f"TIME: {self.time_scale:.0f}x",       time_cx,    Y_R1_LBL,
                          fonte=self.medium_font, cor=(50, 50, 180))

                transito_cx = (btn_tr_m.rect.left + btn_tr_p.rect.right) // 2
                acidente_cx = (btn_ac_m.rect.left + btn_ac_p.rect.right) // 2

                lbl_acima(f"TRÂNSITO: {self.nivel_transito}",  transito_cx,             Y_R2_LBL)
                lbl_acima(f"ACIDENTES: {self.nivel_acidentes}", acidente_cx,             Y_R2_LBL)
                lbl_acima("CHUVA",      btn_chuva.rect.centerx, Y_R2_LBL)
                lbl_acima("MODO AUTO",  btn_auto.rect.centerx,  Y_R2_LBL)
                lbl_acima("HOTSPOT",    btn_hs.rect.centerx,    Y_R2_LBL,
                          cor=(180, 30, 30) if self.hotspot_ativo else TEXT_COLOR)
                lbl_acima("HOLDING",    btn_hold.rect.centerx,  Y_R2_LBL,
                          cor=(80, 0, 120) if self.holding_ativo else TEXT_COLOR)

                # Escala (canto inferior direito)
                self.screen.blit(
                    self.small_font.render(
                        f"Escala: {self.meters_per_pixel:.2f} m/px", True, (120, 120, 120)),
                    (self.width - 160, self.height - 18))

                # ── Legenda inferior esquerda: intempéries + veículos ─────────
                # Posicionada de forma a não colidir com a legenda de vias (direita)
                lx  = 10
                ly  = self.height - 195   # altura suficiente para todos os itens
                ROW = 16                  # espaçamento entre linhas

                def _lbl(surf_color, draw_fn, texto, yl):
                    """Desenha uma linha da legenda."""
                    draw_fn(yl)
                    self.screen.blit(
                        self.small_font.render(texto, True, TEXT_COLOR),
                        (lx + 20, yl - 1))

                # — Intemperismos —
                pygame.draw.rect(self.screen, (255, 165, 0), (lx, ly, 14, 10))
                self.screen.blit(self.small_font.render("▲ Trânsito na rua", True, TEXT_COLOR),
                                 (lx + 18, ly - 1))
                ly += ROW

                pygame.draw.rect(self.screen, (220, 20, 20), (lx, ly, 14, 10))
                self.screen.blit(self.small_font.render("✖ Acidente na rua", True, TEXT_COLOR),
                                 (lx + 18, ly - 1))
                ly += ROW

                # — Timer de entrega —
                pygame.draw.rect(self.screen, (30, 160, 30), (lx, ly, 14, 10))
                self.screen.blit(self.small_font.render("+M:SS  Dentro do prazo", True, TEXT_COLOR),
                                 (lx + 18, ly - 1))
                ly += ROW

                pygame.draw.rect(self.screen, (200, 20, 20), (lx, ly, 14, 10))
                self.screen.blit(self.small_font.render("-M:SS  Atrasado", True, TEXT_COLOR),
                                 (lx + 18, ly - 1))
                ly += ROW

                pygame.draw.rect(self.screen, (255, 140, 0), (lx, ly, 14, 10))
                self.screen.blit(self.small_font.render("LESAO  Entregador machucado", True, TEXT_COLOR),
                                 (lx + 18, ly - 1))
                ly += ROW

                pygame.draw.rect(self.screen, (128, 0, 128), (lx, ly, 14, 10))
                self.screen.blit(self.small_font.render("HOLDING  Aguardando pedidos", True, TEXT_COLOR),
                                 (lx + 18, ly - 1))
                ly += ROW + 4   # separador visual

                # — Veículos —
                # Moto: círculo
                pygame.draw.circle(self.screen, (255, 51, 102), (lx + 7, ly + 5), 6)
                pygame.draw.circle(self.screen, (255, 255, 255), (lx + 7, ly + 5), 6, 1)
                self.screen.blit(self.small_font.render(
                    f"● Moto  (min R${PRECO_MINIMO_MOTO:.2f})", True, TEXT_COLOR),
                    (lx + 18, ly - 1))
                ly += ROW

                # Carro: quadrado
                pygame.draw.rect(self.screen, (0, 194, 209), (lx + 2, ly + 1, 12, 12))
                pygame.draw.rect(self.screen, (255, 255, 255), (lx + 2, ly + 1, 12, 12), 1)
                self.screen.blit(self.small_font.render(
                    f"■ Carro (min R${PRECO_MINIMO_CARRO:.2f})", True, TEXT_COLOR),
                    (lx + 18, ly - 1))
                ly += ROW

                # Bike: triângulo
                tp = [(lx + 7, ly + 1), (lx + 2, ly + 11), (lx + 12, ly + 11)]
                pygame.draw.polygon(self.screen, (0, 153, 102), tp)
                pygame.draw.polygon(self.screen, (255, 255, 255), tp, 1)
                self.screen.blit(self.small_font.render(
                    f"▲ Bike  (min R${PRECO_MINIMO_BIKE:.2f})", True, TEXT_COLOR),
                    (lx + 18, ly - 1))

            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()


if __name__ == "__main__":
    Simulador().run()