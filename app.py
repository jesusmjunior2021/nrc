"""
NRC PAINEL GERENCIAL
Painel gerencial das Unidades Interligadas - NRC/COGEX/TJMA
Dados carregados automaticamente da planilha Google Sheets publicada em CSV
(ou, opcionalmente, de um arquivo CSV/XLSX enviado manualmente).

Como rodar localmente:
    streamlit run app.py

Deploy:
    1. Suba este repositório no GitHub.
    2. Em https://share.streamlit.io, aponte para o app.py.
    3. Configure em "Secrets" (Settings > Secrets) o usuário/senha reais,
       usando o modelo do arquivo .streamlit/secrets.toml.example.
"""

import pandas as pd
import streamlit as st

# ----------------------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="NRC PAINEL GERENCIAL",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# URL da planilha Google Sheets publicada em formato CSV (fonte padrão).
# Para trocar a fonte de dados padrão, publique a planilha em
# Arquivo > Compartilhar > Publicar na Web > CSV, e cole o link abaixo.
DATA_URL_PADRAO = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vT73jQ3Ae7I0gSx-UqOvA3C_JznfDQYrb23nLx4jpQXH03i1-ocEzHxnRNZnYTTHQ/pub?output=csv"
)

COLUNAS_ESPERADAS = [
    "MUNICÍPIOS", "HOSPITAL", "DATA DA INSTALAÇÃO", "ESFERA", "SERVENTIA",
    "JUSTIÇA ABERTA", "HABILITAÇÃO CRC", "SITUAÇÃO ATUAL", "SITUAÇÃO GERAL",
    "ÍNDICES IBGE", "OBSERVAÇÕES",
]

# ----------------------------------------------------------------------------
# AUTENTICAÇÃO
# ----------------------------------------------------------------------------
def get_credentials():
    """
    Busca usuário/senha em st.secrets (recomendado em produção).
    Se não houver secrets configurados, usa um valor padrão apenas
    para permitir testes locais - TROQUE antes de publicar!
    """
    try:
        user = st.secrets["credentials"]["username"]
        pwd = st.secrets["credentials"]["password"]
    except Exception:
        user, pwd = "COGEX", "cogex@nrc"  # valor padrão de fallback (apenas teste local)
    return user, pwd


def login_screen():
    st.markdown(
        """
        <div style="text-align:center; padding-top: 40px;">
            <h1>🏛️ NRC PAINEL GERENCIAL</h1>
            <p style="color:gray;">COGEX / TJMA - Unidades Interligadas</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login_form"):
            st.subheader("Acesso restrito")
            user_input = st.text_input("Usuário")
            pwd_input = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", use_container_width=True)

        if submitted:
            valid_user, valid_pwd = get_credentials()
            if user_input == valid_user and pwd_input == valid_pwd:
                st.session_state["autenticado"] = True
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")


def logout_button():
    with st.sidebar:
        st.markdown("---")
        if st.button("🚪 Sair", use_container_width=True):
            st.session_state["autenticado"] = False
            st.rerun()


# ----------------------------------------------------------------------------
# CLASSIFICAÇÃO DE STATUS (robusta contra valores vazios/NaN/não-string)
# ----------------------------------------------------------------------------
def classificar_status(valor) -> str:
    if valor is None:
        return "Sem informação"
    v = str(valor).strip().upper()
    if v == "" or v == "NAN":
        return "Sem informação"
    if "IMPLANTA" in v or "PREVIS" in v or "EM PROCESSO" in v or "PROCESSO CNJ" in v:
        return "Em fase de implantação"
    if "REATIVA" in v:
        return "Em fase de reativação"
    if "NÃO" in v and "FUNCION" in v:
        return "Inativa"
    if "PAROU" in v or "PARALISAD" in v or "DESATIVAD" in v:
        return "Inativa"
    if "FUNCIONANDO" in v or v == "OK":
        return "Ativa"
    return "Outra situação"


# ----------------------------------------------------------------------------
# CARGA E TRATAMENTO DOS DADOS
# ----------------------------------------------------------------------------
def tratar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # remove eventual coluna de índice sem nome, vinda da planilha
    unnamed = [c for c in df.columns if str(c).startswith("Unnamed")]
    df = df.drop(columns=unnamed, errors="ignore")

    # limpa espaços dos nomes de coluna
    df.columns = [str(c).strip() for c in df.columns]

    # limpa espaços em branco de TODAS as colunas de texto, tratando NaN
    # de forma segura (independe do dtype interno usado pelo pandas)
    for c in df.columns:
        df[c] = df[c].apply(lambda x: "" if pd.isna(x) else str(x).strip())

    # coluna normalizada de status, usada nos filtros e KPIs
    if "SITUAÇÃO ATUAL" in df.columns:
        df["STATUS_FUNCIONAMENTO"] = df["SITUAÇÃO ATUAL"].apply(classificar_status)
    else:
        df["STATUS_FUNCIONAMENTO"] = "Sem informação"

    return df


@st.cache_data(ttl=600, show_spinner="Carregando dados da planilha...")
def load_data_url(url: str) -> pd.DataFrame:
    df = pd.read_csv(url)
    return tratar_dataframe(df)


def load_data_upload(arquivo) -> pd.DataFrame:
    nome = arquivo.name.lower()
    if nome.endswith(".csv"):
        df = pd.read_csv(arquivo)
        return tratar_dataframe(df)
    else:
        # arquivo Excel: se tiver mais de uma aba, deixa o usuário escolher
        planilhas = pd.read_excel(arquivo, sheet_name=None)
        if len(planilhas) == 1:
            df = list(planilhas.values())[0]
        else:
            aba = st.selectbox("Escolha a aba da planilha", list(planilhas.keys()))
            df = planilhas[aba]
        return tratar_dataframe(df)


# ----------------------------------------------------------------------------
# PAINEL PRINCIPAL
# ----------------------------------------------------------------------------
def painel():
    with st.sidebar:
        st.markdown("## 🏛️ NRC PAINEL GERENCIAL")
        st.caption("COGEX / TJMA")
        st.markdown("### Fonte de dados")

        fonte = st.radio(
            "Selecione a origem dos dados",
            ["Planilha publicada (padrão)", "Enviar arquivo (CSV/XLSX)"],
            index=0,
        )

        df = None
        if fonte == "Planilha publicada (padrão)":
            try:
                df = load_data_url(DATA_URL_PADRAO)
            except Exception as e:
                st.error(f"Não foi possível carregar a planilha publicada: {e}")
        else:
            arquivo = st.file_uploader("Envie o arquivo CSV ou XLSX", type=["csv", "xlsx", "xls"])
            if arquivo is not None:
                try:
                    df = load_data_upload(arquivo)
                except Exception as e:
                    st.error(f"Não foi possível ler o arquivo: {e}")

        if df is None:
            st.info("Aguardando dados...")
            st.stop()

        st.markdown("### Filtros")

        def multiselect_filtro(label, coluna):
            if coluna not in df.columns:
                return []
            opcoes = sorted([o for o in df[coluna].unique() if o])
            return st.multiselect(label, opcoes, default=[])

        f_municipio = multiselect_filtro("Município", "MUNICÍPIOS")
        f_esfera = multiselect_filtro("Esfera", "ESFERA")
        f_status = multiselect_filtro("Status (Ativa/Inativa/...)", "STATUS_FUNCIONAMENTO")
        f_situacao_geral = multiselect_filtro("Situação geral", "SITUAÇÃO GERAL")
        f_justica_aberta = multiselect_filtro("Justiça Aberta", "JUSTIÇA ABERTA")
        f_crc = multiselect_filtro("Habilitação CRC", "HABILITAÇÃO CRC")
        f_serventia = multiselect_filtro("Serventia", "SERVENTIA")

        busca = st.text_input("🔎 Buscar hospital/unidade/observação")

        if fonte == "Planilha publicada (padrão)" and st.button("🔄 Atualizar dados", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # aplica filtros
    df_filtrado = df.copy()
    if f_municipio:
        df_filtrado = df_filtrado[df_filtrado["MUNICÍPIOS"].isin(f_municipio)]
    if f_esfera:
        df_filtrado = df_filtrado[df_filtrado["ESFERA"].isin(f_esfera)]
    if f_status:
        df_filtrado = df_filtrado[df_filtrado["STATUS_FUNCIONAMENTO"].isin(f_status)]
    if f_situacao_geral:
        df_filtrado = df_filtrado[df_filtrado["SITUAÇÃO GERAL"].isin(f_situacao_geral)]
    if f_justica_aberta:
        df_filtrado = df_filtrado[df_filtrado["JUSTIÇA ABERTA"].isin(f_justica_aberta)]
    if f_crc:
        df_filtrado = df_filtrado[df_filtrado["HABILITAÇÃO CRC"].isin(f_crc)]
    if f_serventia:
        df_filtrado = df_filtrado[df_filtrado["SERVENTIA"].isin(f_serventia)]
    if busca:
        mask = df_filtrado.apply(
            lambda row: busca.upper() in " ".join(row.astype(str)).upper(), axis=1
        )
        df_filtrado = df_filtrado[mask]

    # cabeçalho
    st.markdown("## 🏛️ NRC PAINEL GERENCIAL")
    st.caption("Unidades Interligadas - Corregedoria Geral de Justiça Extrajudicial (COGEX/MA)")

    # KPIs
    total = len(df_filtrado)
    ativas = (df_filtrado["STATUS_FUNCIONAMENTO"] == "Ativa").sum()
    inativas = (df_filtrado["STATUS_FUNCIONAMENTO"] == "Inativa").sum()
    reativacao = (df_filtrado["STATUS_FUNCIONAMENTO"] == "Em fase de reativação").sum()
    implantacao = (df_filtrado["STATUS_FUNCIONAMENTO"] == "Em fase de implantação").sum()
    outros = total - ativas - inativas - reativacao - implantacao

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total de unidades", total)
    c2.metric("✅ Ativas", int(ativas))
    c3.metric("⛔ Inativas", int(inativas))
    c4.metric("♻️ Em reativação", int(reativacao))
    c5.metric("🚧 Em implantação", int(implantacao))

    if outros:
        st.caption(f"ℹ️ {int(outros)} unidade(s) em outras situações / sem informação classificável.")

    st.markdown("---")

    # gráficos com biblioteca nativa do streamlit (sem libs externas)
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("#### Unidades por status")
        st.bar_chart(df_filtrado["STATUS_FUNCIONAMENTO"].value_counts())
    with g2:
        st.markdown("#### Unidades por esfera")
        if "ESFERA" in df_filtrado.columns:
            esfera_counts = df_filtrado[df_filtrado["ESFERA"] != ""]["ESFERA"].value_counts()
            st.bar_chart(esfera_counts)

    g3, g4 = st.columns(2)
    with g3:
        st.markdown("#### Justiça Aberta")
        if "JUSTIÇA ABERTA" in df_filtrado.columns:
            st.bar_chart(df_filtrado["JUSTIÇA ABERTA"].value_counts())
    with g4:
        st.markdown("#### Habilitação CRC")
        if "HABILITAÇÃO CRC" in df_filtrado.columns:
            st.bar_chart(df_filtrado["HABILITAÇÃO CRC"].value_counts())

    st.markdown("#### Top 15 municípios com mais unidades")
    if "MUNICÍPIOS" in df_filtrado.columns:
        top_municipios = df_filtrado["MUNICÍPIOS"].value_counts().head(15)
        st.bar_chart(top_municipios)

    st.markdown("---")

    # tabela detalhada
    st.markdown(f"#### Detalhamento das unidades ({total} registros)")
    colunas_exibir = [c for c in COLUNAS_ESPERADAS if c in df_filtrado.columns]
    colunas_exibir += ["STATUS_FUNCIONAMENTO"] if "STATUS_FUNCIONAMENTO" not in colunas_exibir else []
    st.dataframe(df_filtrado[colunas_exibir], use_container_width=True, hide_index=True)

    csv_download = df_filtrado[colunas_exibir].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Baixar dados filtrados (CSV)",
        data=csv_download,
        file_name="nrc_unidades_interligadas_filtrado.csv",
        mime="text/csv",
    )


# ----------------------------------------------------------------------------
# CONTROLE DE FLUXO (LOGIN -> PAINEL)
# ----------------------------------------------------------------------------
def main():
    if "autenticado" not in st.session_state:
        st.session_state["autenticado"] = False

    if not st.session_state["autenticado"]:
        login_screen()
    else:
        logout_button()
        painel()


if __name__ == "__main__":
    main()
