"""Anonimizador de PDF — spaCy NER + REGEX | uv run streamlit run app.py"""

import re
from collections import defaultdict
from io import BytesIO

import fitz
import spacy
import streamlit as st

PATTERNS = {
    "CPF": re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}"),
    "CNPJ": re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"),
    "Telefone": re.compile(r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}"),
    "Email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "CEP": re.compile(r"\b\d{5}-\d{3}\b"),
    "Cartão": re.compile(r"\b(?:\d{4}[\s-]){3}\d{4}\b"),
}

NER = {"PER": "Pessoa", "ORG": "Organização", "LOC": "Local"}


@st.cache_resource
def load_nlp():
    return spacy.load("pt_core_news_lg")


def detect(texto, pagina, nlp):
    achados = []
    for linha in texto.split("\n"):
        if not linha.strip():
            continue
        for ent in nlp(linha).ents:
            if ent.label_ in NER:
                achados.append(
                    {"texto": ent.text.strip(), "cat": NER[ent.label_], "pagina": pagina}
                )
    for cat, pat in PATTERNS.items():
        for m in pat.finditer(texto):
            achados.append({"texto": m.group().strip(), "cat": cat, "pagina": pagina})
    return achados


def anonimizar(pdf_bytes, mapa):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for num_pag, textos in mapa.items():
        page = doc[num_pag]
        for texto in textos:
            for area in page.search_for(texto):
                page.add_redact_annot(area, fill=(0, 0, 0))
        page.apply_redactions()
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf


st.set_page_config(page_title="Anonimizador de PDF", layout="wide")
st.title("Anonimizador de PDF")
st.caption(
    "Detecta dados sensíveis com spaCy NER (Pessoa, Organização, Local) "
    "e REGEX (CPF, CNPJ, Telefone, Email, CEP, Cartão). "
    "Selecione o que anonimizar e baixe o PDF com tarjas pretas."
)

arquivo = st.file_uploader("Selecione um arquivo PDF", type=["pdf"])
if arquivo is None:
    st.stop()

nlp = load_nlp()

if "dados" not in st.session_state or st.session_state.get("_arq") != arquivo.name:
    pdf_bytes = arquivo.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    dados = []
    for i in range(len(doc)):
        dados.extend(detect(doc[i].get_text(), i, nlp))
    doc.close()
    dados = list({(d["texto"], d["pagina"]): d for d in dados}.values())
    for i in range(len(dados)):
        st.session_state[f"c{i}"] = True
    st.session_state.dados = dados
    st.session_state._arq = arquivo.name
    st.session_state._pdf = pdf_bytes

dados = st.session_state.dados
if not dados:
    st.warning("Nenhum dado sensível encontrado no PDF.")
    st.stop()

por_cat = defaultdict(list)
for i, d in enumerate(dados):
    por_cat[d["cat"]].append(i)

st.subheader(f"Dados sensíveis encontrados: {len(dados)}")

for cat in sorted(por_cat):
    with st.expander(f"{cat} ({len(por_cat[cat])})"):
        for i in por_cat[cat]:
            d = dados[i]
            st.checkbox(f"`{d['texto']}` — pág. {d['pagina'] + 1}", key=f"c{i}")

sel = [i for i in range(len(dados)) if st.session_state.get(f"c{i}", True)]

if st.button(
    f"Anonimizar PDF ({len(sel)}/{len(dados)})",
    type="primary",
    disabled=len(sel) == 0,
):
    mapa = defaultdict(list)
    for i in sel:
        mapa[dados[i]["pagina"]].append(dados[i]["texto"])
    out = anonimizar(st.session_state._pdf, mapa)
    st.download_button(
        "Baixar PDF anonimizado",
        data=out,
        file_name=f"anonimizado_{arquivo.name}",
        mime="application/pdf",
    )
