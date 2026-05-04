# SPEC.md — Sistema Multiagentes: Análise de Concorrentes & Triagem de Compras

> **Version:** 1.0.0 | **Status:** Approved | **Date:** 2026-05-03

---

## 1. Visão Geral

Sistema autônomo multiagentes em Python que atua como uma equipe virtual de inteligência competitiva e automação de procurement. Dois eixos interligados:

- **Eixo 1 — Inteligência de Mercado:** monitoramento contínuo de concorrentes, preços, features e posicionamento de fornecedores.
- **Eixo 2 — Triagem de Compras:** validação automática de requisições de compra cruzando dados de mercado com critérios internos.

---

## 2. Arquitetura Base

```
┌──────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                              │
│            (main.py — GSD Pipeline Controller)                   │
└───────────────┬──────────────────────────────────────────────────┘
                │ delegates via @agent syntax
    ┌───────────▼────────────┐
    │   @researcher          │  ← Market Analyst Agent
    │   agents/researcher/   │
    └───────────┬────────────┘
                │ MarketResearchOutput (Pydantic)
    ┌───────────▼────────────┐
    │   @judge               │  ← QA Agent (validates researcher output)
    │   agents/judge/        │  ← BLOCKS if incomplete → retry loop (max 3)
    └───────────┬────────────┘
                │ ValidatedResearchOutput (Pydantic)
    ┌───────────▼────────────┐
    │   @procurement_analyst │  ← Procurement Triage Agent
    │   agents/procurement/  │
    └───────────┬────────────┘
                │ ProcurementDecision (Pydantic)
    ┌───────────▼────────────┐
    │   @synthesizer         │  ← Report Compiler Agent
    │   agents/synthesizer/  │
    └───────────┬────────────┘
                │ FinalReport (.md + .json)
              output/
```

**Execution model:** Strictly sequential. Each stage blocks until its Pydantic output is validated.

---

## 3. Escopo dos Subagentes

### A. `@researcher` — Market & Competitor Analyst

**Responsabilidades:**
- Coletar preços de produtos/serviços de fornecedores alvo (via web scraping ou API)
- Monitorar lançamentos de features e mudanças de posicionamento
- Coletar avaliações de plataformas públicas (G2, Capterra, etc.)
- Avaliar posicionamento SEO/tráfego estimado

**Input:**
```python
class ResearchRequest(BaseModel):
    target_companies: list[str]
    product_category: str
    procurement_request_id: str
    search_keywords: list[str]
    max_sources_per_company: int = 5
```

**Output:**
```python
class CompetitorProfile(BaseModel):
    company_name: str
    website_url: str
    price_range: tuple[float, float] | None
    key_features: list[str]
    review_score: float | None
    review_count: int | None
    seo_traffic_estimate: int | None
    data_confidence: Literal["high", "medium", "low"]
    scraping_errors: list[str] = []

class MarketResearchOutput(BaseModel):
    request_id: str
    timestamp: datetime
    profiles: list[CompetitorProfile]
    market_average_price: float | None
    data_completeness_score: float  # 0.0 to 1.0
```

---

### B. `@judge` — QA / Reviewer Agent

**Responsabilidades:**
- Validar estrutural e semanticamente o output do `@researcher`
- Aplicar regras de negócio: `data_completeness_score >= 0.7`, mínimo 2 perfis com `data_confidence != "low"`
- Se falhar: retornar `JudgeVerdict(passed=False, reason=..., retry_researcher=True)`
- Se aprovado: encaminhar `ValidatedResearchOutput` para o próximo estágio

**Retry Policy:** máximo 3 tentativas do `@researcher`. Na 3ª falha → `PipelineError` com log estruturado.

**Schemas:**
```python
class JudgeVerdict(BaseModel):
    passed: bool
    reason: str
    retry_researcher: bool
    failed_rules: list[str]

class ValidatedResearchOutput(BaseModel):
    original: MarketResearchOutput
    verdict: JudgeVerdict
    validated_at: datetime
```

---

### C. `@procurement_analyst` — Procurement Triage Agent

**Responsabilidades:**
- Receber a requisição de compra interna + dados validados do mercado
- Verificar se o fornecedor proposto atende aos requisitos mínimos
- Comparar preço proposto vs. média de mercado
- Gerar veredicto de aprovação/rejeição com justificativa
- Formatar output para integração com sistemas externos (ERP/WMS)

**Input:**
```python
class ProcurementRequest(BaseModel):
    request_id: str
    requester: str
    supplier_name: str
    proposed_price: float
    required_features: list[str]
    budget_ceiling: float
    urgency: Literal["low", "medium", "high", "critical"]
```

**Output:**
```python
class ProcurementDecision(BaseModel):
    request_id: str
    decision: Literal["approved", "rejected", "pending_review"]
    price_vs_market: Literal["below", "at", "above"]
    price_delta_pct: float
    missing_features: list[str]
    recommendation: str
    erp_payload: dict  # formatted for external system integration
    decided_at: datetime
```

---

### D. `@synthesizer` — Report Compiler

**Responsabilidades:**
- Compilar toda a cadeia de dados em relatório executivo
- Gerar matriz de concorrência
- Produzir output em Markdown (para diretoria) e JSON estruturado (para integração)

**Output:**
```
output/
  report_<request_id>.md   ← Executive report (Markdown)
  report_<request_id>.json ← Structured intelligence (JSON)
```

---

## 4. Requisitos Técnicos

| Item | Spec |
|------|------|
| Python | 3.10+ |
| Pydantic | v2.x |
| HTTP/Scraping | `httpx`, `beautifulsoup4` |
| AI Gateway | Gemini 2.5 Flash via REST (`generativelanguage.googleapis.com/v1beta`) |
| Config | `python-dotenv` — GEMINI_API_KEY via `.env` |
| CLI | `typer` — `python main.py run --request procurement_request.json` |
| Logging | `structlog` — JSON-structured logs |
| Testing | `pytest` + `pytest-asyncio` |

---

## 5. Regras de Negócio

1. **Completeness Gate:** `data_completeness_score < 0.7` → `@judge` bloqueia e força retry
2. **Price Alert:** `price_delta_pct > 20%` acima da média → decision automaticamente `"pending_review"`
3. **Feature Gap:** qualquer `required_feature` ausente no fornecedor → inclui em `missing_features`; 3+ ausentes → `"rejected"`
4. **Graceful Degradation:** scraping bloqueado → `CompetitorProfile.scraping_errors` preenchido; `data_confidence = "low"` para esse perfil
5. **Retry Cap:** máximo 3 iterações do loop `@judge` → `@researcher`; na exaustão, emite `PipelineError` com log JSON completo

---

## 6. Critérios de Aceite (QA Gates)

- [ ] `python main.py run --request sample_request.json` executa o pipeline completo sem intervenção humana
- [ ] Se um site bloquear scraping, o sistema loga o erro e continua com os demais fornecedores (não quebra)
- [ ] Dados inválidos do `@researcher` são rejeitados pelo `@judge` e acionam re-run automático
- [ ] `report_<id>.json` passa validação com `pydantic.TypeAdapter(FinalReport).validate_json()`
- [ ] Todos os SKILL.md documentam: propósito, input schema, output schema, system prompt, restrições operacionais

---

## 7. Estrutura de Arquivos do Projeto

```
projeto-sales-agents/
├── .agents/
│   └── skills/
│       ├── researcher/SKILL.md
│       ├── judge/SKILL.md
│       ├── procurement-analyst/SKILL.md
│       └── synthesizer/SKILL.md
├── .planning/
│   ├── PROJECT.md
│   ├── SPEC.md
│   ├── REQUIREMENTS.md
│   ├── ROADMAP.md
│   └── STATE.md
├── agents/
│   ├── base.py          ← BaseAgent ABC
│   ├── researcher.py
│   ├── judge.py
│   ├── procurement.py
│   └── synthesizer.py
├── models/
│   ├── research.py      ← Pydantic schemas (researcher chain)
│   ├── procurement.py   ← Pydantic schemas (procurement chain)
│   └── report.py        ← Pydantic schemas (final report)
├── core/
│   ├── orchestrator.py  ← Pipeline controller
│   ├── gemini_client.py ← Gemini REST client
│   └── logger.py        ← structlog config
├── output/              ← Generated reports (gitignored)
├── tests/
├── main.py              ← CLI entrypoint (typer)
├── requirements.txt
├── .env.example
└── README.md
```

---
*SPEC approved — proceed to ROADMAP.md*
