# DataSift – Coletor Universal de Dados Web

**DataSift** é uma aplicação desktop completa, desenvolvida em Python com interface gráfica PyQt5, que integras três grandes capacidades: raspagem estruturada de sites, pesquisa automatizada em mecanismos de busca e enriquecimento de leads com e‑mail e telefone – utilizando desde expressões regulares até inteligência artificial (Groq Llama 3.3-70B) de forma gratuita.

---

## Por que este projeto demonstra conhecimento técnico de ponta?

A construção do DataSift exigiu o domínio de diversas tecnologias e estratégias avançadas:

- **PyQt5** – Escolhida pela sua robustez, componentes ricos e capacidade de criar interfaces nativas e responsivas, garantindo uma experiência profissional ao usuário.
- **Arquitetura multi‑thread** – Cada tarefa (scraping, pesquisa web, enriquecimento) roda em threads separadas com sinais `pyqtSignal`, mantendo a interface sempre responsiva e estável.
- **Selenium + undetected‑chromedriver** – Para pesquisas e raspagem de páginas dinâmicas, utilizou-se o `undetected_chromedriver` que contorna mecanismos anti‑bot, combinado com rotação de User‑Agent, tamanhos de janela aleatórios e delays humanos.
- **Rotação inteligente de mecanismos** – Google, Bing e Yahoo são alternados automaticamente; quando um deles apresenta CAPTCHA ou bloqueio, entra em cooldown e o sistema troca para o próximo.
- **Camadas de extração de contatos** – Uma solução híbrida: regex no HTML (rápido), depois varredura de páginas de contato comuns, e finalmente fallback para **Groq AI (Llama 3.3-70B)** – modelo de linguagem gratuito que analisa o texto visível da página e devolve e‑mails e telefones com alta precisão.
- **Gerenciamento de projetos** – Os projetos (listas de URLs e seletores CSS) são salvos em JSON, permitindo retomar trabalhos sem perda de configuração.
- **Exportação universal** – Dados podem ser salvos nos formatos CSV e JSON, compatíveis com qualquer ferramenta de análise posterior.

Essas escolhas não foram aleatórias; cada uma reflete a necessidade de equilibrar **velocidade, confiabilidade, discrição e baixo custo** (API Groq é 100% gratuita).

---

## Funcionalidades

### 1. Raspagem Estruturada (Scraper)
- Defina campos com seletores CSS (ex.: `h1`, `div.price`, `#description`).
- Dois modos de operação:
  - **Modo rápido (requests + BeautifulSoup)** – para páginas estáticas.
  - **Modo Selenium** – para páginas que dependem de JavaScript.
- Atraso configurável entre requisições (evita sobrecarga).

### 2. Pesquisa Web Multi‑mecanismo
- Digite uma consulta por linha (ex.: `locadora de equipamentos em São Paulo`, `aluguel de projetor`).
- Escolha entre Google, Bing e Yahoo.
- Número de páginas por consulta (1 a 3).
- O sistema evita bloqueios com:
  - Rota cíclica dos mecanismos.
  - Cooldown automático após CAPTCHA.
  - Delays aleatórios e rolagem simulada.

### 3. Enriquecimento com Contatos (E‑mail e Telefone)
- Alimenta a ferramenta com URLs vindas do Scraper ou da Pesquisa Web.
- **Camada 1:** Regex direto no HTML da página principal.
- **Camada 2:** Varredura inteligente das páginas `/contato`, `/contact`, `/sobre`, `/fale‑conosco`, etc.
- **Camada 3 (opcional):** Se ainda não encontrou nada, envia o texto visível da página (limpo de tags, até 4000 caracteres) para o modelo **Groq Llama 3.3-70B**, que retorna um JSON com os contatos extraídos.
- Tabela de resultados atualizada em tempo real, com opção de sobreescrever ou preservar contatos existentes.

### 4. Visualização e Exportação
- Aba **Results**: mostra os dados raspados pelo Scraper.
- Botões para exportar para CSV ou JSON.
- A aba de Enriquecimento também permite exportar a tabela final em CSV.

### 5. Configurações e Persistência
- Customização do User‑Agent.
- Chave da API Groq (necessária apenas se o enriquecimento com IA estiver ativo).
- Salvamento e carregamento de projetos (URLs + campos + opções) em arquivos `.json`.

---

## Tecnologias Utilizadas

| Tecnologia | Função |
|------------|--------|
| Python 3.8+ | Linguagem principal |
| PyQt5 | Interface gráfica (widgets, sinais, threads) |
| Requests + BeautifulSoup | Raspagem leve de HTML estático |
| Selenium + undetected‑chromedriver | Automação de navegador anti‑detecção |
| Threading (QThread) | Execução assíncrona de tarefas pesadas |
| Groq API (Llama 3.3-70B) | Extração inteligente de contatos (fallback gratuito) |
| JSON, CSV | Formatos de armazenamento e exportação |

---

## Instalação e Execução

### Pré‑requisitos
- Python 3.8 ou superior.
- Google Chrome instalado (para o Selenium).
- Conexão com a internet (opcional, apenas para a API Groq).

### Passos

1. Coloque os três arquivos na mesma pasta:
   - `datasift.py` (aplicação principal)
   - `search_worker.py` (pesquisa web)
   - `contact_enricher.py` (enriquecimento de contatos)

2. Instale as dependências:

```bash
pip install PyQt5 requests beautifulsoup4 selenium undetected-chromedriver
```

3. Execute:

```bash
python datasift.py
```

4. (Opcional) Obtenha uma chave de API gratuita em [console.groq.com](https://console.groq.com) e configure‑a na aba **Settings** para usar o enriquecimento com IA.

---

## Como Usar

### Aba Scraper
- Cole URLs (uma por linha).
- Adicione campos: nome do campo e seletor CSS.
- Escolha se deseja Selenium e modo headless.
- Clique em `Start Scraping`.
- Acompanhe o log e, ao final, vá para a aba **Results**.

### Aba Web Search
- Escreva as consultas (uma por linha).
- Marque os mecanismos desejados.
- Defina o número de páginas.
- Clique em `Start Search`.
- A tabela exibirá título, URL, engine e consulta.

### Aba Enrich Contacts
- Selecione as fontes de URLs (Scraper e/ou Web Search).
- Se quiser usar IA, marque `Use Groq AI` e tenha a chave configurada.
- Clique em `Start Enrichment`.
- Acompanhe a varredura. E‑mails e telefones encontrados preencherão a tabela.
- Exporte o resultado final em CSV.

### Aba Results
- Exibe os dados extraídos pelo Scraper. Utilize os botões de exportação.

### Aba Settings
- Defina User‑Agent personalizado (opcional).
- Cole a chave da API Groq para ativar a IA.

---

## Estrutura de Armazenamento

- Configurações: `~/.general_scraper/config.json`
- Projetos salvos: `~/.general_scraper/projects/`
- Levar em conta que os dados de sessão (resultados de busca, enriquecimento) são voláteis; exporte‑os para CSV/JSON para persistência.

---

## Resolução de Problemas

| Problema | Solução |
|----------|---------|
| `ModuleNotFoundError` para `undetected_chromedriver` | Instale: `pip install undetected-chromedriver` |
| Web Search trava com CAPTCHA | Reduza `Pages per query` para 1 e aumente o intervalo entre consultas. |
| A IA não retorna contatos | Verifique a chave API em Settings e a conexão com a internet. |
| Selenium não encontra elementos | Teste os seletores CSS no navegador; use o modo headless desligado para depuração. |
| O aplicativo não inicia | Verifique se os três arquivos `.py` estão na mesma pasta. Execute pelo terminal para ver a mensagem de erro. |

---

## Licença e Boas Práticas

Este software é fornecido para fins educacionais e de pesquisa. O usuário é o único responsável por respeitar os termos de uso dos sites e mecanismos de busca, bem como as leis de proteção de dados. Recomenda‑se a utilização de delays e a verificação de `robots.txt` antes de qualquer raspagem automatizada.

---

## Créditos e Agradecimentos

- **PyQt5** – Framework gráfico de alta qualidade.
- **Groq** – Pela API Llama gratuita e rápida.
- **undetected‑chromedriver** – Por permitir automação discreta.
- Comunidade open‑source que mantém as bibliotecas utilizadas.

---

## Versão

**DataSift v1.2** – Abril de 2026

--- 