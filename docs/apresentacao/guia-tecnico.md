# Guia técnico do assistente de dívidas e crédito

Material de estudo para entender o projeto de ponta a ponta e conseguir explicá-lo
numa apresentação ou numa entrevista. Para cada conceito há quatro partes:

1. **O conceito:** a teoria, independente do projeto.
2. **Como está no projeto:** onde fica e trechos do código.
3. **Por que assim:** a decisão e a alternativa descartada.
4. **Perguntas de entrevista:** com respostas curtas.

Os caminhos seguem o formato `arquivo:linha`. As linhas são as do commit em que
este guia foi escrito; se o código mudar, procure pelo nome da função.

---

## 0. O projeto em 60 segundos (pitch)

> Construí um assistente de dívidas e crédito para o consumidor leigo. É um grafo
> em LangGraph com guardrails de entrada e saída, um agente com ferramentas e RAG
> agêntico sobre leis e normas oficiais. As contas e as taxas de mercado vêm de um
> servidor MCP que escrevi, com dados do Banco Central; as datas vêm de um servidor
> MCP da comunidade. Tarefas de várias etapas, como montar um plano de quitação,
> ficam em skills carregadas sob demanda. Há memória por conversa (checkpointer) e
> entre conversas (perfil persistente). Avaliei com 10 casos de ponta a ponta,
> com checagens determinísticas e um juiz LLM, e comparei dois modelos em acerto,
> latência e custo.

Em números:

| | |
|---|---|
| Nós do grafo | 8 |
| Ferramentas no servidor próprio | 9 |
| Normas no corpus | 11 |
| Notas curadas | 9 |
| Trechos no índice | 273 |
| Skills | 2 |
| Testes automáticos | 159 |
| Avaliação | 10/10 com `gemini-3.6-flash` e 8/10 com `gemini-3.5-flash-lite` |

---

## 1. Arquitetura

```text
Navegador ── Streamlit (app.py) ── AssistantRunner (thread + event loop próprio, credito/runner.py)
                                        │
                                        ▼
                              Grafo LangGraph (credito/graph.py)
             ┌──────────────┬───────────┴───────────┬──────────────────────┐
             ▼              ▼                       ▼                      ▼
        Gemini API     MCPAdapter (stdio)      Chroma (data/chroma)    AsyncSqliteSaver
   (agente, guardas,   ├─ credit_server.py     embeddings Gemini        (data/checkpoints.db)
    avaliador,         │   └─ SQLite perfis + API do BCB
    reescritor)        └─ uvx mcp-server-time
```

- **Processos:** o app Streamlit e, como subprocessos, os dois servidores MCP, que falam com o cliente por stdin/stdout. O grafo roda numa thread do app com seu próprio *event loop*.
- **Dados:**
  - `data/profiles.db`: perfis (usuários, dívidas, planos), escrito só pelo servidor MCP;
  - `data/checkpoints.db`: histórico das conversas;
  - `data/chroma/`: índice vetorial;
  - `data/docs/`: corpus limpo, versionado;
  - `data/rates_cache.json`: última mediana do BCB por modalidade.
- **Injeção de dependência:** o grafo não sabe que é Gemini nem MCP. Recebe tudo num `Deps` (`credito/graph.py:39`). Por isso os testes usam modelos e ferramentas falsos, e `credito/assistant.py` monta a versão real.

**Perguntas**
- *Por que o grafo não importa o Gemini direto?* Para poder testar sem rede e sem chave, e trocar o modelo por configuração (`CREDITO_MODEL`). É inversão de dependência: o grafo depende de interfaces (um chat model com `bind_tools`, runnables de saída estruturada, `BaseTool`).
- *Onde ficam os dados do usuário?* No SQLite do servidor MCP. O grafo só os vê pelas ferramentas `credito_*`. O painel da interface lê o mesmo arquivo direto, só para exibição.

---

## 2. LangGraph: estado, nós, arestas e `Command`

### O conceito

- **Grafo de estado:** o LangGraph modela um agente como uma máquina de estados. Há um **estado** compartilhado (um dict tipado), **nós** que recebem o estado e devolvem *atualizações parciais*, e **arestas** que dizem o próximo nó.
- **Reducer:** cada campo do estado tem um reducer, que define como a atualização se combina com o valor anterior. O padrão é substituir. Em `messages`, o reducer é o `add_messages`: ele acrescenta mensagens e **substitui uma mensagem que tenha o mesmo `id`**. Esse detalhe é usado várias vezes no projeto.
- **Rotas:**
  - **Aresta fixa:** `add_edge(a, b)`.
  - **Aresta condicional:** `add_conditional_edges(a, func, destinos)`. A função lê o estado e devolve o nome do próximo nó.
  - **`Command(update=..., goto=...)`:** o próprio nó atualiza o estado e escolhe o destino de uma vez. É útil quando a decisão nasce dentro do nó, por exemplo depois de chamar um classificador.
- **Compilação:** `compile(checkpointer=...)` gera um runnable que salva o estado a cada passo, por `thread_id`.

### Como está no projeto

Estado (`credito/graph.py:27-35`, comentários acrescentados aqui):
```python
class CreditState(MessagesState):
    user_id: str
    owner: str | None          # dono da conversa (fixado no 1º turno)
    tool_rounds: int           # rodadas de ferramentas no turno (limite 8)
    profile: str               # JSON do perfil, lido do servidor MCP
    rewrites: int              # reescritas da busca no turno (limite 2)
    retry_query: str | None    # consulta reescrita para a próxima busca
    search_exhausted: bool     # a busca não achou nada útil
    blocked: str | None        # categoria barrada pela guarda de entrada
```
`MessagesState` já traz `messages: Annotated[list, add_messages]`.

O laço principal:
- `agent` → `after_agent` (`credito/graph.py:174`): se a última mensagem tem `tool_calls`, vai para `tools`; senão, para `guard_output`.
- `tools` → `after_tools` (`credito/graph.py:177`): se alguma chamada foi `search_norms`, vai para `grade`; senão, volta ao `agent`.

`Command` em dois nós:
- **`guard_input`** (`credito/graph.py:78`): decide entre `refuse` e `load_profile`.
- **`grade`** (`credito/graph.py:146`): decide entre voltar ao `agent` (trechos bons ou busca esgotada) e ir para `rewrite`.

Substituição por id, usada três vezes:
1. `guard_input` troca a mensagem do usuário pela versão mascarada: `HumanMessage(masked, id=message.id)`.
2. `refuse` troca a mensagem barrada pelo marcador `[mensagem bloqueada pelo guardrail]`.
3. `guard_output` troca a resposta perigosa pela segura: `AIMessage(SAFE_OUTPUT, id=answer.id)`.

Sem o mesmo id, o histórico teria as duas versões, e a original, perigosa ou com CPF, continuaria indo para o modelo.

### Por que assim

- **Grafo próprio em vez de `create_agent`:** o enunciado exige. Mas há motivo técnico: o `create_agent` dá só o laço agente ⇄ ferramentas. As guardas antes e depois, a carga do perfil e o desvio para avaliar a busca são etapas que precisam ficar visíveis e controláveis.
- **`Command` versus aresta condicional:** use `Command` quando o nó precisa decidir e atualizar o estado ao mesmo tempo. Use a aresta condicional quando a decisão é só uma leitura do estado. É o mesmo padrão dos notebooks 09 e 12 da disciplina.

### Perguntas
- *O que é um reducer?* É a função que combina a atualização de um nó com o valor anterior do campo. Sem reducer, o valor é substituído; com `add_messages`, mensagens são acrescentadas, e uma mensagem de mesmo id substitui a anterior.
- *Como você evita laço infinito entre agente e ferramentas?* O LangGraph tem um `recursion_limit`, mas o padrão é alto. O grafo conta `tool_rounds`: depois de 8 rodadas, o nó `agent` chama o modelo **sem** ferramentas e com uma instrução para responder já (`credito/graph.py:111-121`).
- *Por que a pergunta corrente é a última `HumanMessage` e não `messages[0]`?* Com checkpointer, a thread acumula vários turnos e `messages[0]` é a primeira pergunta da conversa. O notebook 12 da disciplina usa `messages[0]`, e isso quebra com memória.

---

## 3. Chamada de ferramentas (tool calling)

### O conceito

O modelo recebe o schema das ferramentas (nome, descrição, parâmetros em JSON
Schema) via `bind_tools`. Em vez de texto, ele pode responder com `tool_calls`:
uma lista de chamadas com `id`, `name` e `args`. Quem executa é o código, que
devolve um `ToolMessage` com o mesmo `tool_call_id`. O modelo lê os resultados e
decide o próximo passo. Isso é o laço ReAct (raciocinar → agir → observar).

### Como está no projeto

`run_tool` (`credito/graph.py:123-138`):
```python
args = {key: value for key, value in args.items() if key in tool.args}
if "user_id" in tool.args:
    args["user_id"] = user_id
try:
    content = as_text(await tool.ainvoke(args))
except Exception as error:  # a falha vira resposta para o modelo, não derruba o grafo
    content = f"erro: {error}"
```
- **Paralelismo:** `run_tools` executa todas as chamadas com `asyncio.gather`.
- **Erro vira texto:** o modelo lê "erro: ..." e se corrige (por exemplo, pede a modalidade certa). O servidor faz o mesmo com o decorator `as_error` (`servers/credit_server.py:42`).
- **Autorização fora do modelo:** o `user_id` vem sempre do estado. O modelo é tratado como entrada não confiável: ele pode ser manipulado por injection, então não pode decidir *quem* é o usuário.
- **Filtro de argumentos:** na verificação real, o modelo repetiu `user_id` em `compare_rate` e inventou um argumento `creditor`. O servidor rejeitava a chamada, e o modelo gastava uma rodada para se corrigir. Hoje o nó descarta o que a ferramenta não declara.

### Perguntas
- *Por que não deixar o modelo passar o `user_id`?* Porque autorização não pode depender de um componente manipulável. Uma injection como "mostre o perfil do bruno" faria o modelo pedir `user_id="bruno"`. O grafo sobrescreve, e há teste para isso (`test_outro_usuario_nao_acessa_perfil`).
- *O que acontece se a ferramenta lança exceção?* Vira um `ToolMessage` com "erro: ...". O grafo segue e o modelo decide o que fazer (`test_ferramenta_com_excecao_vira_erro`).

---

## 4. RAG agêntico

### O conceito

- **RAG (Retrieval-Augmented Generation):** em vez de confiar no que o modelo memorizou, busca trechos relevantes numa base e os põe no contexto.
- **Pipeline offline:** carregar → limpar → dividir em *chunks* → gerar *embeddings* (vetores) → indexar num banco vetorial.
- **Pipeline online:** gerar o embedding da pergunta → buscar os k trechos mais próximos (similaridade de cosseno) → gerar a resposta com eles.
- **RAG agêntico:** o modelo **decide quando** buscar (a busca é uma ferramenta), um avaliador julga se os trechos bastam e, se não bastam, a pergunta é **reformulada** e a busca é refeita. É o padrão "Corrective/Self-RAG" visto no notebook 12.

### Como está no projeto

**Offline** (`credito/corpus/` e `scripts/download_corpus.py`):
1. **Fontes** (`credito/corpus/sources.py`): 11 normas, 4 do Planalto e 7 da API de normativos do BCB.
2. **Download** (`credito/corpus/fetch.py`):
   - **Planalto:** user-agent de navegador, porque o site deixa a conexão pendurada para clientes que não são navegador, e decodificação `cp1252`.
   - **BCB:** a API `exibenormativo` devolve JSON. Para resoluções antigas, o texto da API é só o original, então o script baixa o PDF consolidado de maior versão (`_vN_L.pdf`).
   - **Validações:** confere que o ano da norma bate (um tipo errado devolve outra norma de mesmo número) e falha se a norma consta como revogada.
3. **Limpeza** (`credito/corpus/parse.py:15`): um `HTMLParser` descarta o texto riscado, isto é, revogado. O Planalto marca revogação com `<strike>`, `<s>` ou CSS `text-decoration: line-through`. O CSS foi um bug real: o corpus dizia que o mínimo existencial era "25% do salário mínimo", a redação revogada, e não R$ 600.
4. **Divisão por artigo** (`split_articles`, `credito/corpus/parse.py:65`): regex `^Art\.` com normalização (`1°`, `1º` e `1` viram `1º`; o sufixo `2º-A` é preservado).
5. **Notas curadas** (`data/docs/notas/*.md`): textos curtos, com fontes no cabeçalho, para o que o texto oficial não reflete. Exemplos: a decisão do STF de 2026 sobre o mínimo existencial e a MP que caducou.

**Índice** (`credito/rag.py`):
- `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)` aplicado **dentro** de cada artigo. Cada pedaço recebe o rótulo `[CDC art. 54-A]` no início (`credito/rag.py:58`).
- **Id estável com hash do conteúdo**, `cdc:54-A:0:<sha256[:12]>`. `build_vector_store` (`credito/rag.py:94`) compara os ids do índice com os do corpus: remove os que sumiram ou mudaram e adiciona só os que faltam, em lotes de 80, esperando 60 s quando a API devolve 429.
- Chroma com `hnsw:space = cosine` e embeddings `gemini-embedding-001` com 768 dimensões.

**Online:**
- `search_norms` (`credito/rag.py:138`) devolve os 4 trechos mais próximos, já rotulados.
- Nó `grade`: `grade_chunks` usa saída estruturada `GradeDocuments(binary_score: "sim" | "nao")`.
- Nó `rewrite`: `rewrite_query` reformula com os termos técnicos das normas. A consulta nova entra no **system prompt** como `retry_query`, e não como uma mensagem falsa do usuário, para não poluir o histórico.
- Depois de 2 reescritas sem sucesso, `search_exhausted=True` e o prompt manda dizer que não encontrou e **não citar fonte**.

### Por que assim

- **Divisão por artigo:** o artigo é a unidade de citação jurídica. Cortar no meio de um artigo produz trechos sem sentido e sem fonte clara.
- **Rótulo dentro do texto do trecho:** o modelo cita exatamente o que vê. Se a fonte ficasse só nos metadados, o modelo não a veria.
- **Notas curadas:** o texto compilado do Planalto ainda diz que o consignado fica fora do mínimo existencial. Sem a nota, o RAG responderia com uma regra já derrubada pelo STF. Em domínio jurídico, "o documento oficial" nem sempre é "a regra vigente".
- **Id com hash:** com o id antigo (`fonte:artigo:k`), atualizar o corpus não reindexava nada, porque o id já existia. O índice continuaria servindo texto desatualizado como se fosse lei.

### Perguntas
- *Qual a diferença entre RAG e RAG agêntico?* No RAG simples, toda pergunta passa por uma busca fixa. No agêntico, o modelo decide se busca, há avaliação dos resultados e a busca é refeita com uma pergunta melhor.
- *Como você mede se o RAG funciona?* Nos casos 1 e 2 da avaliação (cheque especial e mínimo existencial), com checagem de valores na resposta e juiz. E na verificação manual de buscas reais ("teto do rotativo" traz a nota e o art. 28 da Lei 14.690 no topo).
- *O que é similaridade de cosseno?* É o cosseno do ângulo entre dois vetores: mede a direção e ignora o tamanho. Textos de significado parecido têm embeddings com direção parecida.
- *Por que `chunk_overlap`?* Para que uma frase cortada na fronteira entre dois pedaços apareça inteira em pelo menos um deles.

---

## 5. MCP (Model Context Protocol)

### O conceito

- **O que é:** um protocolo aberto (JSON-RPC) para expor **ferramentas**, **recursos** e **prompts** a aplicações com LLM. A aplicação (*host*) usa um **cliente** MCP que conversa com **servidores** MCP.
- **Transportes:** `stdio` (o servidor é um subprocesso; as mensagens vão por stdin e stdout) ou HTTP.
- **Vantagem:** a ferramenta é escrita uma vez e qualquer host compatível usa: Claude Desktop, IDEs, outros agentes.

### Como está no projeto

**Servidor próprio** (`servers/credit_server.py`, FastMCP):
```python
@mcp.tool()
@as_error
def compare_rate(modality: str, monthly_rate: float) -> str:
    """Compara a taxa do cliente (% ao mês) com a mediana do mercado na modalidade, segundo o BCB."""
```

Tem 9 ferramentas:
- `market_rate` e `compare_rate`: dados do BCB;
- `simulate_payoff`, `simulate_installments` e `simulate_portability`: calculadoras;
- `get_profile`, `save_debt`, `remove_debt` e `save_plan`: perfil.

Detalhes:
- O docstring vira a descrição da ferramenta que o modelo lê, por isso ele diz as unidades (% ao mês, R$).
- A fábrica `build_server(db_path, rates)` (`servers/credit_server.py:65`) recebe as dependências. Os testes usam um banco temporário e um cliente de taxas falso, com o `fastmcp.Client` em memória.
- O banco vem de `CREDITO_DB` (`db_path()`, `servers/credit_server.py:60`). A avaliação passa um banco temporário pela chave `env` da config.

**Servidor da comunidade:** `mcp-server-time`, iniciado por `uvx`. Dá a data de hoje no fuso de Fortaleza, para transformar "10 parcelas a partir do mês que vem" em "termina em setembro de 2027".

**Cliente** (`credito/assistant.py:24-44` e `:71`):
```python
adapter = MCPAdapter({"mcpServers": mcp_servers(profiles_db)})
async with adapter, AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
    tools = [*await adapter.list_tools(), *local_tools]
```
O `langchain.mcp.MCPAdapter`, o mesmo do repositório da disciplina, transforma cada ferramenta MCP numa `StructuredTool` do LangChain, com o prefixo do servidor: `credito_compare_rate`, `time_get_current_time`.

**Dados do BCB** (`credito/rates.py`): a API `TaxasJurosDiariaPorInicioPeriodo` traz a taxa de cada banco por modalidade e semana. O código:
1. pega o período mais recente;
2. lê as taxas de todos os bancos nesse período;
3. calcula a **mediana**.

Um bug real: o OData do BCB rejeita espaço codificado como `+`, que é o padrão do httpx. A `build_url` (`credito/rates.py:44`) usa `%20`.

### Por que assim

- **MCP em vez de funções Python locais:** o enunciado exige, mas faz sentido no projeto. Calculadoras, dados de mercado e perfil são um serviço reutilizável (outro agente ou o Claude Desktop poderia usar), e o processo separado isola o acesso ao banco de perfis.
- **Mediana em vez de média:** um banco com taxa fora da curva distorce a média. A mediana representa "o banco típico".
- **Ferramentas que o modelo erraria sozinho:** juros compostos, taxa de mercado atual e memória persistente. A regra é "números só por ferramenta".

### Perguntas
- *O que o MCP resolve?* Padroniza como expor ferramentas e contexto a LLMs. Sem ele, cada framework tem seu formato de ferramenta; com ele, um servidor serve qualquer host.
- *stdio ou HTTP?* stdio para servidores locais, que são subprocessos sem rede nem autenticação. HTTP para servidores remotos ou compartilhados.
- *Por que o servidor devolve "erro: ..." em vez de lançar?* Para o modelo ler o erro e se corrigir. Uma exceção viraria um erro de protocolo menos informativo.

---

## 6. Skills (carregamento sob demanda)

### O conceito

- **O que é:** uma skill é um pacote de instruções para uma tarefa de várias etapas, em `SKILL.md`, com frontmatter `name` e `description`.
- **Divulgação progressiva:** o system prompt traz só o **catálogo** (nome e descrição, poucas linhas por skill). Quando o pedido combina, o agente chama `load_skill` e só então recebe as instruções completas. O contexto fica enxuto, e dá para ter muitas skills sem inchar o prompt.

### Como está no projeto

- `credito/skills.py`:
  - `load_catalog` monta o catálogo;
  - `make_load_skill_tool` cria a ferramenta `load_skill(name)`, que devolve o corpo do `SKILL.md`, ou um erro com os nomes válidos.
- O catálogo entra no prompt (`credito/prompts.py`), junto com a regra "chame `load_skill` antes de qualquer outra ferramenta".
- **`skills/plano-de-quitacao`:**
  1. perfil;
  2. `compare_rate` em cada dívida;
  3. orçamento;
  4. avalanche ou bola de neve;
  5. `simulate_payoff`;
  6. `time_get_current_time` para datas;
  7. oferecer `save_plan`.
- **`skills/avaliar-portabilidade`:**
  1. `market_rate`;
  2. `simulate_portability`;
  3. `search_norms` sobre a Res. CMN 5.057;
  4. passo a passo do pedido, sem garantir aprovação.

A revisão pegou um defeito: a skill de plano mandava "pagar o mínimo" nas outras dívidas, mas o perfil não tem esse dado, e o modelo inventaria o valor. Agora a skill manda calcular a parcela com ferramenta ou perguntar ao usuário.

### Por que assim

- **Skill, ferramenta ou prompt?** A ferramenta faz uma coisa: uma conta, uma consulta. A skill ensina uma **sequência** de ferramentas com critério (ordem, quando perguntar, o que não prometer). Pôr tudo no prompt fixo gastaria contexto em todo turno, mesmo em "oi".

### Perguntas
- *Como o modelo sabe que skill usar?* Pela descrição no catálogo, que diz o que a skill faz e "Use quando...". Escrever bem essa linha é o que faz a skill ser escolhida.
- *Qual a diferença entre skill e subagente?* A skill é instrução carregada no mesmo agente e no mesmo contexto. O subagente é outro agente, com contexto próprio. Para tarefas curtas que usam as mesmas ferramentas, a skill é mais barata.

---

## 7. Memória: curto prazo e longo prazo

### O conceito
- **Curto prazo (conversa):** o histórico de mensagens da thread. No LangGraph, quem guarda é o **checkpointer**: salva o estado depois de cada passo, por `thread_id`. Ao invocar de novo com o mesmo `thread_id`, o estado é restaurado.
- **Longo prazo (entre conversas):** fatos que sobrevivem à conversa, como as dívidas do usuário. Ficam num armazenamento próprio, consultado quando necessário.

### Como está no projeto
- **Checkpointer:** `AsyncSqliteSaver` (`credito/assistant.py:72`). A interface guarda um `thread_id` por usuário em `st.session_state.threads`; "Nova conversa" gera um uuid novo, e a conversa antiga continua no banco.
- **Perfil:** SQLite do servidor MCP (`credito/profiles.py`), com as tabelas `users`, `debts` e `plans`.
  - `save_debt` faz **upsert** por `(user_id, kind, creditor)`; o credor é comparado sem diferenciar maiúsculas (`COLLATE NOCASE`). Contar a mesma dívida duas vezes atualiza o saldo em vez de duplicar.
  - `get_profile` devolve `total_balance` calculado pelo servidor. Na verificação real, o modelo somava de cabeça e listava errado.
  - O nó `load_profile` lê o perfil **a cada turno**, então uma dívida salva agora aparece no turno seguinte e em qualquer conversa nova.
- **Conversa presa ao dono:** o campo `owner` é fixado no primeiro turno. Se outro usuário usar o mesmo `thread_id`, recebe a recusa `outro_usuario` e não vê o histórico.

### Perguntas
- *Por que não guardar as dívidas só no histórico da conversa?* Porque numa conversa nova o histórico começa vazio, e porque histórico longo custa tokens. O perfil é estruturado, pequeno e vem pronto no prompt.
- *O que acontece com conversas concorrentes?* Cada sessão do navegador tem seus `thread_id`. As corrotinas rodam no mesmo loop, e o aiosqlite serializa as escritas.

---

## 8. Guardrails

### O conceito
Guardrails são controles em volta do modelo que reduzem riscos. As camadas
típicas são:
1. **validação e sanitização da entrada** (dados sensíveis, injection);
2. **restrição do que as ferramentas podem fazer** (privilégio mínimo);
3. **verificação da saída** (políticas do domínio).

Nenhuma camada sozinha basta. Isso é defesa em profundidade.

### Como está no projeto
| Camada | Implementação | Arquivo |
|---|---|---|
| Dados sensíveis | regex de CPF e cartão **antes** de qualquer modelo; a mensagem é trocada pelo mesmo id | `credito/guards.py:10-16`, `credito/graph.py:87-89` |
| Injection, fora do escopo, dados de terceiros | classificador com saída estruturada `InputVerdict(category: Literal[...])`, prompt com regras e exemplos | `credito/guards.py:19, 36` |
| Mensagem barrada fora do contexto futuro | `refuse` troca a mensagem pelo marcador | `credito/graph.py:95` |
| Autorização | `user_id` do estado; `remove_debt` com `WHERE id=? AND user_id=?`; conversa presa ao dono | `credito/graph.py:131-133`, `credito/profiles.py:136` |
| Saída | `OutputVerdict(investment_advice, approval_guarantee)` troca a resposta pela segura, e a regex mascara a resposta | `credito/guards.py:28, 62`, `credito/graph.py:162` |
| Laço descontrolado | `MAX_TOOL_ROUNDS = 8` | `credito/graph.py:21` |

- **A linha de política:** definida **antes** dos prompts. Conselho sobre dívida é o produto: ordem de pagamento, portabilidade, usar a reserva para quitar. Recomendar ação, fundo ou cripto e garantir aprovação de crédito é barrado.
- **Falso positivo real:** a guarda barrava "quanto eu devo no total?" como pedido de dados de terceiros. A correção foi dizer no prompt que o usuário está logado e tem perfil próprio, e dar exemplos (*few-shot*) de `ok` e de cada categoria.

### Limites que vale admitir numa entrevista
- **Injection indireta não é filtrada.** Uma instrução escondida dentro de um trecho do RAG ou de uma resposta de ferramenta não passa por guarda. Aqui o risco é baixo, porque o corpus é curado e as ferramentas são minhas; com fontes abertas seria preciso filtrar também os resultados de ferramenta, como no notebook 14 com `@wrap_tool_call`.
- **Regex imperfeita:** a de cartão também mascara datas com hífen e telefones, e a de CPF, qualquer sequência de 11 dígitos.
- **Classificador LLM não é determinístico:** um ataque bem escrito pode passar. Por isso as defesas estruturais (`user_id` fora do modelo) importam mais que o classificador.

### Perguntas
- *Por que mascarar antes do classificador e não depois?* Para que nenhum modelo, nem o da guarda, receba o dado sensível. Mascarar é barato e determinístico.
- *Por que os guardrails são nós e não middleware?* O enunciado pede nós, e no grafo eles ficam explícitos no diagrama e no histórico (a recusa é uma mensagem). O notebook 14 usa middleware do `create_agent`, que esconde o fluxo.

---

## 9. Prompt e saída estruturada

- **System prompt** (`credito/prompts.py`): seções `# Papel`, `# Regras`, `# Skills disponíveis` e `# Perfil do usuário`, no padrão da disciplina.
  - As regras que mais importam: números só por ferramenta, citar a fonte exatamente como veio, salvar dívida nova e dizer o que salvou, chamar `load_skill` primeiro.
  - O prompt é **dinâmico**: ganha uma seção quando há `retry_query` ou `search_exhausted`, e uma nota de limite quando acabam as rodadas de ferramentas.
- **Saída estruturada:** `model.with_structured_output(PydanticModel)` faz o modelo devolver JSON validado. `Literal["sim", "nao"]` e `Literal["ok", "injection", ...]` restringem as respostas a categorias fechadas. Usado em três lugares: guardas, avaliador da busca e juiz da avaliação.
- **Pergunta típica:** *por que saída estruturada no classificador?* Porque o código precisa decidir uma rota. Texto livre ("acho que é injection...") exigiria parsing frágil.

---

## 10. O domínio financeiro (as contas)

- **Tabela Price** (`credito/calc.py:39`): parcela fixa `PMT = P · i / (1 − (1 + i)^−n)`. Com `i = 0`, a parcela é `P / n`. Exemplo: R$ 1.000 a 5% ao mês em 12× dá R$ 112,83. Esse valor é teste.
- **Quitação com parcela fixa** (`credito/calc.py:49`): simulação mês a mês; juros = saldo × i; a última parcela é parcial. Recusa a parcela que não cobre os juros do mês (a dívida nunca acabaria) e corta em 600 meses.
- **Portabilidade** (`credito/calc.py:67`): compara a Price com a taxa atual e com a nova, no mesmo prazo restante. Economia = (parcela atual − parcela nova) × n. Se der negativo, a resposta diz "custo adicional; portar não compensa".
- **Regras jurídicas usadas:**
  - **Rotativo:** juros e encargos limitados a 100% do valor original (Lei 14.690/2023, art. 28; Res. CMN 5.112/2023). O saldo só fica no rotativo até o vencimento seguinte (Res. 4.549).
  - **Cheque especial:** até 8% ao mês, sem tarifa pelo limite (Res. 4.765; ADI 6.407).
  - **Portabilidade:** Res. CMN 5.057/2022. O cliente não paga pela transferência, e o novo contrato não pode ter valor maior que o saldo nem prazo maior que o restante.
  - **Mínimo existencial:** R$ 600 (Decreto 11.150). Desde abril de 2026 o consignado entra no cálculo (STF).

---

## 11. Assíncrono e Streamlit

### O problema
O grafo é **assíncrono**, porque as ferramentas MCP são assíncronas. Os servidores
MCP precisam ficar **abertos** entre as mensagens. Já o Streamlit **reexecuta o
script inteiro** a cada interação, de forma síncrona.

### A solução (`credito/runner.py`)
- **Thread de fundo:** o `AssistantRunner` cria uma thread com um event loop próprio. Nela, abre o `open_assistant()` uma única vez (servidores MCP, checkpointer, índice) e fica esperando um sinal de parada.
- **Ponte síncrona:** `ask()` e `history()` são síncronos. Enviam a corrotina para o loop da thread com `asyncio.run_coroutine_threadsafe` e esperam o resultado com timeout:
  ```python
  future = asyncio.run_coroutine_threadsafe(coroutine_factory(self._assistant.graph), self._loop)
  try:
      return future.result(self.timeout)
  except TimeoutError:
      future.cancel()  # sem isso o turno seguiria rodando e disputaria a mesma thread com o próximo
  ```
- **Ciclo de vida no app:** `@st.cache_resource(on_release=lambda r: r.close())` (`app.py:28`) guarda o runner entre reexecuções e o fecha quando o cache é descartado, para não deixar processos MCP órfãos. Se a abertura falhar, por exemplo com um 429, o app limpa o cache para tentar de novo.
- **Testabilidade:** a lógica da tela (turnos, painel) fica em `credito/ui.py`, sem Streamlit.

### Perguntas
- *Por que não `asyncio.run()` a cada mensagem?* Porque fecharia o loop e, com ele, as sessões MCP. Os servidores seriam reabertos a cada pergunta, o que custa segundos.
- *O que acontece se a resposta demora demais?* `future.cancel()` cancela a corrotina no loop e o usuário vê "o assistente demorou mais de 180 s". Sem o cancelamento, o turno seguiria rodando e brigaria com o próximo na mesma thread.

---

## 12. Testes

- **TDD:** cada comportamento nasceu de um teste que falhava. Bugs achados à mão (o `+` no BCB, o texto riscado com CSS, o argumento inventado pelo modelo) viraram testes antes da correção.
- **159 testes sem rede e sem chave:**
  - **Modelo falso:** `tests/fakes.py:ScriptedModel` devolve respostas roteirizadas e guarda o que recebeu. Assim dá para afirmar "o prompt do agente continha o perfil" ou "a mensagem barrada não chegou ao modelo".
  - **Classificadores falsos:** `RunnableLambda` devolvendo vereditos fixos.
  - **Servidor MCP:** `fastmcp.Client(server)` em memória.
  - **App:** `streamlit.testing.v1.AppTest` com o runner e o cliente de taxas trocados por `monkeypatch`.
- **Testes marcados `network`:** batem no Planalto, no BCB e no assistente real. Ficam fora do `pytest` padrão.
- **O que os testes não provam:** que o classificador real pega um ataque. Isso é papel da avaliação com o modelo real.

**Pergunta:** *como testar um agente se o LLM não é determinístico?* Separando o que é código (roteamento, autorização, guardas por regex, cálculos), que se testa com modelos falsos e de forma determinística, do que é comportamento do modelo, que se mede com avaliação de ponta a ponta.

---

## 13. Avaliação de LLM

- **Casos** (`evals/cases.py`): 10, cada um com entrada, esperado, ferramentas e skills esperadas e **checagens determinísticas**: valor na resposta, recusa exata, ferramenta num turno, CPF fora do histórico.
- **Execução** (`evals/run.py`): cada caso roda num banco e num checkpointer temporários a partir do seed. Mede:
  - **latência:** só os turnos, sem abrir servidores e índice;
  - **tokens:** de todas as chamadas, com `UsageMetadataCallbackHandler` passado no config. O LangChain propaga callbacks por contextvars até as chamadas dentro dos nós e o `asyncio.to_thread` copia o contexto.
- **Juiz LLM** (`gemini-3.8-flash`): `Verdict(correct, reason)`. O caso só passa se ferramentas, checagens e juiz concordarem. Juiz que falha marca "não julgado", nunca aprovado.
- **Resultado:** 3.6-flash 10/10 (18,8 s, US$ 0,149 nos 10 casos) contra 3.5-flash-lite 8/10 (5,5 s, US$ 0,030).
- **Lições, ótimas para entrevista:**
  - **O juiz foi leniente.** Aprovou as duas respostas erradas do lite; quem pegou foram as checagens determinísticas. LLM-as-judge sozinho não basta, especialmente da mesma família do modelo avaliado.
  - **Uma rodada é pouco.** n = 1 com modelo não determinístico mostra tendência, não medida estável.
  - **O caso precisa testar o que diz testar.** O caso 7 (memória entre turnos) foi reescrito duas vezes: na primeira versão o turno 1 já pedia a conta; na segunda a checagem penalizava o modelo por ser proativo.
  - **Não afrouxar o teste depois de ver o resultado.** O caso 2 cobra R$ 600 e foi mantido, mesmo com o lite reprovando.

---

## 14. Bugs reais e o que ensinaram

| Bug | Sintoma | Causa | Correção | Lição |
|---|---|---|---|---|
| Texto revogado no corpus | "mínimo existencial = 25% do salário mínimo" | Planalto marca revogação com CSS, não só `<strike>` | parser que pula `line-through` | Olhe o dado limpo, não só o código de limpeza |
| BCB com HTTP 400 | consulta OData falhava | httpx codifica espaço como `+` | `urlencode(quote_via=quote)` | Serviços públicos têm peculiaridades; teste com a API real |
| Planalto pendurado | timeout de 60 s | o site trava clientes que não são navegador | user-agent de navegador | — |
| Índice desatualizado | corpus novo sem efeito | id sem hash do conteúdo | id com hash, remoção dos ids antigos | Atualização é parte do design do RAG |
| Argumento inventado | servidor rejeitava a chamada | modelo repetia `user_id`, inventava `creditor` | filtro pelos argumentos declarados | Trate a saída do modelo como entrada não confiável |
| Falso positivo da guarda | "quanto eu devo?" recusado | classificador sem saber que há login | contexto e *few-shot* no prompt | Guardas também precisam de avaliação |
| Soma errada | lista incompleta, total certo | modelo somando de cabeça | `total_balance` no servidor | Números por ferramenta |
| Mensagem barrada voltando | injection no contexto do turno seguinte | `refuse` deixava a mensagem no histórico | substituir pelo marcador, com o mesmo id | Guardrail precisa cuidar do estado, não só da resposta |
| Outro usuário na conversa | histórico de um vazava para outro | thread sem dono | campo `owner` e recusa | Autorização por sessão |

---

## 15. Trade-offs e próximos passos

- **Custo contra qualidade:** o 3.6-flash custa 5× e leva 3,4× mais tempo que o lite. Para produção, um roteamento por complexidade faria sentido: lite para perguntas simples e de RAG, 3.6 para skills.
- **Guardas com LLM:** cada turno faz duas chamadas extras (entrada e saída). Uma alternativa mais barata seria um classificador pequeno ou regras para os casos óbvios.
- **Contingência:** hoje um 429 numa guarda derruba o turno. O ideal seria retry com backoff e uma resposta de contingência.
- **Follow-up na busca:** o avaliador e o reescritor só veem a última pergunta. "E no consignado?" perde o contexto. Daria para passar as duas últimas trocas.
- **Observabilidade:** o notebook 15 mostra Langfuse. Ligar o tracing daria custo e latência por nó em produção.
- **Corpus vivo:** em 1º/7/2027 cinco normas mudam de situação. O script de download e o índice com hash já permitem atualizar, mas falta agendar.

---

## 16. Perguntas rápidas de entrevista

1. **O que torna isso "agêntico" e não um chatbot com RAG?** O modelo decide a sequência de ações: buscar, calcular, consultar o mercado, salvar no perfil, carregar uma skill. Há laço de observação e correção (erro de ferramenta, reescrita da busca).
2. **Qual foi a decisão mais importante?** "Números e autorização nunca vêm do modelo." As contas vêm das ferramentas e o usuário vem do estado. O resto é otimização.
3. **Onde o sistema pode errar?** Classificação das guardas (não determinística), seleção de ferramentas pelo modelo (o lite esqueceu a de datas) e notas curadas que ficam velhas.
4. **Como garantiu que a resposta jurídica está certa?** Corpus oficial e vigente pesquisado, limpeza do texto revogado, notas para decisões posteriores, citação obrigatória da fonte e "não encontrei" quando a busca falha. Mesmo assim, o assistente não substitui advogado, e o prompt e as guardas evitam promessas.
5. **Por que LangGraph e não só LangChain?** Pelo controle do fluxo: guardas, perfil e laço de RAG como nós e arestas explícitos, além de checkpointer e estado tipado.
6. **Como escalaria?** Servidor MCP por HTTP compartilhado, Postgres no lugar do SQLite (checkpointer e perfil), índice vetorial gerenciado, fila para turnos longos e tracing.
7. **O que faria diferente?** Começaria a avaliação mais cedo, já com checagens determinísticas, e teria filtrado os resultados de ferramenta contra injection indireta.

---

## 17. Glossário

| Termo | Significado |
|---|---|
| Agente | LLM que decide ações (ferramentas) em laço até cumprir o objetivo |
| Checkpointer | componente do LangGraph que salva o estado por `thread_id` |
| Chunk | pedaço de documento indexado no RAG |
| Embedding | vetor numérico que representa o significado de um texto |
| Few-shot | exemplos de entrada e saída no prompt para guiar o modelo |
| Guardrail | controle que reduz risco na entrada, nas ferramentas ou na saída |
| LLM-as-judge | uso de um LLM para avaliar respostas de outro |
| MCP | protocolo para expor ferramentas e contexto a aplicações com LLM |
| Mediana | valor do meio de uma lista ordenada; robusta a valores extremos |
| Prompt injection | texto que tenta fazer o modelo ignorar suas instruções |
| RAG | geração aumentada por recuperação de documentos |
| Reducer | função que combina a atualização de um nó com o estado anterior |
| Skill | instruções de tarefa carregadas sob demanda a partir de um catálogo |
| Tabela Price | sistema de amortização com parcelas fixas |
| Thread | uma conversa; unidade de memória do checkpointer |
| Tool calling | o modelo pede para executar uma função com argumentos estruturados |
