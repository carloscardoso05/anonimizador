# Anonimizador de PDFs — Explicação detalhada

> Guia para apresentação do código na palestra. Cada seção explica o **conceito de PLN** por trás do trecho, o **que ele faz** e os **pontos para destacar** ao público.

---

## Estrutura geral (113 linhas)

```
Imports         (linhas 1-7)
Padrões Regex   (linhas 9-15)
Modelo spaCy    (linhas 18-20)
Classe PII      (linhas 23-27)
detectar_pii()  (linhas 30-63)   ← coração do app
redigir_pdf()   (linhas 66-77)
UI Streamlit    (linhas 80-113)
```

---

## 1. Imports (linhas 1-7)

```python
import io
import re
from dataclasses import dataclass, field

import pymupdf
import spacy
import streamlit as st
```

| Biblioteca | Função no projeto |
|---|---|
| `pymupdf` | Ler PDF, buscar texto por coordenadas, aplicar censura (redact) |
| `spacy` | NER — Reconhecimento de Entidades Nomeadas (PESSOA, ORGANIZAÇÃO, LOCAL) |
| `streamlit` | Interface web com zero esforço — botões, upload, tabelas |
| `re` | Expressões regulares para padrões como CPF, email, telefone |
| `dataclasses` | Estrutura leve para representar uma PII encontrada |
| `io` | Buffer em memória para gerar PDF sem gravar em disco |

**Ponto para palestra:** Três bibliotecas fazem o trabalho pesado — `pymupdf` manipula o PDF, `spacy` entende o texto, `streamlit` monta a interface. PLN não é uma tecnologia isolada, é uma combinação de ferramentas.

---

## 2. Padrões Regex (linhas 9-15)

```python
PADROES = {
    "CPF":      re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11}"),
    "EMAIL":    re.compile(r"[\w\.\-]+@[\w\.\-]+\.\w+"),
    "TELEFONE": re.compile(r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}|\d{10,11}"),
    "RG":       re.compile(r"\d{2}\.\d{3}\.\d{3}-\d|\d{7,9}"),
    "PROCESSO": re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}|\d{20}"),
}
```

Cada padrão tem **duas alternativas** separadas por `|`:

| Padrão | Com máscara | Sem máscara |
|---|---|---|
| CPF | `123.456.789-00` | `12345678900` |
| TELEFONE | `(91) 99999-1111` | `91999991111` |
| RG | `23.456.789-0` | `1234567` |
| PROCESSO | `1111111-22.3333.4.55.6666` | 20 dígitos contínuos |
| EMAIL | `nome@dominio.com` | (não tem máscara) |

**Ponto para palestra:** Regex é a abordagem **determinística** para PII. Funciona para padrões bem definidos, mas falha quando o formato varia. Por isso combinamos com NER. A ordem dos padrões importa: `re.compile` compila uma vez e reusa — eficiência.

---

## 3. Carregamento do modelo spaCy (linhas 18-20)

```python
@st.cache_resource
def carregar_nlp():
    return spacy.load("pt_core_news_lg")
```

- `spacy.load("pt_core_news_lg")` — carrega o modelo de língua portuguesa (grande)
- `@st.cache_resource` — cache do Streamlit: o modelo de ~500 MB é carregado **uma vez** e compartilhado entre todas as requisições. Sem isso, cada interação do usuário recarregaria o modelo.

**Ponto para palestra:** Modelos de PLN são pesados (500 MB+). Cache é essencial para aplicações web. O `pt_core_news_lg` contém vetores de palavras, regras de tokenização e pesos treinados para NER em português.

---

## 4. Classe PII (linhas 23-27)

```python
@dataclass
class PII:
    texto: str
    tipo: str
    ocorrencias: list = field(default_factory=list)  # [(pagina, rect), ...]
```

Cada PII detectada vira um objeto com:
- `texto` — o valor encontrado (ex: `"João Silva"`)
- `tipo` — categoria (ex: `"PER"`, `"CPF"`, `"EMAIL"`)
- `ocorrencias` — lista de `(página, retângulo)` indicando **onde** no PDF

**Ponto para palestra:** Um mesmo texto (ex: "João Silva") pode aparecer em várias páginas. Em vez de duplicar linhas na tabela, agrupamos tudo em um objeto só. Quando o usuário seleciona, censura em **todas** as páginas. `field(default_factory=list)` é um truque do Python para evitar o bug do argumento mutável em dataclasses.

---

## 5. `detectar_pii()` — o motor de detecção (linhas 30-63)

```python
def detectar_pii(pdf_bytes, nlp):
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        por_texto = {}
```

Abre o PDF a partir dos bytes (não de arquivo em disco — compatível com `st.file_uploader`).

### 5.1 Iteração por blocos (linhas 34-38)

```python
        for num_pag in range(len(pdf)):
            pagina = pdf[num_pag]

            for bloco in pagina.get_text("blocks"):
                texto = bloco[4]
```

**Por que `get_text("blocks")` em vez de `get_text()`?**

`get_text()` retorna a página inteira como uma string. O problema: textos de regiões diferentes do PDF (ex: "Vara da Capital" e "Assunto") podem ser colados com `\n`, e o spaCy junta tudo numa entidade só.

`get_text("blocks")` retorna uma lista de tuplas. Cada tupla `(x0, y0, x1, y1, texto, ...)` representa um bloco visual independente. Processamos cada bloco separadamente → o spaCy só vê texto que realmente está junto visualmente.

**Ponto para palestra:** Extrair texto de PDF é um problema de engenharia subestimado. A estrutura visual (blocos, colunas, tabelas) importa para o PLN. Um `\n` mal posicionado pode quebrar o NER.

### 5.2 Detecção NER — spaCy (linhas 40-46)

```python
                for ent in nlp(texto).ents:
                    if ent.label_ in ("PER", "ORG", "LOC"):
                        t = ent.text.strip()
                        for rect in pagina.search_for(t):
                            if t not in por_texto:
                                por_texto[t] = PII(t, ent.label_)
                            por_texto[t].ocorrencias.append((num_pag, rect))
```

Passo a passo:
1. `nlp(texto)` — processa o texto do bloco (tokenização, POS tagging, NER, parsing)
2. `.ents` — iterator sobre as entidades nomeadas encontradas
3. Filtro `ent.label_ in ("PER", "ORG", "LOC")` — só entidades consideradas PII
4. `ent.text.strip()` — texto da entidade sem espaços extras
5. `pagina.search_for(t)` — busca o texto no PDF e retorna coordenadas (retângulos)
6. Se o texto ainda não está no dicionário, cria uma PII nova
7. Adiciona `(página, retângulo)` à lista de ocorrências

**Ponto para palestra:** `search_for` é a ponte entre o PLN (que trabalha com texto) e o PDF (que trabalha com coordenadas). Ele faz busca textual e retorna `(x, y, largura, altura)` de cada ocorrência. É o que permite censurar o local exato.

### 5.3 Detecção Regex (linhas 48-54)

```python
                for nome, padrao in PADROES.items():
                    for match in padrao.finditer(texto):
                        t = match.group()
                        for rect in pagina.search_for(t):
                            if t not in por_texto or por_texto[t].tipo not in PADROES:
                                por_texto[t] = PII(t, nome)
                            por_texto[t].ocorrencias.append((num_pag, rect))
```

Mesma lógica do NER, mas usando `padrao.finditer(texto)` para encontrar matches de regex.

A condição `por_texto[t].tipo not in PADROES` é crucial: **regex tem prioridade sobre NER**. Se o spaCy classificou `laenor.val01@gmail.com` como `LOC` (falso positivo), o regex EMAIL sobrescreve com o tipo correto.

**Ponto para palestra:** NER comete erros — emails são frequentemente classificados como LOC ou ORG. Regex é mais preciso para padrões estruturados. A prioridade "regex ganha do NER" é uma heurística simples que resolve a maioria dos conflitos.

### 5.4 Deduplicação (linhas 56-63)

```python
    for pii in por_texto.values():
        unicas = []
        for o in pii.ocorrencias:
            if o not in unicas:
                unicas.append(o)
        pii.ocorrencias = unicas

    return list(por_texto.values())
```

Remove ocorrências duplicadas `(mesma página, mesmo retângulo)`. Isso acontece quando o mesmo texto é detectado via NER em dois blocos diferentes (ex: "João Silva" no bloco de Ana e no bloco de Pedro).

**Retorna:** lista de objetos `PII`, um por texto único, cada um com todas as suas ocorrências no PDF.

---

## 6. `redigir_pdf()` — aplicando a censura (linhas 66-77)

```python
def redigir_pdf(pdf_bytes, piis):
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        for pii in piis:
            for pagina, rect in pii.ocorrencias:
                pdf[pagina].add_redact_annot(rect, fill=(0, 0, 0))

        for pagina in pdf:
            pagina.apply_redactions()

        saida = io.BytesIO()
        pdf.save(saida)
        return saida.getvalue()
```

Passo a passo:
1. Abre o PDF original (bytes)
2. Para cada PII selecionada, itera suas ocorrências
3. `add_redact_annot(rect, fill=(0,0,0))` — marca um retângulo preto sobre o texto
4. `apply_redactions()` — **destrói permanentemente** o texto sob os retângulos
5. Salva em `BytesIO` (buffer de memória) e retorna os bytes

**Ponto para palestra:** `add_redact_annot` + `apply_redactions` é irreversível. O texto original é removido do PDF, não apenas "escondido". Isso é importante para conformidade com LGPD — não basta cobrir visualmente, tem que remover do conteúdo do arquivo.

---

## 7. Interface Streamlit (linhas 80-113)

### 7.1 Cabeçalho (linhas 82-85)

```python
st.title("Anonimizador de PDFs")
nlp = carregar_nlp()

arquivo = st.file_uploader("PDF", type=["pdf"])
```

- `st.title` — título da página
- `carregar_nlp()` — carrega o modelo (cacheado) assim que o app inicia
- `st.file_uploader` — widget de upload, aceita só PDF

### 7.2 Detecção e resumo (linhas 87-92)

```python
if arquivo:
    pdf_bytes = arquivo.read()
    piis = detectar_pii(pdf_bytes, nlp)

    categorias = len({p.tipo for p in piis})
    st.success(f"{len(piis)} PIIs em {categorias} categorias")
```

- Lê bytes do arquivo enviado
- Chama `detectar_pii` (a função que definimos)
- Conta categorias únicas (set comprehension) e exibe resumo

### 7.3 Tabela interativa (linhas 94-101)

```python
    st.subheader("Selecionar PIIs")
    dados = [{"Censurar": True, "Tipo": p.tipo, "Texto": p.texto} for p in piis]
    editado = st.data_editor(
        dados,
        column_config={"Censurar": st.column_config.CheckboxColumn()},
        width="stretch",
        hide_index=True,
    )
```

- Cria lista de dicionários: cada PII vira uma linha com checkbox + tipo + texto
- `st.data_editor` — widget do Streamlit que permite **editar** os dados na tabela
- `CheckboxColumn()` — renderiza a coluna "Censurar" como checkboxes clicáveis
- `width="stretch"` — ocupa toda a largura disponível

**Ponto para palestra:** `st.data_editor` é um dos widgets mais poderosos do Streamlit. Em 5 linhas temos uma tabela editável com checkboxes — zero JavaScript, zero HTML.

### 7.4 Botão e download (linhas 103-113)

```python
    selecionados_n = sum(1 for row in editado if row["Censurar"])
    if st.button(f"Anonimizar ({selecionados_n}/{len(piis)})", type="primary"):
        para_redigir = [piis[i] for i, row in enumerate(editado) if row["Censurar"]]
        if para_redigir:
            pdf_final = redigir_pdf(pdf_bytes, para_redigir)
            st.download_button(
                "Download",
                data=pdf_final,
                file_name="anonimizado.pdf",
                mime="application/pdf",
            )
```

- Conta selecionados e mostra no botão (`5/43`)
- `enumerate(editado)` — mantém o índice para mapear de volta para `piis[i]`
- Chama `redigir_pdf` com as PIIs selecionadas
- `st.download_button` — botão nativo de download, recebe bytes e oferece arquivo

---

## Conceitos de PLN abordados (resumo para a palestra)

| Conceito | Onde aparece |
|---|---|
| **NER** (Named Entity Recognition) | spaCy detecta PER, ORG, LOC no texto |
| **Regex** (Expressões Regulares) | Padrões determinísticos para CPF, email, telefone |
| **Extração de texto de PDF** | `get_text("blocks")` — estrutura visual importa |
| **Busca por coordenadas** | `search_for()` — ponte entre texto e layout |
| **Redação (censura)** | `add_redact_annot` + `apply_redactions` — irreversível |
| **Heurística de prioridade** | Regex sobrescreve NER quando ambos detectam o mesmo texto |
| **Deduplicação** | Agrupa ocorrências do mesmo texto em múltiplas páginas |
| **Limitações do NER** | Falsos positivos (CPF como PER), endereços fragmentados |
| **Limitações do Regex** | Só funciona para padrões conhecidos; não detecta nomes de pessoas |

---

## Falar sobre na palestra

1. **"Por que não usar só regex?"** → Nomes de pessoas não têm padrão fixo. Precisamos de NER.
2. **"Por que não usar só NER?"** → CPF, email, telefone têm formato exato. Regex é mais preciso.
3. **"E os falsos positivos?"** → `CPF` detectado como pessoa, `EXITOSO` como pessoa, `CLÁUSULA` como organização. O modelo de português não é perfeito. A tabela interativa permite revisão manual.
4. **"Por que blocos e não a página inteira?"** → PDFs têm layout visual. Tratar a página como texto corrido introduz ruído (ex: "Vara da Capital\nAssunto" vira uma entidade só).
5. **"O que acontece quando censura?"** → O PyMuPDF remove o texto do PDF permanentemente. Não é só uma tarja — o dado some do arquivo.
