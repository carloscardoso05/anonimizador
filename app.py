"""Anonimizador de PDF — spaCy NER + REGEX | uv run streamlit run app.py"""

import re
from collections import defaultdict
from io import BytesIO

import fitz  # pymupdf
import spacy
import streamlit as st

# ═══════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ═══════════════════════════════════════════════════════════

STREAMLIT_TITLE = "Anonimizador de PDF"

PATTERNS: dict[str, re.Pattern] = {
    "CPF": re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}"),
    "CNPJ": re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"),
    "Telefone": re.compile(r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}"),
    "Email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "CEP": re.compile(r"\d{5}-\d{3}"),
    "Cartão": re.compile(r"\b(?:\d{4}[\s-]){3}\d{4}\b"),
}

NER_LABELS = {"PER": "Pessoa", "ORG": "Organização", "LOC": "Local"}

# ═══════════════════════════════════════════════════════════
# MOTOR DE DETECÇÃO
# ═══════════════════════════════════════════════════════════


@st.cache_resource
def _carregar_spacy():
    return spacy.load("pt_core_news_lg")


def _detectar_pagina(texto: str, pagina: int, nlp) -> list[dict]:
    """NER (spaCy) + REGEX em uma página."""
    achados: list[dict] = []

    doc = nlp(texto)
    for ent in doc.ents:
        if ent.label_ in NER_LABELS:
            achados.append(
                {"texto": ent.text.strip(), "categoria": NER_LABELS[ent.label_], "pagina": pagina}
            )

    for categoria, pattern in PATTERNS.items():
        for match in pattern.finditer(texto):
            achados.append(
                {"texto": match.group().strip(), "categoria": categoria, "pagina": pagina}
            )

    return achados


def _deduplicar(achados: list[dict]) -> list[dict]:
    vistos: set[tuple[str, int]] = set()
    unicos: list[dict] = []
    for a in achados:
        chave = (a["texto"], a["pagina"])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(a)
    return unicos


# ═══════════════════════════════════════════════════════════
# MOTOR DE CENSURA
# ═══════════════════════════════════════════════════════════


def _censurar(pdf_bytes: bytes, mapa: dict[int, list[str]]) -> BytesIO:
    """Aplica tarjas pretas nos textos indicados por página."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for num_pagina, textos in mapa.items():
        page = doc[num_pagina]
        for texto in textos:
            for area in page.search_for(texto):
                page.add_redact_annot(area, fill=(0, 0, 0))
        page.apply_redactions()
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf



# ═══════════════════════════════════════════════════════════
# INTERFACE STREAMLIT
# ═══════════════════════════════════════════════════════════

st.set_page_config(page_title=STREAMLIT_TITLE, layout="wide")
st.title(STREAMLIT_TITLE)
st.caption(
    "Detecta dados sensíveis com **spaCy NER** (Pessoa, Organização, Local) "
    "e **REGEX** (CPF, CNPJ, Telefone, Email, CEP, Cartão). "
    "Selecione o que censurar e baixe o PDF com tarjas pretas."
)

arquivo = st.file_uploader("Selecione um arquivo PDF", type=["pdf"])

if arquivo is None:
    st.stop()

# ── Carregar spaCy ──
nlp = _carregar_spacy()

# ── Processar PDF (cache por nome de arquivo no session_state) ──
if "dados" not in st.session_state or st.session_state.get("_arquivo_nome") != arquivo.name:
    with st.spinner("Analisando PDF..."):
        pdf_bytes = arquivo.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total = len(doc)

        barra = st.progress(0, text="Extraindo texto...")
        todos: list[dict] = []
        for i, page in enumerate(doc):
            todos.extend(_detectar_pagina(page.get_text(), i + 1, nlp))
            barra.progress((i + 1) / total, text=f"Página {i + 1}/{total}")
        doc.close()
        barra.empty()

        # Limpa chaves antigas da sessão
        for chave in list(st.session_state.keys()):
            if chave.startswith("sel_"):
                del st.session_state[chave]

        st.session_state.dados = _deduplicar(todos)
        st.session_state._arquivo_nome = arquivo.name
        st.session_state._pdf_bytes = pdf_bytes

dados: list[dict] = st.session_state.dados

if not dados:
    st.warning("Nenhum dado sensível encontrado no PDF.")
    st.stop()

# ── Agrupar por categoria ──
por_cat: dict[str, list[int]] = defaultdict(list)
for idx, item in enumerate(dados):
    por_cat[item["categoria"]].append(idx)

st.subheader(f"Dados sensíveis encontrados: {len(dados)}")
st.caption("Desmarque os itens que **não** devem ser censurados.")

# ── Inicializar seleções (tudo marcado por padrão) ──
for i in range(len(dados)):
    if f"sel_{i}" not in st.session_state:
        st.session_state[f"sel_{i}"] = True

# ── Renderizar checkboxes agrupados por categoria ──
for categoria in sorted(por_cat.keys()):
    indices = por_cat[categoria]
    with st.expander(f"{categoria} ({len(indices)})"):
        c1, c2, _ = st.columns([1, 1, 4])
        with c1:
            if st.button("✓ Todos", key=f"todos_{categoria}"):
                for i in indices:
                    st.session_state[f"sel_{i}"] = True
        with c2:
            if st.button("✗ Nenhum", key=f"nenhum_{categoria}"):
                for i in indices:
                    st.session_state[f"sel_{i}"] = False

        for i in indices:
            item = dados[i]
            st.checkbox(f"`{item['texto']}` — pág. {item['pagina']}", key=f"sel_{i}")

# ── Resumo + Ação ──
selecionados = [i for i in range(len(dados)) if st.session_state.get(f"sel_{i}", True)]
total_sel = len(selecionados)

col1, col2 = st.columns([3, 1])
with col1:
    st.info(f"{total_sel} de {len(dados)} itens serão censurados")
with col2:
    apertou = st.button("Censurar PDF", type="primary", disabled=total_sel == 0)

if apertou:
    with st.spinner("Aplicando censura..."):
        mapa: dict[int, list[str]] = defaultdict(list)
        for i in selecionados:
            item = dados[i]
            mapa[item["pagina"] - 1].append(item["texto"])

        pdf_censurado = _censurar(st.session_state._pdf_bytes, mapa)

    st.success("PDF censurado com sucesso!")
    st.download_button(
        "Baixar PDF censurado",
        data=pdf_censurado,
        file_name=f"censurado_{arquivo.name}",
        mime="application/pdf",
    )
