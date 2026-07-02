# -*- coding: utf-8 -*-
# =============================================================================
# MAT-NRC-REBUILD-001 — Sistema de Monitoramento Provimento 07/2021 v4.0
# Registro Civil - Unidades Interligadas (COGEX-MA / TJMA)
# -----------------------------------------------------------------------------
# Reconstruído a partir da auditoria do CSV real (4.487 registros):
#   • 100% dos registros preservados (nenhuma linha descartada)
#   • Parser textual de quantidades ("OITO NASCIMENTO", "0 (ZERO)", "NÃO HOUVE")
#   • Ano em branco (51 casos, incl. 2026 sem opção no form) → fallback carimbo
#   • Mês em português (JANEIRO...) → número 1-12
#   • Coluna "%" texto BR ("62,07%") → float
#   • Remoção de marcas invisíveis LRM/RLM em municípios
#   • Aba 🚩 Anomalias: células irrecuperáveis + registros > nascimentos
# =============================================================================

import io
import re
import unicodedata
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd
import requests
import streamlit as st

# ==================== CONFIGURAÇÃO DA PÁGINA ====================
st.set_page_config(
    page_title="Provimento 07/2021 - Sistema Avançado v4.0",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

URL_PADRAO = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRtKiqlosLL5_CJgGom7BlWpFYExhLTQEjQT_Pdgnv3uEYMlWPpsSeaxfjqy0IxTluVlKSpcZ1IoXQY"
    "/pub?output=csv"
)

COLUNA_TIMESTAMP = "Carimbo de data/hora"

NOMES_MESES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}

MESES_PT = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARÇO": 3, "MARCO": 3, "ABRIL": 4,
    "MAIO": 5, "JUNHO": 6, "JULHO": 7, "AGOSTO": 8,
    "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12,
}

# ==================== PARSER TEXTUAL DE QUANTIDADES ====================
# Validado contra os 4.487 registros reais:
#   NASCIMENTOS: 4.330 numéricos + 84 dígito-em-texto + 20 extenso + 1 "não houve"
#                → 35 sem_info + 17 nulos permanecem como anomalia (NaN)
#   REGISTROS:   4.354 numéricos + 95 dígito-em-texto + 20 extenso + 10 "não houve"
#                → 5 sem_info + 3 nulos permanecem como anomalia (NaN)

EXTENSO = {
    "ZERO": 0, "UM": 1, "UMA": 1, "DOIS": 2, "DUAS": 2, "TRES": 3,
    "QUATRO": 4, "CINCO": 5, "SEIS": 6, "SETE": 7, "OITO": 8, "NOVE": 9,
    "DEZ": 10, "ONZE": 11, "DOZE": 12, "TREZE": 13,
    "QUATORZE": 14, "QUARTOZE": 14, "CATORZE": 14, "QUINZE": 15,
    "DEZESSEIS": 16, "DEZESSETE": 17, "DEZOITO": 18, "DEZENOVE": 19,
    "VINTE": 20, "NENHUM": 0, "NENHUMA": 0,
}

PADROES_SEM_INFO = [
    "SEM INFORMAC", "SEM DECLARAC", "NAO INFORMADO", "DESCONHECID",
    "PREJUDICADO", "EM INSTALACAO", "NAO HA UNIDADE",
    "NAO TEM RELATORIO", "EM REFORMA",
]


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def parse_quantidade(valor) -> Tuple[Optional[float], str]:
    """Converte a célula de quantidade em número, preservando 100% das linhas.

    Retorna (numero, origem):
      numerico      → célula já era número ("116", "72,0")
      texto_zero    → "NÃO HOUVE...", "Não teve nenhum" → 0
      texto_digito  → dígito dentro de texto ("12 REGISTROS", "0 (ZERO)", "´17")
      texto_extenso → número por extenso ("OITO NASCIMENTO", "TRES (03)")
      sem_info      → irrecuperável ("SEM INFORMAÇÃO", "Em instalação") → NaN
      nulo          → célula vazia → NaN
    """
    if pd.isna(valor):
        return None, "nulo"
    texto = str(valor).strip()
    numero = pd.to_numeric(texto.replace(",", "."), errors="coerce")
    if pd.notna(numero):
        return float(numero), "numerico"
    tu = _sem_acento(texto.upper())
    if any(p in tu for p in PADROES_SEM_INFO):
        return None, "sem_info"
    if "NAO HOUVE" in tu or "NAO TEVE" in tu:
        return 0.0, "texto_zero"
    m = re.search(r"\d+", tu)
    if m:
        return float(m.group()), "texto_digito"
    for palavra in re.findall(r"[A-Z]+", tu):
        if palavra in EXTENSO:
            return float(EXTENSO[palavra]), "texto_extenso"
    return None, "sem_info"


def converter_mes(valor) -> Optional[int]:
    """'JANEIRO' → 1; aceita também número puro (compatibilidade)."""
    if pd.isna(valor):
        return None
    texto = str(valor).strip().upper()
    if texto in MESES_PT:
        return MESES_PT[texto]
    try:
        numero = int(float(texto.replace(",", ".")))
        if 1 <= numero <= 12:
            return numero
    except (ValueError, TypeError):
        pass
    return None


def converter_percentual_texto(serie: pd.Series) -> pd.Series:
    """'62,07%' → 62.07 (float). Sem isso min/max/mean quebram com TypeError."""
    return pd.to_numeric(
        serie.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.strip(),
        errors="coerce",
    )


# ==================== NORMALIZAÇÃO DE SCHEMA ====================

def normalizar_planilha(df: pd.DataFrame) -> pd.DataFrame:
    """Corrige divergências entre o CSV publicado e o schema interno."""
    df = df.copy()

    # 1) 1ª coluna (timestamp) sai sem nome no CSV publicado → "Unnamed: 0"
    primeira = df.columns[0]
    if primeira != COLUNA_TIMESTAMP and (
        str(primeira).strip() == "" or str(primeira).startswith("Unnamed")
    ):
        df = df.rename(columns={primeira: COLUNA_TIMESTAMP})

    # 2) Coluna de percentual pronto chega como "%"
    if "%" in df.columns and "% Ok." not in df.columns:
        df = df.rename(columns={"%": "% Ok."})

    # 3) Colunas fantasma totalmente vazias (ex.: "Unnamed: 10")
    for col in list(df.columns):
        if str(col).startswith("Unnamed") and df[col].isna().all():
            df = df.drop(columns=[col])

    # 4) Marcas invisíveis LRM/RLM injetadas pelo Google Forms
    #    (ex.: "Açailândia\u200e") + espaços extras
    campos_texto = ["MUNICÍPIO", "Nome da Serventia", "Posto/Unidade Interligada"]
    for col in campos_texto:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace("\u200e", "", regex=False)
                .str.replace("\u200f", "", regex=False)
                .str.strip()
            )
            df[col] = df[col].replace("nan", pd.NA)

    return df


# ==================== CARREGAMENTO ====================

@st.cache_data(ttl=300, show_spinner=False)
def carregar_dados_url(url: str) -> Optional[pd.DataFrame]:
    try:
        resposta = requests.get(url, timeout=30)
        resposta.raise_for_status()
        df = pd.read_csv(io.StringIO(resposta.text))
        return normalizar_planilha(df)
    except Exception as erro:
        st.error(f"Erro ao carregar dados da URL: {erro}")
        return None


@st.cache_data(show_spinner=False)
def carregar_dados_arquivo(arquivo) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(arquivo)
        return normalizar_planilha(df)
    except Exception as erro:
        st.error(f"Erro ao carregar arquivo: {erro}")
        return None


# ==================== PROCESSAMENTO (100% PRESERVADO) ====================

def processar_dados(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """Processa TODAS as linhas sem descartar nenhuma.

    Células irrecuperáveis viram NaN e são sinalizadas na coluna
    'anomalias' — consumidas pela aba 🚩.
    """
    mapa = {
        COLUNA_TIMESTAMP: "timestamp",
        "Endereço de e-mail": "email",
        "MUNICÍPIO": "municipio",
        "Nome da Serventia": "serventia",
        "Posto/Unidade Interligada": "posto_unidade",
        "Mês": "mes_bruto",
        "Ano": "ano_bruto",
        "NASCIMENTOS (QTDE)": "nascimentos_bruto",
        "REGISTROS (QTDE)": "registros_bruto",
        "Quais os principais motivos de não terem sido feitos 100% registros?": "motivos",
        "% Ok.": "percentual_bruto",
    }
    d = df.copy()
    for original, novo in mapa.items():
        if original in d.columns:
            d[novo] = d[original]
        else:
            d[novo] = pd.NA

    stats = {"total_linhas": len(d)}

    # --- Timestamp (dayfirst: formato BR "25/02/2021 16:26:30") ---
    d["timestamp"] = pd.to_datetime(d["timestamp"], errors="coerce", dayfirst=True)
    d["ano_carimbo"] = d["timestamp"].dt.year
    d["data_formatada"] = d["timestamp"].dt.strftime("%d/%m/%Y %H:%M")

    # --- Ano: campo do form com fallback no carimbo ---
    # 51 respostas com Ano vazio no dado real, incluindo lançamentos de 2026
    # ("O ANO É 2026, ESTÁ SEM OPÇÃO" — o formulário não tem a opção 2026).
    d["ano"] = pd.to_numeric(d["ano_bruto"], errors="coerce")
    stats["ano_via_fallback"] = int(d["ano"].isna().sum())
    d["ano"] = d["ano"].fillna(d["ano_carimbo"]).astype("Int64")

    # --- Mês: nome PT → número ---
    d["mes"] = d["mes_bruto"].apply(converter_mes).astype("Int64")

    # --- Competência 2026: o formulário NÃO tem a opção de ano 2026 ---
    # Padrão comprovado no dado real: a unidade seleciona 2025 e anota
    # "O ANO É 2026, ESTÁ SEM OPÇÃO". Regra de inferência conservadora:
    #   ano_declarado == ano_carimbo - 1  E  mês declarado <= mês do carimbo
    #   (lag aparente >= 12 meses)  =>  competência real = ano do carimbo.
    # Não captura relatos legítimos atrasados (ex.: DEZ/2025 enviado em
    # JAN/2026: mês 12 > mês 1 → permanece 2025). Toda inferência é
    # sinalizada na aba 🚩 e preservada em 'ano_declarado_form'.
    d["ano_declarado_form"] = pd.to_numeric(
        d["ano_bruto"], errors="coerce"
    ).astype("Int64")
    d["mes_carimbo"] = d["timestamp"].dt.month.astype("Int64")
    # Guarda anti-sobre-correção: só inferir quando o ano do carimbo NÃO
    # existe como opção no formulário (maior ano já declarado por alguém).
    # Regularizações atrasadas legítimas de anos anteriores (o form TINHA a
    # opção) permanecem intocadas — são exatamente o que a cobrança mede.
    maior_ano_form = d["ano_declarado_form"].max()
    mascara_inferencia = (
        (d["ano_declarado_form"] == d["ano_carimbo"] - 1)
        & (d["mes"] <= d["mes_carimbo"])
        & (d["ano_carimbo"] > maior_ano_form)
    )
    mascara_inferencia = mascara_inferencia.fillna(False).astype(bool)
    d["ano_inferido"] = mascara_inferencia
    d.loc[mascara_inferencia, "ano"] = (
        d.loc[mascara_inferencia, "ano_carimbo"].astype("Int64")
    )
    stats["ano_competencia_inferido"] = int(mascara_inferencia.sum())

    # --- Quantidades: parser textual, zero descarte ---
    nasc = d["nascimentos_bruto"].apply(parse_quantidade)
    reg = d["registros_bruto"].apply(parse_quantidade)
    d["nascimentos"] = nasc.apply(lambda x: x[0])
    d["origem_nascimentos"] = nasc.apply(lambda x: x[1])
    d["registros"] = reg.apply(lambda x: x[0])
    d["origem_registros"] = reg.apply(lambda x: x[1])

    stats["nasc_recuperados_texto"] = int(
        d["origem_nascimentos"].isin(["texto_digito", "texto_extenso", "texto_zero"]).sum()
    )
    stats["reg_recuperados_texto"] = int(
        d["origem_registros"].isin(["texto_digito", "texto_extenso", "texto_zero"]).sum()
    )
    stats["nasc_irrecuperaveis"] = int(d["nascimentos"].isna().sum())
    stats["reg_irrecuperaveis"] = int(d["registros"].isna().sum())

    # --- Percentual: coluna "%" texto BR com fallback calculado ---
    d["percentual_original"] = converter_percentual_texto(d["percentual_bruto"])
    # inf (divisão por zero) → NaN — pandas 2.x removeu mode.use_inf_as_na
    d["percentual_calculado"] = (d["registros"] / d["nascimentos"] * 100)
    d["percentual_calculado"] = (
        d["percentual_calculado"]
        .replace([float("inf"), float("-inf")], pd.NA)
    )
    d["percentual_calculado"] = pd.to_numeric(
        d["percentual_calculado"], errors="coerce"
    ).round(2)
    d["percentual"] = d["percentual_original"].fillna(d["percentual_calculado"])
    d["percentual"] = pd.to_numeric(d["percentual"], errors="coerce")
    # Cobertura acima de 100% existe no dado real (registros de nascidos em
    # meses/municípios anteriores) — manter valor real, sinalizar na aba 🚩,
    # e criar versão limitada apenas para médias comparativas.
    d["percentual_cap100"] = d["percentual"].clip(upper=100)

    # --- Déficit ---
    d["deficit"] = d["nascimentos"] - d["registros"]

    # --- Sinalização de anomalias (linha preservada, nunca removida) ---
    def marcar_anomalias(linha) -> str:
        marcas = []
        if pd.isna(linha["nascimentos"]):
            marcas.append("nascimentos irrecuperáveis")
        elif linha["origem_nascimentos"] != "numerico":
            marcas.append("nascimentos extraídos de texto")
        if pd.isna(linha["registros"]):
            marcas.append("registros irrecuperáveis")
        elif linha["origem_registros"] != "numerico":
            marcas.append("registros extraídos de texto")
        if pd.notna(linha["percentual"]) and linha["percentual"] > 100:
            marcas.append("cobertura > 100%")
        if pd.isna(linha["mes"]):
            marcas.append("mês inválido")
        if pd.isna(linha["ano"]):
            marcas.append("ano indeterminado")
        if linha.get("ano_inferido", False):
            marcas.append(
                f"ano de competência inferido: {linha['ano']} "
                f"(formulário sem a opção; declarado {linha['ano_declarado_form']})"
            )
        if pd.isna(linha["municipio"]):
            marcas.append("município ausente")
        return "; ".join(marcas)

    d["anomalias"] = d.apply(marcar_anomalias, axis=1)
    stats["linhas_com_anomalia"] = int((d["anomalias"] != "").sum())
    stats["linhas_percentual_acima_100"] = int((d["percentual"] > 100).sum())

    # --- Campos de texto ---
    for col in ["email", "serventia", "posto_unidade", "motivos"]:
        d[col] = d[col].fillna("Não informado").replace("", "Não informado")

    return d, stats


# ==================== CACHE DE SESSÃO ====================

def inicializar_cache():
    padroes = {
        "dados_cache": None,
        "dados_originais_cache": None,
        "stats_cache": None,
        "conformidade_cache": {},
        "timestamp_cache": None,
        "cache_ativo": False,
    }
    for chave, valor in padroes.items():
        if chave not in st.session_state:
            st.session_state[chave] = valor


def salvar_no_cache(df_proc: pd.DataFrame, df_orig: pd.DataFrame, stats: dict):
    st.session_state.dados_cache = df_proc.copy()
    st.session_state.dados_originais_cache = df_orig.copy()
    st.session_state.stats_cache = dict(stats)
    st.session_state.timestamp_cache = datetime.now()
    st.session_state.cache_ativo = True
    st.session_state.conformidade_cache = {}
    if "municipio" in df_proc.columns:
        for municipio in df_proc["municipio"].dropna().unique():
            analise = analisar_conformidade_municipio(df_proc, municipio)
            if analise:
                st.session_state.conformidade_cache[municipio] = analise


def limpar_cache():
    for chave in [
        "dados_cache", "dados_originais_cache", "stats_cache", "timestamp_cache",
    ]:
        st.session_state[chave] = None
    st.session_state.conformidade_cache = {}
    st.session_state.cache_ativo = False


# ==================== EXPORTAÇÃO (CSV / XLSX / PDF) ====================

def df_para_csv_bytes(df: pd.DataFrame) -> bytes:
    """UTF-8 com BOM: acentos corretos ao abrir direto no Excel."""
    return df.to_csv(index=False).encode("utf-8-sig")


def df_para_xlsx_bytes(df: pd.DataFrame, nome_aba: str = "Dados") -> Optional[bytes]:
    try:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
            df.to_excel(escritor, index=False, sheet_name=nome_aba[:31])
        return buffer.getvalue()
    except Exception:
        return None


def _texto_pdf_seguro(texto: str) -> str:
    """Mantém apenas latin-1 (cobre acentos PT-BR); remove emojis."""
    return re.sub(r"[^\x00-\xff]", "", str(texto))


def texto_para_pdf_bytes(texto: str, titulo: str) -> Optional[bytes]:
    """Relatório em texto corrido → PDF A4."""
    try:
        from fpdf import FPDF
    except ImportError:
        return None
    try:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        avanco = {"new_x": "LMARGIN", "new_y": "NEXT"}  # fpdf2>=2.7: reposiciona cursor
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(0, 8, _texto_pdf_seguro(titulo), **avanco)
        pdf.set_font("Helvetica", "I", 8)
        pdf.multi_cell(
            0, 5,
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            **avanco,
        )
        pdf.ln(2)
        pdf.set_font("Helvetica", size=9)
        for linha in texto.split("\n"):
            limpa = _texto_pdf_seguro(linha.replace("**", "").replace("═", "="))
            pdf.multi_cell(0, 5, limpa if limpa.strip() else " ", **avanco)
        return bytes(pdf.output())
    except Exception:
        return None


def tabela_para_pdf_bytes(
    df: pd.DataFrame, titulo: str, max_linhas: int = 300, max_colunas: int = 10
) -> Optional[bytes]:
    """Tabela → PDF paisagem (limitada para legibilidade em papel)."""
    try:
        from fpdf import FPDF
    except ImportError:
        return None
    try:
        d = df.head(max_linhas).copy()
        colunas = list(d.columns)[:max_colunas]
        pdf = FPDF(orientation="L")
        pdf.set_auto_page_break(auto=True, margin=10)
        pdf.add_page()
        avanco = {"new_x": "LMARGIN", "new_y": "NEXT"}  # fpdf2>=2.7: reposiciona cursor
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 8, _texto_pdf_seguro(titulo), **avanco)
        pdf.set_font("Helvetica", "I", 8)
        aviso = (f"Exibindo {len(d):,} de {len(df):,} linhas"
                 if len(df) > max_linhas else f"{len(d):,} linhas")
        pdf.multi_cell(
            0, 5,
            f"{aviso} - Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            **avanco,
        )
        pdf.ln(1)
        largura = (pdf.w - 20) / len(colunas)
        pdf.set_font("Helvetica", "B", 7)
        for c in colunas:
            pdf.cell(largura, 6, _texto_pdf_seguro(c)[:30], border=1)
        pdf.ln()
        pdf.set_font("Helvetica", size=7)
        for _, linha in d.iterrows():
            for c in colunas:
                valor = linha[c]
                texto = "" if pd.isna(valor) else str(valor)
                pdf.cell(largura, 5, _texto_pdf_seguro(texto)[:30], border=1)
            pdf.ln()
        return bytes(pdf.output())
    except Exception:
        return None


def bloco_exportacao(df: pd.DataFrame, prefixo: str, titulo_pdf: str, chave: str):
    """Trio padrão de botões CSV / XLSX / PDF para qualquer recorte."""
    if df is None or df.empty:
        st.caption("Nenhum dado no recorte atual para exportar.")
        return
    agora = datetime.now().strftime("%Y%m%d_%H%M%S")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "📄 CSV", data=df_para_csv_bytes(df),
            file_name=f"{prefixo}_{agora}.csv", mime="text/csv",
            key=f"{chave}_csv", use_container_width=True,
        )
    with c2:
        xlsx = df_para_xlsx_bytes(df, prefixo[:31])
        if xlsx:
            st.download_button(
                "📊 XLSX", data=xlsx,
                file_name=f"{prefixo}_{agora}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{chave}_xlsx", use_container_width=True,
            )
        else:
            st.caption("XLSX indisponível (adicione openpyxl ao requirements.txt)")
    with c3:
        pdf = tabela_para_pdf_bytes(df, titulo_pdf)
        if pdf:
            st.download_button(
                "🖨️ PDF", data=pdf,
                file_name=f"{prefixo}_{agora}.pdf", mime="application/pdf",
                key=f"{chave}_pdf", use_container_width=True,
            )
        else:
            st.caption("PDF indisponível (adicione fpdf2 ao requirements.txt)")


def tabela_pendencias_por_unidade(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Relatório consolidado de meses faltantes por unidade (município/ano),
    pronto para cobrança — base da exportação de inconformidades."""
    cache = st.session_state.conformidade_cache
    if not cache:
        return None
    serventias_por_municipio = (
        df.groupby("municipio")["serventia"]
        .apply(lambda s: "; ".join(sorted(set(s.dropna().astype(str)))[:3]))
        .to_dict()
    )
    linhas = []
    for municipio, a in cache.items():
        for ano, d in sorted(a["analise_por_ano"].items()):
            if d["meses_faltantes"]:
                linhas.append({
                    "Município": municipio,
                    "Serventia(s)": serventias_por_municipio.get(municipio, ""),
                    "Ano": ano,
                    "Meses Faltantes": ", ".join(
                        NOMES_MESES[m] for m in d["meses_faltantes"]
                    ),
                    "Qtde Meses Faltantes": d["total_faltante"],
                    "Conformidade do Ano (%)": round(d["pct_conformidade"], 1),
                    "Conformidade Geral (%)": round(a["conformidade_geral"], 1),
                    "Status": status_conformidade(a["conformidade_geral"]),
                })
    if not linhas:
        return pd.DataFrame(columns=[
            "Município", "Serventia(s)", "Ano", "Meses Faltantes",
            "Qtde Meses Faltantes", "Conformidade do Ano (%)",
            "Conformidade Geral (%)", "Status",
        ])
    return pd.DataFrame(linhas).sort_values(
        ["Conformidade Geral (%)", "Município", "Ano"]
    )


# ==================== CONFORMIDADE (PROVIMENTO 07/2021) ====================

def analisar_conformidade_municipio(df: pd.DataFrame, municipio: str) -> Optional[dict]:
    d = df[(df["municipio"] == municipio) & df["ano"].notna() & df["mes"].notna()]
    if d.empty:
        return None

    hoje = datetime.now()
    analise_anos = {}
    for ano in sorted(d["ano"].unique()):
        dados_ano = d[d["ano"] == ano]
        informados = sorted(int(m) for m in dados_ano["mes"].unique())
        if int(ano) == hoje.year:
            esperados = list(range(1, hoje.month + 1))
        elif int(ano) > hoje.year:
            esperados = []
        else:
            esperados = list(range(1, 13))
        faltantes = [m for m in esperados if m not in informados]
        total_esp, total_inf = len(esperados), len([m for m in informados if m in esperados])
        analise_anos[int(ano)] = {
            "total_esperado": total_esp,
            "total_informado": total_inf,
            "total_faltante": len(faltantes),
            "pct_conformidade": (total_inf / total_esp * 100) if total_esp else 100.0,
            "meses_faltantes": faltantes,
            "meses_faltantes_nomes": [f"{NOMES_MESES[m]}/{int(ano)}" for m in faltantes],
            "nascimentos": float(dados_ano["nascimentos"].sum(skipna=True)),
            "registros": float(dados_ano["registros"].sum(skipna=True)),
        }

    total_esp = sum(a["total_esperado"] for a in analise_anos.values())
    total_inf = sum(a["total_informado"] for a in analise_anos.values())
    total_falt = total_esp - total_inf
    todos_faltantes = [
        nome for a in analise_anos.values() for nome in a["meses_faltantes_nomes"]
    ]
    nasc_geral = sum(a["nascimentos"] for a in analise_anos.values())
    reg_geral = sum(a["registros"] for a in analise_anos.values())

    return {
        "municipio": municipio,
        "analise_por_ano": analise_anos,
        "total_meses_esperados": total_esp,
        "total_meses_informados": total_inf,
        "total_meses_faltantes": total_falt,
        "conformidade_geral": (total_inf / total_esp * 100) if total_esp else 100.0,
        "defasagem_geral": (total_falt / total_esp * 100) if total_esp else 0.0,
        "todos_meses_faltantes": todos_faltantes,
        "total_nascimentos_geral": nasc_geral,
        "total_registros_geral": reg_geral,
        "deficit_geral": nasc_geral - reg_geral,
    }


def status_conformidade(pct: float) -> str:
    return "🟢 Conforme" if pct >= 90 else ("🟡 Atenção" if pct >= 70 else "🔴 Crítico")


def tabela_conformidade_geral() -> Optional[pd.DataFrame]:
    cache = st.session_state.conformidade_cache
    if not cache:
        return None
    linhas = []
    for municipio, a in cache.items():
        linhas.append({
            "Município": municipio,
            "Conformidade (%)": round(a["conformidade_geral"], 1),
            "Meses Informados": a["total_meses_informados"],
            "Meses Faltantes": a["total_meses_faltantes"],
            "Status": status_conformidade(a["conformidade_geral"]),
            "Nascimentos": int(a["total_nascimentos_geral"]),
            "Registros": int(a["total_registros_geral"]),
            "Déficit": int(a["deficit_geral"]),
        })
    return pd.DataFrame(linhas).sort_values("Conformidade (%)", ascending=False)


def gerar_relatorio_conformidade(a: dict) -> str:
    cobertura = (
        a["total_registros_geral"] / a["total_nascimentos_geral"] * 100
        if a["total_nascimentos_geral"] else 0.0
    )
    if not a["todos_meses_faltantes"]:
        return f"""
**📋 RELATÓRIO DE CONFORMIDADE — PROVIMENTO 07/2021**

✅ **A unidade {a['municipio']} está em CONFORMIDADE TOTAL.**

• Percentual de Conformidade: {a['conformidade_geral']:.1f}%
• Total de Nascimentos: {a['total_nascimentos_geral']:,.0f}
• Total de Registros: {a['total_registros_geral']:,.0f}
• Percentual de Cobertura: {cobertura:.1f}%
"""
    n_falt = len(a["todos_meses_faltantes"])
    urgencia = (
        "ALTA — mais de 6 meses em atraso" if n_falt > 6
        else "MÉDIA — entre 3 e 6 meses em atraso" if n_falt > 3
        else "BAIXA — poucos meses em atraso"
    )
    lista = "\n".join(f"• {m}" for m in a["todos_meses_faltantes"])
    return f"""
**📋 RELATÓRIO DE CONFORMIDADE — PROVIMENTO 07/2021**

⚠️ **A unidade {a['municipio']} possui PENDÊNCIAS.**

**RESUMO EXECUTIVO:**
• Percentual de Conformidade: {a['conformidade_geral']:.1f}%
• Percentual de Defasagem: {a['defasagem_geral']:.1f}%
• Total de meses em débito: {n_falt}
• Total de Nascimentos: {a['total_nascimentos_geral']:,.0f}
• Total de Registros: {a['total_registros_geral']:,.0f}
• Déficit de Registros: {a['deficit_geral']:,.0f}
• Percentual de Cobertura: {cobertura:.1f}%

**🔴 MESES EM DÉBITO:**
{lista}

**📝 AÇÃO NECESSÁRIA:** regularizar os envios em atraso conforme o
Provimento 07/2021 (envio mensal obrigatório até o dia 10 de cada mês).

**⚡ URGÊNCIA:** {urgencia}
"""


# ==================== GRÁFICOS ====================

def bloco_graficos(df: pd.DataFrame):
    st.subheader("📊 Centro de Análise Gráfica")

    col1, col2, col3 = st.columns(3)
    with col1:
        tipo = st.selectbox(
            "🎯 Tipo de Análise:",
            [
                "Nascimentos vs Registros",
                "Evolução Temporal",
                "Análise de Percentuais",
                "Déficit por Região",
                "Comparativo de Performance",
                "Análise de Tendências",
                "Distribuição Estatística",
                "Conformidade Visual",
            ],
        )
    with col2:
        mapa = {
            "Município": "municipio", "Serventia": "serventia",
            "Posto/Unidade": "posto_unidade", "Ano": "ano", "Mês": "mes",
        }
        opcoes = [rotulo for rotulo, col in mapa.items() if col in df.columns]
        agrupamento = st.selectbox("📋 Agrupar por:", opcoes)
    with col3:
        limite = st.slider("📊 Quantidade no gráfico:", 5, 100, 25)

    coluna = mapa.get(agrupamento, "municipio")
    st.markdown("---")

    if tipo == "Nascimentos vs Registros":
        g = df.groupby(coluna, dropna=True).agg(
            nascimentos=("nascimentos", "sum"), registros=("registros", "sum")
        ).reset_index().nlargest(limite, "nascimentos")
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📊 Nascimentos vs Registros")
            st.bar_chart(g.set_index(coluna)[["nascimentos", "registros"]])
        with c2:
            st.subheader("📈 Gap de Registros")
            g["gap"] = g["nascimentos"] - g["registros"]
            st.bar_chart(g.set_index(coluna)["gap"])
        g["percentual"] = (g["registros"] / g["nascimentos"] * 100).round(1)
        st.subheader("📋 Dados Detalhados")
        st.dataframe(g, use_container_width=True)

    elif tipo == "Evolução Temporal":
        c1, c2 = st.columns(2)
        with c1:
            modo = st.selectbox("Modo:", ["Mensal", "Anual", "Trimestral"])
        with c2:
            metricas = st.multiselect(
                "Métricas:", ["Nascimentos", "Registros", "Percentual", "Déficit"],
                default=["Nascimentos", "Registros"],
            )
        base = df.dropna(subset=["ano", "mes"]).copy()
        if modo == "Mensal":
            t = base.groupby(["ano", "mes"]).agg(
                registros=("registros", "sum"), nascimentos=("nascimentos", "sum")
            ).reset_index()
            t["periodo"] = t["ano"].astype(str) + "-" + t["mes"].astype(int).astype(str).str.zfill(2)
            t = t.sort_values(["ano", "mes"])
        elif modo == "Anual":
            t = base.groupby("ano").agg(
                registros=("registros", "sum"), nascimentos=("nascimentos", "sum")
            ).reset_index()
            t["periodo"] = t["ano"].astype(str)
        else:
            base["trimestre"] = ((base["mes"].astype(int) - 1) // 3) + 1
            t = base.groupby(["ano", "trimestre"]).agg(
                registros=("registros", "sum"), nascimentos=("nascimentos", "sum")
            ).reset_index()
            t["periodo"] = t["ano"].astype(str) + "-T" + t["trimestre"].astype(str)
        t["percentual"] = (t["registros"] / t["nascimentos"] * 100).round(1)
        t["deficit"] = t["nascimentos"] - t["registros"]
        cols = [c for rot, c in [
            ("Nascimentos", "nascimentos"), ("Registros", "registros"), ("Déficit", "deficit")
        ] if rot in metricas]
        if cols:
            st.subheader(f"📈 Evolução {modo}")
            st.line_chart(t.set_index("periodo")[cols])
        if "Percentual" in metricas:
            st.subheader("📊 Evolução do Percentual de Cobertura")
            st.line_chart(t.set_index("periodo")["percentual"])
        st.subheader("📋 Dados Temporais")
        st.dataframe(t, use_container_width=True)

    elif tipo == "Análise de Percentuais":
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📊 Ranking de Percentuais")
            g = (
                df.groupby(coluna)["percentual"].mean()
                .sort_values(ascending=False).head(limite)
            )
            st.bar_chart(g)
        with c2:
            st.subheader("📈 Distribuição de Performance")
            faixas = pd.cut(
                df["percentual_cap100"],
                bins=[0, 50, 70, 85, 95, 100],
                labels=["Crítico (0-50%)", "Baixo (50-70%)", "Médio (70-85%)",
                        "Bom (85-95%)", "Excelente (95-100%)"],
                include_lowest=True,
            )
            st.bar_chart(faixas.value_counts())
        st.subheader("📊 Estatísticas Descritivas")
        p = df["percentual"].dropna()
        if not p.empty:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Média", f"{p.mean():.1f}%")
            m2.metric("Mediana", f"{p.median():.1f}%")
            m3.metric("Desvio Padrão", f"{p.std():.1f}")
            cv = p.std() / p.mean() * 100 if p.mean() else 0
            m4.metric("Coef. Variação", f"{cv:.1f}%")

    elif tipo == "Déficit por Região":
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("⚠️ Maiores Déficits")
            g = df.groupby(coluna)["deficit"].sum().sort_values(ascending=False).head(limite)
            st.bar_chart(g)
        with c2:
            st.subheader("📊 Déficit vs Nascimentos (%)")
            g2 = df.groupby(coluna).agg(
                deficit=("deficit", "sum"), nascimentos=("nascimentos", "sum")
            )
            g2 = g2[g2["nascimentos"] > 0]
            g2["pct_deficit"] = (g2["deficit"] / g2["nascimentos"] * 100).round(1)
            st.bar_chart(g2["pct_deficit"].sort_values(ascending=False).head(limite))

    elif tipo == "Comparativo de Performance":
        g = df.groupby(coluna).agg(
            nascimentos=("nascimentos", "sum"), registros=("registros", "sum"),
            percentual=("percentual", "mean"),
        ).reset_index().sort_values("percentual", ascending=False).head(limite)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🏆 Top Performers")
            st.bar_chart(g.head(10).set_index(coluna)["percentual"])
        with c2:
            st.subheader("⚠️ Necessitam Atenção")
            st.bar_chart(g.tail(10).set_index(coluna)["percentual"])

    elif tipo == "Análise de Tendências":
        base = df.dropna(subset=["ano", "mes"])
        t = base.groupby(["ano", "mes"]).agg(percentual=("percentual", "mean")).reset_index()
        t["periodo"] = t["ano"].astype(str) + "-" + t["mes"].astype(int).astype(str).str.zfill(2)
        t = t.sort_values(["ano", "mes"])
        t["media_movel_3"] = t["percentual"].rolling(3).mean()
        t["media_movel_6"] = t["percentual"].rolling(6).mean()
        st.subheader("📈 Análise de Tendências")
        c1, c2 = st.columns(2)
        with c1:
            st.line_chart(t.set_index("periodo")[["percentual", "media_movel_3", "media_movel_6"]])
        with c2:
            saz = base.groupby("mes")["percentual"].mean()
            saz.index = saz.index.map(lambda m: NOMES_MESES.get(int(m), str(m)))
            st.bar_chart(saz)

    elif tipo == "Distribuição Estatística":
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📊 Histograma de Percentuais (0-100)")
            faixas = pd.cut(df["percentual_cap100"], bins=range(0, 101, 10), include_lowest=True)
            st.bar_chart(faixas.value_counts().sort_index().astype(int))
        with c2:
            st.subheader("📈 Quartis")
            p = df["percentual"].dropna()
            if not p.empty:
                q = pd.Series(
                    [p.quantile(0.25), p.quantile(0.5), p.quantile(0.75)],
                    index=["Q1 (25%)", "Q2 (50%)", "Q3 (75%)"],
                )
                st.bar_chart(q)

    elif tipo == "Conformidade Visual":
        tabela = tabela_conformidade_geral()
        if tabela is not None:
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("📊 Ranking de Conformidade")
                st.bar_chart(tabela.head(20).set_index("Município")["Conformidade (%)"])
            with c2:
                st.subheader("⚠️ Mais Pendências")
                pend = tabela.sort_values("Meses Faltantes", ascending=False).head(20)
                st.bar_chart(pend.set_index("Município")["Meses Faltantes"])
            faixas = pd.cut(
                tabela["Conformidade (%)"], bins=[0, 50, 70, 85, 95, 100],
                labels=["Crítico", "Baixo", "Médio", "Bom", "Excelente"],
                include_lowest=True,
            )
            st.subheader("📈 Distribuição de Conformidade")
            st.bar_chart(faixas.value_counts())
        else:
            st.info("Análises de conformidade ainda não calculadas.")


# ==================== ANÁLISE GEOGRÁFICA ====================

def bloco_geografico(df: pd.DataFrame) -> pd.DataFrame:
    st.subheader("🗺️ Análise Geográfica Completa")
    g = df.groupby("municipio").agg(
        nascimentos=("nascimentos", "sum"),
        registros=("registros", "sum"),
        percentual=("percentual", "mean"),
        deficit=("deficit", "sum"),
        serventias=("serventia", "nunique"),
        postos=("posto_unidade", "nunique"),
    ).round(2).reset_index()

    conf = st.session_state.conformidade_cache
    g["conformidade"] = g["municipio"].map(
        lambda m: round(conf[m]["conformidade_geral"], 1) if m in conf else None
    )

    g.columns = [
        "Município", "Total Nascimentos", "Total Registros", "Percentual Médio",
        "Déficit Total", "Nº Serventias", "Nº Postos/Unidades", "Conformidade (%)",
    ]
    g["Status Performance"] = g["Percentual Médio"].apply(
        lambda x: "🟢 Excelente" if x >= 90 else ("🟡 Bom" if x >= 70 else "🔴 Atenção")
    )
    g["Status Conformidade"] = g["Conformidade (%)"].apply(
        lambda x: status_conformidade(x) if pd.notna(x) else "—"
    )

    c1, c2 = st.columns(2)
    with c1:
        criterio = st.selectbox(
            "Ordenar por:",
            ["Percentual Médio", "Total Nascimentos", "Déficit Total", "Conformidade (%)"],
        )
    with c2:
        crescente = st.checkbox("Ordem crescente", value=False)
    g = g.sort_values(criterio, ascending=crescente)

    f1, f2, f3 = st.columns(3)
    with f1:
        filtro_perf = st.selectbox(
            "Filtrar Status Performance:", ["Todos", "🟢 Excelente", "🟡 Bom", "🔴 Atenção"]
        )
    with f2:
        filtro_conf = st.selectbox(
            "Filtrar Status Conformidade:", ["Todos", "🟢 Conforme", "🟡 Atenção", "🔴 Crítico"]
        )
    with f3:
        limite = st.slider("Mostrar quantos municípios:", 10, max(len(g), 10), min(50, len(g)))

    filtrado = g.copy()
    if filtro_perf != "Todos":
        filtrado = filtrado[filtrado["Status Performance"] == filtro_perf]
    if filtro_conf != "Todos":
        filtrado = filtrado[filtrado["Status Conformidade"] == filtro_conf]
    st.dataframe(filtrado.head(limite), use_container_width=True, height=500)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🟢 Performance Excelente", int((g["Percentual Médio"] >= 90).sum()))
    m2.metric("🟡 Performance Boa",
              int(((g["Percentual Médio"] >= 70) & (g["Percentual Médio"] < 90)).sum()))
    m3.metric("🔴 Precisam Atenção", int((g["Percentual Médio"] < 70).sum()))
    m4.metric("⚠️ Déficit Total", f"{g['Déficit Total'].sum():,.0f}")
    m5.metric("✅ Conformes", int((g["Conformidade (%)"] >= 90).sum()))
    return g


# ==================== ABA DE ANOMALIAS ====================

def bloco_anomalias(df: pd.DataFrame, df_filtrado: pd.DataFrame, stats: dict):
    st.subheader("🚩 Anomalias de Percentual e Qualidade de Dados")
    st.markdown(
        "Nenhuma linha é descartada: registros problemáticos são **preservados e "
        "sinalizados** aqui para correção manual na origem (Google Forms/Sheets)."
    )

    usar_filtros = st.checkbox(
        "🔍 Aplicar os filtros da sidebar (ano/mês/município/serventia) às anomalias",
        value=False,
        help="Marque para auditar as anomalias apenas do recorte filtrado — "
             "útil para emitir a lista de correções de uma unidade específica.",
    )
    if usar_filtros:
        df = df_filtrado
        st.info(f"Recorte filtrado ativo: {len(df):,} registros na base de análise.")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📊 Linhas Totais", f"{stats['total_linhas']:,}")
    m2.metric("🔤 Qtde Recuperadas de Texto",
              f"{stats['nasc_recuperados_texto'] + stats['reg_recuperados_texto']:,}")
    m3.metric("❌ Células Irrecuperáveis",
              f"{stats['nasc_irrecuperaveis'] + stats['reg_irrecuperaveis']:,}")
    m4.metric("📈 Cobertura > 100%", f"{stats['linhas_percentual_acima_100']:,}")

    st.markdown("---")

    anomalos = df[df["anomalias"] != ""].copy()
    st.markdown(f"**{len(anomalos):,} linhas sinalizadas** "
                f"({len(anomalos) / max(len(df), 1) * 100:.1f}% do total)")

    tipos = sorted({t for lista in anomalos["anomalias"] for t in lista.split("; ") if t})
    filtro_tipo = st.multiselect("Filtrar por tipo de anomalia:", tipos, default=tipos)
    if filtro_tipo:
        mascara = anomalos["anomalias"].apply(
            lambda a: any(t in a for t in filtro_tipo)
        )
        anomalos = anomalos[mascara]

    colunas_exibir = [
        "data_formatada", "municipio", "serventia", "posto_unidade", "ano", "mes",
        "nascimentos_bruto", "nascimentos", "origem_nascimentos",
        "registros_bruto", "registros", "origem_registros",
        "percentual", "anomalias",
    ]
    colunas_exibir = [c for c in colunas_exibir if c in anomalos.columns]
    st.dataframe(anomalos[colunas_exibir], use_container_width=True, height=450)

    # Ranking de municípios com mais anomalias
    if not anomalos.empty:
        st.subheader("🏙️ Municípios com Mais Anomalias")
        st.bar_chart(anomalos["municipio"].value_counts().head(20))

    # Cobertura > 100% detalhada
    acima = df[df["percentual"] > 100].copy()
    if not acima.empty:
        with st.expander(f"📈 Detalhe: {len(acima)} lançamentos com cobertura acima de 100%"):
            st.markdown(
                "Cobertura acima de 100% ocorre quando a serventia registra no mês "
                "crianças nascidas em meses anteriores ou em outros municípios — "
                "valor mantido sem corte para auditoria."
            )
            st.dataframe(
                acima[["data_formatada", "municipio", "serventia", "ano", "mes",
                       "nascimentos", "registros", "percentual"]]
                .sort_values("percentual", ascending=False),
                use_container_width=True,
            )

    st.subheader("📤 Exportar Lista de Correções (recorte atual)")
    st.markdown(
        "Planilha de trabalho para a unidade corrigir na origem: valor bruto "
        "digitado, valor interpretado e o motivo da sinalização."
    )
    bloco_exportacao(
        anomalos[colunas_exibir],
        prefixo="anomalias_correcao",
        titulo_pdf="Anomalias para Correção - Provimento 07/2021",
        chave="exp_anomalias",
    )


# ==================== RELATÓRIO EXECUTIVO ====================

def gerar_relatorio_completo(df: pd.DataFrame, stats: dict) -> str:
    total_nasc = df["nascimentos"].sum(skipna=True)
    total_reg = df["registros"].sum(skipna=True)
    pct_geral = (total_reg / total_nasc * 100) if total_nasc else 0.0
    deficit = total_nasc - total_reg
    data_ini = df["timestamp"].min()
    data_fim = df["timestamp"].max()

    conf = st.session_state.conformidade_cache
    conf_media = (
        sum(a["conformidade_geral"] for a in conf.values()) / len(conf) if conf else None
    )

    r = f"""
**RELATÓRIO EXECUTIVO COMPLETO — PROVIMENTO 07/2021**
**Sistema de Monitoramento de Registros de Nascimentos v4.0**

═══════════════════════════════════════════════════════════════

**INTEGRIDADE DOS DADOS (POLÍTICA 100% PRESERVADOS):**
• Linhas carregadas: {stats['total_linhas']:,} — nenhuma descartada
• Quantidades recuperadas de texto: {stats['nasc_recuperados_texto'] + stats['reg_recuperados_texto']:,}
• Células irrecuperáveis (sinalizadas): {stats['nasc_irrecuperaveis'] + stats['reg_irrecuperaveis']:,}
• Anos preenchidos via carimbo de data/hora: {stats['ano_via_fallback']:,}
• Competências com ano inferido (form sem opção 2026): {stats.get('ano_competencia_inferido', 0):,}
• Linhas com alguma anomalia sinalizada: {stats['linhas_com_anomalia']:,}

**PERÍODO DE ANÁLISE:**
• Início: {data_ini.strftime('%d/%m/%Y') if pd.notna(data_ini) else 'N/A'}
• Fim: {data_fim.strftime('%d/%m/%Y') if pd.notna(data_fim) else 'N/A'}
• Registros no recorte atual: {len(df):,}

**INDICADORES PRINCIPAIS:**
• Total de Nascimentos: {total_nasc:,.0f}
• Total de Registros Realizados: {total_reg:,.0f}
• Percentual Geral de Cobertura: {pct_geral:.2f}%
• Déficit Total de Registros: {deficit:,.0f}

**CONFORMIDADE PROVIMENTO 07/2021:**"""
    if conf_media is not None:
        status = ("🟢 CONFORME" if conf_media >= 90
                  else "🟡 ATENÇÃO" if conf_media >= 70 else "🔴 CRÍTICO")
        r += f"""
• Conformidade Média Geral: {conf_media:.1f}%
• Municípios Analisados: {len(conf)}
• Status Geral: {status}"""
    else:
        r += "\n• Análise de conformidade não disponível"

    r += f"""

**DISTRIBUIÇÃO GEOGRÁFICA:**
• Municípios Atendidos: {df['municipio'].nunique()}
• Serventias Participantes: {df['serventia'].nunique()}
• Postos/Unidades Interligadas: {df['posto_unidade'].nunique()}

**DISTRIBUIÇÃO TEMPORAL:**
• Anos Cobertos: {df['ano'].nunique()}
• Meses com Dados: {df['mes'].nunique()}
"""

    perf = df.dropna(subset=["percentual"]).groupby("municipio")["percentual"].mean()
    if not perf.empty:
        exc = int((perf >= 90).sum())
        bom = int(((perf >= 70) & (perf < 90)).sum())
        ate = int((perf < 70).sum())
        r += f"""
**ANÁLISE DE PERFORMANCE:**
• Performance Excelente (≥90%): {exc} municípios ({exc / len(perf) * 100:.1f}%)
• Performance Boa (70-89%): {bom} municípios ({bom / len(perf) * 100:.1f}%)
• Necessitam Atenção (<70%): {ate} municípios ({ate / len(perf) * 100:.1f}%)

**TOP 10 MUNICÍPIOS (Maior Percentual):**"""
        for i, (m, p) in enumerate(perf.nlargest(10).items(), 1):
            r += f"\n{i:2d}. {m}: {p:.1f}%"
        if ate > 0:
            r += "\n\n**MUNICÍPIOS QUE PRECISAM DE ATENÇÃO URGENTE:**"
            for i, (m, p) in enumerate(perf.nsmallest(min(10, ate)).items(), 1):
                r += f"\n{i:2d}. {m}: {p:.1f}%"

    if conf:
        criticos = sorted(
            ((m, a["conformidade_geral"], len(a["todos_meses_faltantes"]))
             for m, a in conf.items() if a["conformidade_geral"] < 70),
            key=lambda x: x[1],
        )
        if criticos:
            r += "\n\n**MUNICÍPIOS COM CONFORMIDADE CRÍTICA (<70%):**"
            for m, c, f in criticos[:10]:
                r += f"\n• {m}: {c:.1f}% ({f} meses em débito)"

    r += f"""

═══════════════════════════════════════════════════════════════
**RECOMENDAÇÕES ESTRATÉGICAS:**

1. QUALIDADE: corrigir na origem as {stats['nasc_irrecuperaveis'] + stats['reg_irrecuperaveis']:,} células irrecuperáveis (aba 🚩)
2. FORMULÁRIO: incluir a opção de ano 2026 no Google Forms (respostas já chegam sem ano)
3. PADRONIZAÇÃO: restringir os campos de quantidade a somente números no formulário
4. CONFORMIDADE: cobrança sistemática dos municípios em débito
5. MONITORAMENTO: rotina semanal de acompanhamento
6. COBERTURA >100%: auditar os {stats['linhas_percentual_acima_100']:,} lançamentos (registros de meses anteriores)

═══════════════════════════════════════════════════════════════
Relatório gerado automaticamente em {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}
Sistema Avançado v4.0 — Provimento 07/2021 — Política: 100% dos dados preservados
"""
    return r


# ==================== INTERFACE PRINCIPAL ====================

def main():
    inicializar_cache()

    st.title("📊 Sistema Avançado v4.0 — Provimento 07/2021")
    st.markdown(
        "**Registro Civil em Unidades Interligadas • 100% dos dados preservados • "
        "Parser textual • Anomalias sinalizadas**"
    )

    # ---------- SIDEBAR ----------
    st.sidebar.header("⚙️ Central de Controle")

    st.sidebar.subheader("💾 Cache Persistente")
    if st.session_state.cache_ativo:
        minutos = int((datetime.now() - st.session_state.timestamp_cache).total_seconds() / 60)
        st.sidebar.success(f"✅ Cache ativo há {minutos} min")
        st.sidebar.info(f"📊 {len(st.session_state.dados_cache):,} registros")
        st.sidebar.info(f"⚖️ {len(st.session_state.conformidade_cache)} análises de conformidade")
        c1, c2 = st.sidebar.columns(2)
        with c1:
            if st.button("🗑️ Limpar", help="Limpa todo o cache"):
                limpar_cache()
                st.rerun()
        with c2:
            st.download_button(
                "💾 Export",
                data=st.session_state.dados_cache.to_csv(index=False),
                file_name=f"cache_completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )
    else:
        st.sidebar.warning("⚠️ Cache inativo")
        st.sidebar.info("Carregue dados para ativar")

    st.sidebar.subheader("📥 Carregamento de Dados")
    fonte = st.sidebar.radio(
        "Selecione a fonte:", ["URL Padrão", "URL Personalizada", "Upload de Arquivo"]
    )

    df_bruto = None
    carregar_novos = False

    if fonte == "URL Padrão":
        st.sidebar.info("📡 Planilha oficial do Provimento 07/2021")
        if st.sidebar.button("🔄 Carregar Dados", type="primary"):
            with st.spinner("Carregando dados da planilha oficial..."):
                df_bruto = carregar_dados_url(URL_PADRAO)
                carregar_novos = True
    elif fonte == "URL Personalizada":
        url = st.sidebar.text_input("🔗 Cole a URL do CSV:", placeholder="https://...")
        if url and st.sidebar.button("🔄 Carregar da URL", type="primary"):
            with st.spinner("Carregando dados da URL..."):
                df_bruto = carregar_dados_url(url)
                carregar_novos = True
    else:
        arquivo = st.sidebar.file_uploader("📁 Envie seu arquivo CSV:", type=["csv"])
        if arquivo:
            with st.spinner("Processando arquivo enviado..."):
                df_bruto = carregar_dados_arquivo(arquivo)
                carregar_novos = True

    # ---------- PROCESSAMENTO ----------
    if df_bruto is not None and carregar_novos:
        with st.spinner("Processando 100% dos registros e pré-calculando conformidade..."):
            df_proc, stats = processar_dados(df_bruto)
            salvar_no_cache(df_proc, df_bruto, stats)
        st.success(
            f"✅ **{len(df_proc):,} registros** processados e armazenados no cache "
            f"(100% preservados) — {stats['nasc_recuperados_texto'] + stats['reg_recuperados_texto']} "
            f"quantidades recuperadas de texto."
        )
    elif st.session_state.cache_ativo:
        st.info("📊 **Sistema usando dados em cache.** Para atualizar, use a sidebar.")
    else:
        st.info("👆 **Selecione uma fonte de dados na barra lateral para começar.**")
        st.markdown("""
## 🚀 Sistema Avançado v4.0 — Principais Funcionalidades

### 🛡️ **Política 100% dos Dados Preservados**
✅ Nenhuma linha descartada — anomalias sinalizadas, nunca removidas
✅ Parser textual: "OITO NASCIMENTO", "0 (ZERO)", "NÃO HOUVE" → números
✅ Ano em branco (incl. 2026 sem opção no form) → recuperado do carimbo
✅ Percentual "62,07%" texto BR → numérico sem TypeError

### 📊 **Gráficos Interativos** — 8 tipos de análise, múltiplos agrupamentos

### ⚖️ **Conformidade Provimento 07/2021** — envio mensal até o dia 10

### 🗺️ **Análise Geográfica** — 122 municípios, serventias e postos

### 🚩 **Aba de Anomalias** — auditoria de células irrecuperáveis e cobertura >100%

### 📋 **Relatório Executivo** — integridade + performance + conformidade
""")
        return

    df_proc = st.session_state.dados_cache
    df_bruto = st.session_state.dados_originais_cache
    stats = st.session_state.stats_cache

    # ---------- FILTROS ----------
    st.sidebar.subheader("🔍 Filtros Avançados")
    df_completo = df_proc.copy()
    df_f = df_proc.copy()

    with st.sidebar:
        anos = sorted(int(a) for a in df_f["ano"].dropna().unique())
        if anos:
            ano_sel = st.selectbox("📅 Ano:", ["Todos"] + anos, key="filtro_ano")
            if ano_sel != "Todos":
                df_f = df_f[df_f["ano"] == ano_sel]

        meses = sorted(int(m) for m in df_f["mes"].dropna().unique())
        if meses:
            opcoes_mes = ["Todos"] + [f"{NOMES_MESES[m]} ({m})" for m in meses]
            mes_sel = st.selectbox("📅 Mês:", opcoes_mes, key="filtro_mes")
            if mes_sel != "Todos":
                numero = int(mes_sel.split("(")[1].split(")")[0])
                df_f = df_f[df_f["mes"] == numero]

        municipios = sorted(df_f["municipio"].dropna().unique())
        if municipios:
            busca = st.text_input("🔍 Buscar município:", placeholder="Digite para filtrar...")
            lista = [m for m in municipios if busca.lower() in m.lower()] if busca else municipios
            mun_sel = st.selectbox("🏙️ Município:", ["Todos"] + lista, key="filtro_municipio")
            if mun_sel != "Todos":
                df_f = df_f[df_f["municipio"] == mun_sel]

        serventias = sorted(df_f["serventia"].dropna().unique())
        if serventias and len(serventias) <= 50:
            serv_sel = st.selectbox("🏢 Serventia:", ["Todas"] + serventias, key="filtro_serventia")
            if serv_sel != "Todas":
                df_f = df_f[df_f["serventia"] == serv_sel]

        # Filtro de percentual — blindado: dtype numérico garantido no
        # processamento; aqui apenas ignora NaN e protege recorte vazio
        p_validos = df_f["percentual"].dropna()
        if len(p_validos) > 1:
            min_p, max_p = float(p_validos.min()), float(p_validos.max())
            if min_p < max_p:
                faixa = st.slider(
                    "📊 Faixa de Percentual:", min_p, max_p, (min_p, max_p),
                    step=0.1, key="filtro_percentual",
                )
                incluir_nan = st.checkbox(
                    "Incluir registros sem percentual", value=True,
                    help="Linhas com quantidades irrecuperáveis não têm percentual",
                )
                mascara = df_f["percentual"].between(faixa[0], faixa[1])
                if incluir_nan:
                    mascara = mascara | df_f["percentual"].isna()
                df_f = df_f[mascara]

        if len(df_f) != len(df_completo):
            st.success(f"🎯 **{len(df_f):,}** de **{len(df_completo):,}** registros")
            st.info(f"📉 Redução: {(1 - len(df_f) / len(df_completo)) * 100:.1f}%")
        else:
            st.info(f"📊 **{len(df_f):,}** registros (sem filtros)")

    # ---------- ABAS ----------
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Dashboard Principal",
        "⚖️ Análise de Conformidade",
        "📈 Gráficos Avançados",
        "🗺️ Análise Geográfica",
        "🚩 Anomalias",
        "📋 Relatório Executivo",
    ])

    # ===== TAB 1: DASHBOARD =====
    with tab1:
        st.header("📈 Dashboard Principal Interativo")
        c1, c2, c3, c4, c5 = st.columns(5)
        total_nasc = df_f["nascimentos"].sum(skipna=True)
        total_reg = df_f["registros"].sum(skipna=True)
        c1.metric("👶 Nascimentos", f"{total_nasc:,.0f}")
        c2.metric("📝 Registros", f"{total_reg:,.0f}")
        pct_medio = df_f["percentual"].mean(skipna=True)
        if pd.notna(pct_medio):
            c3.metric("📊 Percentual Médio", f"{pct_medio:.1f}%", f"{pct_medio - 85:+.1f}% vs meta 85%")
        else:
            c3.metric("📊 Percentual Médio", "—")
        c4.metric("🏙️ Municípios", int(df_f["municipio"].nunique()))
        c5.metric("⚠️ Déficit Total", f"{df_f['deficit'].sum(skipna=True):,.0f}")

        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🎯 Quick Insights")
            perf = df_f.dropna(subset=["percentual"]).groupby("municipio")["percentual"].mean()
            if not perf.empty:
                st.success(f"🏆 Melhor: **{perf.idxmax()}** ({perf.max():.1f}%)")
                st.error(f"⚠️ Precisa atenção: **{perf.idxmin()}** ({perf.min():.1f}%)")
        with c2:
            st.subheader("📊 Distribuição de Performance")
            p = df_f["percentual"]
            st.write(f"🟢 Excelente (≥90%): **{int((p >= 90).sum()):,}** registros")
            st.write(f"🟡 Bom (70-89%): **{int(((p >= 70) & (p < 90)).sum()):,}** registros")
            st.write(f"🔴 Atenção (<70%): **{int((p < 70).sum()):,}** registros")
            st.write(f"⚪ Sem percentual: **{int(p.isna().sum()):,}** registros (ver aba 🚩)")

        st.markdown("---")
        st.subheader("📋 Dados Detalhados (Cache Ativo)")
        c1, c2 = st.columns(2)
        with c1:
            por_pagina = st.selectbox("Registros por página:", [25, 50, 100, 200], index=1)
        with c2:
            total_paginas = max((len(df_f) + por_pagina - 1) // por_pagina, 1)
            pagina = (
                st.number_input("Página:", min_value=1, max_value=total_paginas, value=1)
                if total_paginas > 1 else 1
            )
        inicio = (pagina - 1) * por_pagina
        fim = inicio + por_pagina

        colunas = ["data_formatada", "municipio", "serventia", "posto_unidade",
                   "ano", "mes", "nascimentos", "registros", "percentual", "deficit"]
        rotulos = {
            "data_formatada": "Data/Hora", "municipio": "Município",
            "serventia": "Serventia", "posto_unidade": "Posto/Unidade",
            "ano": "Ano", "mes": "Mês", "nascimentos": "Nascimentos",
            "registros": "Registros", "percentual": "Percentual (%)", "deficit": "Déficit",
        }
        pagina_df = df_f[colunas].iloc[inicio:fim].rename(columns=rotulos)
        st.dataframe(pagina_df, use_container_width=True, height=500)
        st.info(f"Exibindo registros {inicio + 1} a {min(fim, len(df_f))} de {len(df_f):,} total")

        st.subheader("💾 Exportação do Recorte Filtrado (CSV / XLSX / PDF)")
        colunas_export = [c for c in colunas if c in df_f.columns] + ["anomalias"]
        bloco_exportacao(
            df_f[colunas_export].rename(columns=rotulos),
            prefixo="dados_filtrados",
            titulo_pdf="Dados Filtrados - Provimento 07/2021",
            chave="exp_dashboard",
        )
        with st.expander("📁 Outras exportações (base completa)"):
            agora = datetime.now().strftime("%Y%m%d_%H%M%S")
            d1, d2 = st.columns(2)
            with d1:
                st.download_button(
                    "📁 Dados Originais Brutos (CSV)",
                    data=df_para_csv_bytes(df_bruto),
                    file_name=f"dados_originais_{agora}.csv", mime="text/csv",
                )
            with d2:
                st.download_button(
                    "💾 Cache Completo Processado (CSV)",
                    data=df_para_csv_bytes(st.session_state.dados_cache),
                    file_name=f"cache_completo_{agora}.csv", mime="text/csv",
                )

    # ===== TAB 2: CONFORMIDADE =====
    with tab2:
        st.header("⚖️ Central de Análise de Conformidade")
        st.markdown("**Monitoramento do cumprimento do Provimento 07/2021** "
                    "(envio mensal obrigatório até o dia 10)")

        tabela = tabela_conformidade_geral()
        if tabela is not None:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("🟢 Conformes", int((tabela["Conformidade (%)"] >= 90).sum()))
            c2.metric("🟡 Atenção", int(((tabela["Conformidade (%)"] >= 70)
                                         & (tabela["Conformidade (%)"] < 90)).sum()))
            c3.metric("🔴 Críticos", int((tabela["Conformidade (%)"] < 70).sum()))
            c4.metric("📊 Média Geral", f"{tabela['Conformidade (%)'].mean():.1f}%")

            st.subheader("📋 Status de Conformidade por Município")
            f1, f2 = st.columns(2)
            with f1:
                filtro = st.selectbox(
                    "Filtrar por status:",
                    ["Todos", "🟢 Conforme", "🟡 Atenção", "🔴 Crítico"],
                    key="conf_filtro",
                )
            with f2:
                limite = st.slider("Mostrar quantos municípios:", 10,
                                   max(len(tabela), 10), min(25, len(tabela)),
                                   key="conf_limite")
            exibir = tabela if filtro == "Todos" else tabela[tabela["Status"] == filtro]
            st.dataframe(exibir.head(limite), use_container_width=True, height=400)

            st.markdown("---")
            st.subheader("📤 Exportação de Inconformidades por Unidade")
            st.markdown(
                "Relatório consolidado de **meses faltantes por município/ano** — "
                "pronto para cobrança formal das unidades em débito."
            )
            pendencias = tabela_pendencias_por_unidade(df_proc)
            if pendencias is not None and not pendencias.empty:
                st.dataframe(pendencias, use_container_width=True, height=300)
                bloco_exportacao(
                    pendencias,
                    prefixo="pendencias_por_unidade",
                    titulo_pdf="Meses Faltantes por Unidade - Provimento 07/2021",
                    chave="exp_pendencias",
                )
            else:
                st.success("✅ Nenhuma pendência: todas as unidades em conformidade.")

            st.markdown("**Status geral (todas as unidades):**")
            bloco_exportacao(
                exibir,
                prefixo="conformidade_status_geral",
                titulo_pdf="Status de Conformidade por Município - Provimento 07/2021",
                chave="exp_status_geral",
            )

        st.markdown("---")
        st.subheader("🔍 Análise Individual Detalhada")
        municipios = sorted(df_proc["municipio"].dropna().unique())
        c1, c2 = st.columns(2)
        with c1:
            mun = st.selectbox("🏙️ Município para análise detalhada:",
                               municipios, key="mun_detalhe")
        with c2:
            st.info("📋 **Provimento 07/2021**: envio obrigatório até o dia 10 de cada mês")

        if mun:
            a = st.session_state.conformidade_cache.get(mun) or \
                analisar_conformidade_municipio(df_proc, mun)
            if a:
                st.session_state.conformidade_cache[mun] = a
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("✅ Meses Informados", a["total_meses_informados"])
                m2.metric("📅 Meses Esperados", a["total_meses_esperados"])
                m3.metric("🔴 Meses Faltantes", a["total_meses_faltantes"])
                conf_pct = a["conformidade_geral"]
                m4.metric("📊 Conformidade", f"{conf_pct:.1f}%",
                          "✅ Conforme" if conf_pct >= 100 else f"{conf_pct - 100:.1f}%")

                st.markdown("---")
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader("📊 Situação Geral")
                    st.bar_chart(pd.Series(
                        {"Em Conformidade": a["conformidade_geral"],
                         "Em Defasagem": a["defasagem_geral"]}
                    ))
                with c2:
                    st.subheader("📋 Detalhamento por Ano")
                    st.dataframe(pd.DataFrame([
                        {"Ano": ano,
                         "Informados": d["total_informado"],
                         "Esperados": d["total_esperado"],
                         "Faltantes": d["total_faltante"],
                         "Conformidade (%)": f"{d['pct_conformidade']:.1f}%"}
                        for ano, d in a["analise_por_ano"].items()
                    ]), use_container_width=True)

                st.markdown("---")
                st.subheader("📄 Relatório Executivo Automático")
                rel = gerar_relatorio_conformidade(a)
                st.markdown(rel)

                d1, d2, d3 = st.columns(3)
                agora = datetime.now().strftime("%Y%m%d_%H%M%S")
                with d1:
                    st.download_button(
                        "💾 Relatório (TXT)", data=rel,
                        file_name=f"conformidade_{mun}_{agora}.txt", mime="text/plain",
                        use_container_width=True,
                    )
                with d2:
                    pdf_rel = texto_para_pdf_bytes(
                        rel, f"Relatório de Conformidade - {mun} - Provimento 07/2021"
                    )
                    if pdf_rel:
                        st.download_button(
                            "🖨️ Relatório (PDF)", data=pdf_rel,
                            file_name=f"conformidade_{mun}_{agora}.pdf",
                            mime="application/pdf", use_container_width=True,
                        )
                with d3:
                    st.download_button(
                        "📊 Dados do Município (CSV)",
                        data=df_para_csv_bytes(df_proc[df_proc["municipio"] == mun]),
                        file_name=f"dados_{mun}_{agora}.csv", mime="text/csv",
                        use_container_width=True,
                    )

                if a["todos_meses_faltantes"]:
                    st.subheader("🔍 Detalhamento de Pendências por Ano")
                    for ano, d in a["analise_por_ano"].items():
                        with st.expander(
                            f"📅 Ano {ano} — {d['total_informado']}/{d['total_esperado']} meses informados"
                        ):
                            if d["meses_faltantes"]:
                                st.warning("**Meses em débito:** "
                                           + ", ".join(d["meses_faltantes_nomes"]))
                            else:
                                st.success("✅ Todos os meses informados")
                            if d["nascimentos"] > 0:
                                k1, k2, k3 = st.columns(3)
                                k1.metric("👶 Nascimentos", f"{d['nascimentos']:,.0f}")
                                k2.metric("📝 Registros", f"{d['registros']:,.0f}")
                                k3.metric("⚠️ Déficit",
                                          f"{d['nascimentos'] - d['registros']:,.0f}")
                else:
                    st.success("🎉 Município em conformidade total com o Provimento 07/2021")

    # ===== TAB 3: GRÁFICOS =====
    with tab3:
        st.header("📈 Centro de Gráficos Interativos")
        bloco_graficos(df_f)

    # ===== TAB 4: GEOGRÁFICA =====
    with tab4:
        st.header("🗺️ Análise Geográfica Completa")
        geo = bloco_geografico(df_f)
        if geo is not None and not geo.empty:
            st.markdown("---")
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("🏆 Top 10 Municípios")
                for _, linha in geo.nlargest(10, "Percentual Médio").iterrows():
                    e = ("🟢" if linha["Percentual Médio"] >= 90
                         else "🟡" if linha["Percentual Médio"] >= 70 else "🔴")
                    st.write(f"{e} **{linha['Município']}**: {linha['Percentual Médio']:.1f}%")
            with c2:
                st.subheader("⚠️ Municípios que Precisam Atenção")
                atencao = geo[geo["Status Performance"] == "🔴 Atenção"].nsmallest(
                    10, "Percentual Médio")
                if atencao.empty:
                    st.success("✅ Nenhum município necessita atenção urgente!")
                else:
                    for _, linha in atencao.iterrows():
                        st.write(f"🔴 **{linha['Município']}**: "
                                 f"{linha['Percentual Médio']:.1f}% "
                                 f"(Déficit: {linha['Déficit Total']:,.0f})")

    # ===== TAB 5: ANOMALIAS =====
    with tab5:
        bloco_anomalias(df_proc, df_f, stats)

    # ===== TAB 6: RELATÓRIO =====
    with tab6:
        st.header("📋 Relatório Executivo Completo")
        relatorio = gerar_relatorio_completo(df_f, stats)
        st.markdown(relatorio)

        st.markdown("---")
        st.subheader("💾 Downloads de Relatórios")
        agora = datetime.now().strftime("%Y%m%d_%H%M%S")
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            st.download_button(
                "📋 Executivo (TXT)", data=relatorio,
                file_name=f"relatorio_executivo_{agora}.txt", mime="text/plain",
                use_container_width=True,
            )
        with d2:
            pdf_exec = texto_para_pdf_bytes(
                relatorio, "Relatório Executivo - Provimento 07/2021"
            )
            if pdf_exec:
                st.download_button(
                    "🖨️ Executivo (PDF)", data=pdf_exec,
                    file_name=f"relatorio_executivo_{agora}.pdf",
                    mime="application/pdf", use_container_width=True,
                )
        with d3:
            tabela = tabela_conformidade_geral()
            if tabela is not None:
                xlsx_conf = df_para_xlsx_bytes(tabela, "Conformidade")
                if xlsx_conf:
                    st.download_button(
                        "⚖️ Conformidade (XLSX)", data=xlsx_conf,
                        file_name=f"conformidade_geral_{agora}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
        with d4:
            anomalos = df_proc[df_proc["anomalias"] != ""]
            xlsx_anom = df_para_xlsx_bytes(anomalos, "Anomalias")
            if xlsx_anom:
                st.download_button(
                    "🚩 Anomalias (XLSX)", data=xlsx_anom,
                    file_name=f"anomalias_{agora}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    # ---------- RODAPÉ ----------
    st.markdown("---")
    r1, r2, r3 = st.columns(3)
    with r1:
        st.markdown(f"💾 **Cache:** {len(st.session_state.dados_cache):,} registros")
        minutos = int((datetime.now() - st.session_state.timestamp_cache).total_seconds() / 60)
        st.markdown(f"⏱️ **Tempo ativo:** {minutos} minutos")
    with r2:
        st.markdown(f"🛡️ **Integridade:** 100% preservados "
                    f"({stats['linhas_com_anomalia']:,} sinalizados)")
        conf = st.session_state.conformidade_cache
        if conf:
            media = sum(a["conformidade_geral"] for a in conf.values()) / len(conf)
            e = "🟢" if media >= 90 else "🟡" if media >= 70 else "🔴"
            st.markdown(f"⚖️ **Conformidade:** {e} {media:.1f}%")
    with r3:
        st.markdown(f"🕒 **Atualizado:** {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        st.markdown(f"📋 **Registros no recorte:** {len(df_f):,}")

    st.markdown("""
    <div style='text-align: center; color: gray; font-size: 11px; padding: 15px;
                border-top: 1px solid #ddd; margin-top: 20px;'>
    <strong>Sistema Avançado v4.0 — Provimento 07/2021</strong><br>
    100% dos Dados Preservados • Parser Textual de Quantidades •
    Anomalias Sinalizadas • Conformidade Completa
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
