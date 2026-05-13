# 🛵 Algoritmo de Entregas — Keeta Delivery

<div align="center">

![Hackathon Mackenzie 2026](https://img.shields.io/badge/Hackathon-Mackenzie%202026-FFE600?style=for-the-badge&labelColor=232323)
![2º Lugar](https://img.shields.io/badge/Resultado-2º%20Lugar%20🥈-1EC96E?style=for-the-badge&labelColor=232323)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Machine Learning](https://img.shields.io/badge/Machine%20Learning-scikit--learn-F7931E?style=for-the-badge&logo=scikit-learn&logoColor=white)

**Sistema completo de logística inteligente desenvolvido pela Team E-Keda para o desafio proposto pela Keeta Delivery Brazil LTDA no Hackathon Mackenzie 2026.**

*Escola de Engenharia — Universidade Presbiteriana Mackenzie · São Paulo, 2026*

</div>

---

## 🏆 Premiação

Este projeto conquistou o **2º lugar** no desafio proposto pela empresa **Keeta Delivery Brazil LTDA** no **HACKATHON 2026**, evento promovido pela Escola de Engenharia da Universidade Presbiteriana Mackenzie.

> Declaração oficial emitida pelo Prof. Dr. Delmárcio Gomes da Silva, Coordenador de Extensão da Escola de Engenharia Mackenzie, em 24 de março de 2026.

---

## 📋 Sumário

- [Visão Geral](#-visão-geral)
- [Arquitetura da Solução](#-arquitetura-da-solução)
- [Os 5 Algoritmos Interligados](#-os-5-algoritmos-interligados)
- [Score de Alocação](#-score-de-alocação)
- [Logística de Agrupamento (Holding)](#-logística-de-agrupamento-holding)
- [Balanceamento de Hotspots](#-balanceamento-de-hotspots)
- [Modelos de IA Treinados](#-modelos-de-ia-treinados)
- [Gestão de Exceções](#-gestão-de-exceções)
- [Tabela de Bônus e Precificação](#-tabela-de-bônus-e-precificação)
- [KPIs e Resultados](#-kpis-e-resultados)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [Como Executar](#-como-executar)
- [Tecnologias Utilizadas](#-tecnologias-utilizadas)
- [Equipe](#-equipe)

---

## 🌐 Visão Geral

O projeto resolve o problema central de **otimização de entregas em larga escala** para a Região Metropolitana de São Paulo (RMSP), abordando seis temas do desafio de forma integrada:

| # | Tema | Abordagem |
|---|------|-----------|
| 1 | **Alocação de Entregadores** | Score combinado com 4 fatores ponderados |
| 2 | **Algoritmos de Decisão** | 5 algoritmos modulares interligados |
| 3 | **Logística de Agrupamento** | Holding time com raio de ~1 km |
| 4 | **Balanceamento de Hotspots** | K-Means + Prophet para pré-posicionamento |
| 5 | **Inteligência de Dados** | 4 modelos de ML retreinados diariamente |
| 6 | **Gestão de Exceções** | Resposta automática a chuva, acidentes e inércia |

A arquitetura foi projetada para **escalar com dados reais da Keeta** e evoluir continuamente a partir do log operacional estruturado gerado a cada entrega.

---

## 🏗 Arquitetura da Solução

```
┌─────────────────────────────────────────────────────────┐
│                    NOVO PEDIDO CHEGA                    │
└────────────────────────┬────────────────────────────────┘
                         │
           ┌─────────────▼──────────────┐
           │   PREVISÃO DE ETA (RF)     │  ← RandomForest Regressor
           │  distância, pico, chuva,   │
           │  veículo, fim de semana    │
           └─────────────┬──────────────┘
                         │
           ┌─────────────▼──────────────┐
           │   VERIFICAÇÃO DE HOLDING   │  ← K-Means Zone
           │  raio ~1 km, apenas pico   │
           │  (11–13h e 18–21h)         │
           └─────────────┬──────────────┘
                         │
           ┌─────────────▼──────────────┐
           │    LEILÃO REVERSO          │  ← Logistic Regression
           │  p(aceite) por entregador  │
           └─────────────┬──────────────┘
                         │
           ┌─────────────▼──────────────┐
           │    SCORE DE ALOCAÇÃO       │  ← Fórmula ponderada
           │  melhor entregador selecionado │
           └─────────────┬──────────────┘
                         │
           ┌─────────────▼──────────────┐
           │    LOG ESTRUTURADO         │  ← CSV → PostgreSQL
           │  retroalimenta os modelos  │
           └─────────────┬──────────────┘
                         │
           ┌─────────────▼──────────────┐
           │    RETREINAMENTO DIÁRIO    │  ← Todos os modelos
           └─────────────────────────────┘
```

---

## ⚙️ Os 5 Algoritmos Interligados

O sistema é composto por **5 módulos modulares** que operam em sequência e se retroalimentam:

### 01 — Leilão Reverso (`LogisticRegression`)
Em vez de enviar o pedido ao entregador mais próximo, o sistema **prevê a probabilidade de aceite** da proposta com base no histórico individual de aceite/rejeição e tempo ocioso de cada entregador. Isso reduz rejeições e acelera a alocação.

### 02 — Pricing & Bônus (Dinâmico)
Modelo de repasse transparente e orientado a incentivo:
- **R$ 7,50** base por entrega
- **+ R$ 1,00/km** percorrido
- **+ R$ 3,00** para quem aceita agrupamento (holding)
- **Surge de 30%** ao cliente em horário de pico sem holding disponível

### 03 — Previsão de ETA (`RandomForestRegressor`)
O modelo prevê o tempo total do trajeto considerando **5 features**:
1. Distância (km)
2. Chuva (sim/não)
3. Horário de pico
4. Tipo de veículo
5. Dia da semana (fim de semana)

Retreinado diariamente com os novos registros do log operacional.

### 04 — Log Estruturado (`CSV → PostgreSQL`)
Cada entrega registra um vetor completo de features:

```json
{
  "distancia_km": 3.2,
  "tempo_real_min": 28,
  "chuva": 1,
  "hora_pico": 1,
  "holding_aplicado": 1,
  "bonus_pago": 10.50,
  "status_final": "ENTREGUE"
}
```

Esse log é a base de retreinamento de todos os modelos.

### 05 — Holding Time (`K-Means Zone`)
Agrupa pedidos próximos em raio de **~1 km** durante horários de pico, adicionando apenas **5 minutos ao ETA** enquanto dobra a ocupação do entregador.

---

## 📊 Score de Alocação

O entregador selecionado para cada pedido é aquele com o **menor score** pela fórmula combinada:

```
score = (0.5 × tempo_previsto)
      + (0.2 × dist_km)
      − (0.2 × valor_repasse)
      − (0.1 × tempo_ocioso)
```

| Peso | Fator | Lógica |
|------|-------|--------|
| **50%** | Tempo Previsto | ETA estimado via RandomForest — principal fator |
| **20%** | Distância (km) | Penaliza km extras via OSRM com fallback euclidiano |
| **20%** | Valor do Repasse | Favorece pedidos mais rentáveis ao entregador |
| **10%** | Ociosidade | Prioriza entregadores parados há mais tempo |

---

## 📦 Logística de Agrupamento (Holding)

O algoritmo de holding é ativado **exclusivamente em horários de pico (11h–13h e 18h–21h)** e segue o fluxo:

```
1. Novo pedido chega
   └─► Sistema verifica raio de 0,01° (~1 km) por pedidos pendentes na mesma zona

2. Agrupamento detectado
   └─► Entregador recebe proposta com bônus de +R$3,00

3. Holding time de 5 min
   └─► Trade-off: entregador faz 2 entregas no tempo de 1, cliente recebe dentro do prazo

4. ETA recalculado
   └─► Algoritmo ajusta previsão incluindo holding time e faz repricing automático
```

**Implementação:**

```python
def verificar_holding(pedido_novo, pendentes, contexto):
    # Só ativa em horário de pico
    if not contexto.hora_pico:
        return None
    for candidato in pendentes:
        dist = haversine(pedido_novo, candidato)
        if dist <= 0.01:  # ~1 km
            return candidato
    return None
```

**Métricas do Holding:**

| Parâmetro | Valor |
|-----------|-------|
| Raio de busca | ~1 km (0,01°) |
| Holding time máximo | 5 minutos |
| Bônus ao entregador | + R$ 3,00 |
| Janelas de ativação | 11h–13h e 18h–21h |

---

## 🗺 Balanceamento de Hotspots

A IA analisa o **log histórico de entregas** para identificar zonas com alta probabilidade de demanda futura, permitindo **pré-posicionar entregadores ociosos** antes que os pedidos cheguem.

**Pipeline:**

```
Log de Entregas (histórico)
        │
        ▼
K-Means Clustering → 5 centroides por faixa horária
        │
        ▼
Prophet Forecast → Volume de pedidos nas próximas 48h
        │
        ▼
Plano de reposicionamento → próximas 8h operacionais
```

**Características:**
- Segmentação em **até 5 zonas** por faixa horária
- Cada zona representa **18%–22%** do volume total
- Sex/Sáb concentram maior volume — escala ajustada automaticamente
- Detecção de sazonalidade semanal e picos de demanda

---

## 🤖 Modelos de IA Treinados

| Modelo | Aplicação | Features / Detalhes |
|--------|-----------|---------------------|
| **RandomForest Regressor** | Previsão de ETA | Distância, pico, chuva, tipo de veículo, fim de semana. Retreinado diariamente. |
| **Logistic Regression** | Probabilidade de aceite | Perfil histórico de aceite/rejeição e tempo ocioso do entregador. |
| **K-Means Clustering** | Segmentação geográfica | Até 5 zonas quentes por faixa horária, mapeando centroides de alta concentração. |
| **Prophet (Meta)** | Séries temporais | Previsão de volume de pedidos por hora, detectando sazonalidade semanal 48h à frente. |

### Desafios Personalizados por Perfil de Entregador

O sistema gera desafios para engajar a frota e aumentar a previsibilidade de oferta:

| Perfil | Desafio | Recompensa |
|--------|---------|------------|
| 🟢 Novato | Complete suas primeiras 5 entregas | **R$ 10,00** |
| 🔵 Holding | Aceite 3 pedidos agrupados esta semana | **R$ 9,00** |
| 🟡 Pico | Faça 5 entregas no horário de pico | **R$ 15,00** |
| 🔴 Veterano | Complete mais 10 entregas esta semana | **R$ 20,00** |

---

## 🚨 Gestão de Exceções

O sistema monitora a frota em tempo real e trata eventos imprevistos automaticamente, com integração a APIs externas de clima e tráfego na produção. As simulações contemplam os principais cenários da RMSP.

### Cenários Tratados

**🗺 Monitoramento de Rota (OSRM)**
> Ruas com trânsito ou acidente detectadas via grafo OSM — lógica de degradação de velocidade em tempo real.

**🚑 Resposta a Acidente**
> Entregador é removido da frota, pedidos estornados, pool restaurado e suporte emergencial acionado automaticamente.

**🌧 Chuva**
> 20% dos entregadores ociosos saem de operação (simulando recusa). Bônus automático de **+25%** ao entregador ativo.

**🔄 Inércia do Entregador**
> Entregador parado com pedido ativo por **> 5 min** gera alerta. Pedido é reatribuído com bônus de **R$ 3,00** ao "salvador".

### Log Estruturado de Exceções

```
✅ LOG ESTRUTURADO
Chuva       → chuva: 1, bonus: 25%
Acidente    → status: EMERGENCIA
Espera 20m  → bonus: R$2,50
Holding     → holding_aplicado: 1
Inércia     → REATRIBUIR_PEDIDO
```

---

## 💰 Tabela de Bônus e Precificação

| Item | Valor |
|------|-------|
| Base por entrega | **R$ 7,50** |
| Por km rodado | **+ R$ 1,00** |
| Holding (agrupamento) | **+ R$ 3,00** |
| Bônus chuva | **+ 25%** |
| Bônus holding time | **+ 30%** |
| Espera na loja (> 15 min) | **+ R$ 0,50/min** |
| Bônus "salvador" (reatribuição) | **+ R$ 3,00** |

---

## 📈 KPIs e Resultados

| KPI | Impacto | Descrição |
|-----|---------|-----------|
| **↓ ETA** | Redução | Tempo médio de entrega |
| **↓ km** | Redução | Quilometragem total da frota |
| **↑ OCC** | Aumento | Taxa de ocupação dos entregadores |
| **↑ SLA** | Aumento | Previsibilidade de prazo ao cliente |

> A arquitetura está preparada para **escalar com dados reais da Keeta na RMSP**, com modelos que evoluem continuamente a partir do log operacional gerado em produção.

---

## 🚀 Como Executar

```bash
python simulador_entregas.py
```

---

## 👥 Equipe

**Team E-Keda** — Hackathon Mackenzie 2026

| Membro | RA |
|--------|----|
| Mateus Ribeiro Cerqueira | 10443901 |

> Evento: **HACKATHON 2026** — Escola de Engenharia da Universidade Presbiteriana Mackenzie
> Empresa patrocinadora do desafio: **Keeta Delivery Brazil LTDA**
> Resultado: **🥈 2º Lugar**
> Data: São Paulo, 24 de março de 2026

---

<div align="center">

**Team E-Keda · Hackathon Mackenzie 2026**

*"Nossa solução usa IA para otimizar cada etapa da entrega — da previsão de demanda ao pós-entrega — com modelos que evoluem continuamente a partir do log operacional."*

</div>