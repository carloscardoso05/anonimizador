import io
import re
from dataclasses import dataclass, field

import pymupdf
import spacy
import streamlit as st

PADROES = {
    "CPF": re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11}"),
    "EMAIL": re.compile(r"[\w\.\-]+@[\w\.\-]+\.\w+"),
    "TELEFONE": re.compile(r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}|\d{10,11}"),
    "RG": re.compile(r"\d{2}\.\d{3}\.\d{3}-\d|\d{7,9}"),
    "PROCESSO": re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}|\d{20}"),
}


@st.cache_resource
def carregar_nlp():
    return spacy.load("pt_core_news_lg")


@dataclass
class PII:
    texto: str
    tipo: str
    ocorrencias: list = field(default_factory=list)  # [(pagina, rect), ...]


def detectar_pii(pdf_bytes, nlp):
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        por_texto = {}

        for num_pag in range(len(pdf)):
            pagina = pdf[num_pag]

            for bloco in pagina.get_text("blocks"):
                texto = bloco[4]

                for ent in nlp(texto).ents:
                    if ent.label_ in ("PER", "ORG", "LOC"):
                        t = ent.text.strip()
                        for rect in pagina.search_for(t):
                            if t not in por_texto:
                                por_texto[t] = PII(t, ent.label_)
                            por_texto[t].ocorrencias.append((num_pag, rect))

                for nome, padrao in PADROES.items():
                    for match in padrao.finditer(texto):
                        t = match.group()
                        for rect in pagina.search_for(t):
                            if t not in por_texto or por_texto[t].tipo not in PADROES:
                                por_texto[t] = PII(t, nome)
                            por_texto[t].ocorrencias.append((num_pag, rect))

    for pii in por_texto.values():
        unicas = []
        for o in pii.ocorrencias:
            if o not in unicas:
                unicas.append(o)
        pii.ocorrencias = unicas

    return list(por_texto.values())


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


# ── UI ──

st.title("Anonimizador de PDFs")
nlp = carregar_nlp()

arquivo = st.file_uploader("PDF", type=["pdf"])

if arquivo:
    pdf_bytes = arquivo.read()
    piis = detectar_pii(pdf_bytes, nlp)

    categorias = len({p.tipo for p in piis})
    st.success(f"{len(piis)} PIIs em {categorias} categorias")

    st.subheader("Selecionar PIIs")
    dados = [{"Censurar": True, "Tipo": p.tipo, "Texto": p.texto} for p in piis]
    editado = st.data_editor(
        dados,
        column_config={"Censurar": st.column_config.CheckboxColumn()},
        width="stretch",
        hide_index=True,
    )

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
