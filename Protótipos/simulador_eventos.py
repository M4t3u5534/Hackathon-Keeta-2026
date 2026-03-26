import random
import networkx as nx

class SimuladorEventos:
    def __init__(self, grafo):
        self.grafo = grafo
        # Armazena as velocidades originais para basear os cálculos sem perder os dados da via
        self.velocidades_originais = {}
        for u, v, k, data in self.grafo.edges(data=True, keys=True):
            # Obtém a velocidade base. O OSMnx geralmente usa 'speed_kph'.
            # Caso não exista, assume 40 km/h por padrão.
            vel_base = data.get('speed_kph', 40.0)
            if isinstance(vel_base, list): # Em algumas vias o OSM retorna uma lista
                vel_base = float(vel_base[0])
            self.velocidades_originais[(u, v, k)] = float(vel_base)
            
        # Variáveis de Controle da Chuva
        self.estado_chuva = False
        self.tempo_chuva_restante = 0
        
        # Controle de Acidentes: dicionário {aresta: tempo_restante}
        self.acidentes_ativos = {}
        
        # Fatores de trânsito atuais de cada via
        self.fator_transito = {}

    def atualizar_mundo(self, tempo_passado=1):
        """
        Deve ser chamada a cada iteração (tick) do seu simulador.
        'tempo_passado' é quanto tempo de simulação avançou desde a última chamada.
        """
        self._gerenciar_chuva(tempo_passado)
        self._gerenciar_acidentes(tempo_passado)
        self._gerenciar_transito()
        self._aplicar_efeitos_no_grafo()

    def _gerenciar_chuva(self, tempo_passado):
        if self.estado_chuva:
            self.tempo_chuva_restante -= tempo_passado
            if self.tempo_chuva_restante <= 0:
                self.estado_chuva = False
                print("⛅ A chuva parou. O asfalto está secando.")
        else:
            # Chance de 2% de começar a chover a cada atualização
            if random.random() < 0.02:
                self.estado_chuva = True
                self.tempo_chuva_restante = random.randint(15, 60) # Duração aleatória (ex: minutos)
                print(f"🌧️ Começou a chover! Duração estimada: {self.tempo_chuva_restante} ciclos.")

    def _gerenciar_acidentes(self, tempo_passado):
        # Atualiza acidentes em andamento
        acidentes_finalizados = []
        for edge, tempo in self.acidentes_ativos.items():
            self.acidentes_ativos[edge] -= tempo_passado
            if self.acidentes_ativos[edge] <= 0:
                acidentes_finalizados.append(edge)
                
        for edge in acidentes_finalizados:
            del self.acidentes_ativos[edge]
            print(f"✅ Acidente limpo na via {edge}. O trânsito voltou ao normal.")

        # Criar novos acidentes (ex: 1% de chance de ocorrer algum acidente na cidade)
        if random.random() < 0.01:
            todas_arestas = list(self.velocidades_originais.keys())
            aresta_acidente = random.choice(todas_arestas)
            duracao = random.randint(20, 90)
            self.acidentes_ativos[aresta_acidente] = duracao
            print(f"⚠️ Acidente reportado na via {aresta_acidente}! Trânsito bloqueado por {duracao} ciclos.")

    def _gerenciar_transito(self):
        # Probabilidades do nível de tráfego
        # Pesos: 60% Livre, 25% Moderado, 10% Intenso, 5% Parado
        opcoes_fator = [1.0, 0.7, 0.4, 0.15] 
        probabilidades = [0.60, 0.25, 0.10, 0.05]
        
        for edge in self.velocidades_originais.keys():
            # Apenas 10% de chance das condições da via mudarem a cada ciclo, 
            # para evitar que o trânsito flutue de forma caótica e irreal a cada segundo.
            if random.random() < 0.10 or edge not in self.fator_transito:
                fator_escolhido = random.choices(opcoes_fator, weights=probabilidades, k=1)[0]
                self.fator_transito[edge] = fator_escolhido

    def _aplicar_efeitos_no_grafo(self):
        """
        Consolida todas as penalidades e atualiza os pesos (travel_time) no grafo do NetworkX.
        """
        # A chuva reduz a velocidade geral de toda a cidade em 20%
        penalidade_chuva = 0.80 if self.estado_chuva else 1.0
        
        for u, v, k, data in self.grafo.edges(data=True, keys=True):
            edge = (u, v, k)
            vel_base = self.velocidades_originais[edge]
            
            # Pega o trânsito dinâmico daquela aresta
            fator_transito_via = self.fator_transito.get(edge, 1.0)
            
            # Se há acidente na via, velocidade cai a 5% da base (redução drástica)
            fator_acidente = 0.05 if edge in self.acidentes_ativos else 1.0
            
            # Calcula a velocidade final compondo todos os eventos
            vel_final = vel_base * penalidade_chuva * fator_transito_via * fator_acidente
            
            # Garante que a via não tenha velocidade zero ou negativa (mínimo de 2 km/h)
            data['speed_kph'] = max(vel_final, 2.0)
            
            # Recalcula o tempo de viagem (o que os algoritmos de rota geralmente usam de "weight")
            if 'length' in data:
                # converte velocidade para metros por segundo (m/s)
                velocidade_ms = data['speed_kph'] / 3.6
                data['travel_time'] = data['length'] / velocidade_ms