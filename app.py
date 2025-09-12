import streamlit as st
import pandas as pd
import requests
import io
from datetime import datetime
import base64
from typing import Optional
import time

# ==================== CONFIGURAÇÃO DA PÁGINA ====================
st.set_page_config(
    page_title="Provimento 07/2021 - Registros de Nascimentos",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== FUNÇÕES AUXILIARES ====================

@st.cache_data(ttl=300)  # Cache por 5 minutos
def carregar_dados_url(url: str) -> Optional[pd.DataFrame]:
    """Carrega dados de uma URL CSV"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        return df
    except Exception as e:
        st.error(f"Erro ao carregar dados da URL: {str(e)}")
        return None

@st.cache_data
def carregar_dados_arquivo(arquivo) -> Optional[pd.DataFrame]:
    """Carrega dados de um arquivo enviado"""
    try:
        df = pd.read_csv(arquivo)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar arquivo: {str(e)}")
        return None

def processar_dados(df: pd.DataFrame) -> pd.DataFrame:
    """Processa e limpa os dados"""
    # Renomear colunas para padronizar
    colunas_map = {
        'Carimbo de data/hora': 'timestamp',
        'Endereço de e-mail': 'email',
        'Município': 'municipio',
        'Nome da serventia': 'serventia',
        'Posto/unidade interligada': 'posto_unidade',
        'Mês': 'mes',
        'Ano': 'ano',
        'Nascimentos (quantidade)': 'nascimentos',
        'Registros (quantidade)': 'registros'
    }
    
    # Renomear colunas se existirem
    for old_col, new_col in colunas_map.items():
        if old_col in df.columns:
            df = df.rename(columns={old_col: new_col})
    
    # Processar timestamp se existir
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df['ano_timestamp'] = df['timestamp'].dt.year
        df['mes_timestamp'] = df['timestamp'].dt.month
    
    # Calcular percentual se colunas existirem
    if 'nascimentos' in df.columns and 'registros' in df.columns:
        df['percentual'] = ((df['registros'] / df['nascimentos']) * 100).round(2)
        df['percentual'] = df['percentual'].fillna(0)
        # Limitar percentual a 100% máximo
        df['percentual'] = df['percentual'].clip(upper=100)
    
    # Limpeza de dados
    df = df.dropna(subset=['municipio']) if 'municipio' in df.columns else df
    
    return df

def criar_graficos_streamlit(df: pd.DataFrame):
    """Cria gráficos usando funcionalidades nativas do Streamlit"""
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Gráfico 1: Nascimentos vs Registros por Município
        if all(col in df.columns for col in ['municipio', 'nascimentos', 'registros']):
            st.subheader("📊 Nascimentos vs Registros por Município")
            
            municipios_agrupados = df.groupby('municipio').agg({
                'nascimentos': 'sum',
                'registros': 'sum'
            }).reset_index()
            
            # Preparar dados para gráfico de barras
            chart_data = municipios_agrupados.set_index('municipio')[['nascimentos', 'registros']]
            st.bar_chart(chart_data)
    
    with col2:
        # Gráfico 2: Percentual de Registros
        if 'percentual' in df.columns and 'municipio' in df.columns:
            st.subheader("📈 Percentual Médio por Município")
            
            percentual_medio = df.groupby('municipio')['percentual'].mean().reset_index()
            percentual_chart = percentual_medio.set_index('municipio')['percentual']
            st.bar_chart(percentual_chart)
    
    # Gráfico 3: Evolução Temporal (linha inteira)
    if all(col in df.columns for col in ['ano', 'mes', 'registros']):
        st.subheader("📈 Evolução Temporal dos Registros")
        
        df_temporal = df.groupby(['ano', 'mes'])['registros'].sum().reset_index()
        df_temporal['periodo'] = df_temporal['ano'].astype(str) + '-' + df_temporal['mes'].astype(str).str.zfill(2)
        
        chart_temporal = df_temporal.set_index('periodo')['registros']
        st.line_chart(chart_temporal)

def criar_resumo_geografico(df: pd.DataFrame):
    """Cria resumo geográfico sem mapa complexo"""
    
    if 'municipio' in df.columns:
        st.subheader("🗺️ Distribuição Geográfica - Maranhão")
        
        # Agrupar dados por município
        dados_municipios = df.groupby('municipio').agg({
            'nascimentos': 'sum',
            'registros': 'sum',
            'percentual': 'mean'
        }).round(2).reset_index()
        
        # Adicionar classificação de performance
        dados_municipios['status'] = dados_municipios['percentual'].apply(
            lambda x: '🟢 Excelente' if x >= 90 
                     else '🟡 Bom' if x >= 70 
                     else '🔴 Atenção'
        )
        
        # Ordenar por percentual decrescente
        dados_municipios = dados_municipios.sort_values('percentual', ascending=False)
        
        # Exibir tabela com cores
        st.dataframe(
            dados_municipios,
            use_container_width=True,
            height=400
        )
        
        # Estatísticas por status
        col1, col2, col3 = st.columns(3)
        
        with col1:
            excelentes = len(dados_municipios[dados_municipios['percentual'] >= 90])
            st.metric("🟢 Municípios Excelentes (≥90%)", excelentes)
        
        with col2:
            bons = len(dados_municipios[(dados_municipios['percentual'] >= 70) & (dados_municipios['percentual'] < 90)])
            st.metric("🟡 Municípios Bons (70-89%)", bons)
        
        with col3:
            atencao = len(dados_municipios[dados_municipios['percentual'] < 70])
            st.metric("🔴 Municípios em Atenção (<70%)", atencao)
        
        return dados_municipios
    
    return pd.DataFrame()

def gerar_relatorio_completo(df: pd.DataFrame):
    """Gera relatório completo em texto"""
    
    st.subheader("📋 Relatório Executivo")
    
    total_nascimentos = df['nascimentos'].sum() if 'nascimentos' in df.columns else 0
    total_registros = df['registros'].sum() if 'registros' in df.columns else 0
    percentual_geral = (total_registros / total_nascimentos * 100) if total_nascimentos > 0 else 0
    
    relatorio = f"""
    **RELATÓRIO DO PROVIMENTO 07/2021 - REGISTROS DE NASCIMENTOS**
    
    **Período Analisado:** {df['timestamp'].min().strftime('%d/%m/%Y') if 'timestamp' in df.columns else 'N/A'} a {df['timestamp'].max().strftime('%d/%m/%Y') if 'timestamp' in df.columns else 'N/A'}
    
    **DADOS GERAIS:**
    - Total de Nascimentos: {total_nascimentos:,}
    - Total de Registros: {total_registros:,}
    - Percentual Geral de Cobertura: {percentual_geral:.2f}%
    - Déficit de Registros: {total_nascimentos - total_registros:,}
    
    **DISTRIBUIÇÃO:**
    - Municípios Atendidos: {df['municipio'].nunique() if 'municipio' in df.columns else 0}
    - Serventias Envolvidas: {df['serventia'].nunique() if 'serventia' in df.columns else 0}
    - Período de Dados: {df['ano'].nunique() if 'ano' in df.columns else 0} ano(s)
    
    **PERFORMANCE:**
    """
    
    if 'percentual' in df.columns and 'municipio' in df.columns:
        dados_municipios = df.groupby('municipio')['percentual'].mean()
        excelentes = len(dados_municipios[dados_municipios >= 90])
        bons = len(dados_municipios[(dados_municipios >= 70) & (dados_municipios < 90)])
        atencao = len(dados_municipios[dados_municipios < 70])
        
        relatorio += f"""
    - Municípios com Performance Excelente (≥90%): {excelentes}
    - Municípios com Performance Boa (70-89%): {bons}
    - Municípios que Necessitam Atenção (<70%): {atencao}
    
    **MUNICÍPIOS TOP 5 (Maior Percentual):**
        """
        
        top5 = dados_municipios.nlargest(5)
        for i, (municipio, perc) in enumerate(top5.items(), 1):
            relatorio += f"\n    {i}. {municipio}: {perc:.1f}%"
        
        relatorio += f"\n\n**MUNICÍPIOS QUE PRECISAM DE ATENÇÃO (Menor Percentual):**"
        bottom5 = dados_municipios.nsmallest(5)
        for i, (municipio, perc) in enumerate(bottom5.items(), 1):
            relatorio += f"\n    {i}. {municipio}: {perc:.1f}%"
    
    st.markdown(relatorio)
    
    return relatorio

# ==================== INTERFACE PRINCIPAL ====================

def main():
    st.title("📊 Sistema de Monitoramento - Provimento 07/2021")
    st.markdown("**Registros de Nascimentos em Unidades Interligadas**")
    
    # ==================== SIDEBAR ====================
    st.sidebar.header("⚙️ Configurações")
    
    # URL padrão da planilha
    url_padrao = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRtKiqlosLL5_CJgGom7BlWpFYExhLTQEjQT_Pdgnv3uEYMlWPpsSeaxfjqy0IxTluVlKSpcZ1IoXQY/pub?gid=152355120&single=true&output=csv"
    
    st.sidebar.subheader("📥 Fonte de Dados")
    fonte_dados = st.sidebar.radio(
        "Escolha a fonte:",
        ["URL Padrão", "URL Personalizada", "Upload de Arquivo"]
    )
    
    df = None
    
    if fonte_dados == "URL Padrão":
        st.sidebar.info("Usando planilha padrão do Provimento 07/2021")
        if st.sidebar.button("🔄 Carregar Dados"):
            with st.spinner("Carregando dados..."):
                df = carregar_dados_url(url_padrao)
    
    elif fonte_dados == "URL Personalizada":
        url_custom = st.sidebar.text_input("Cole a URL do CSV:", placeholder="https://...")
        if url_custom and st.sidebar.button("🔄 Carregar da URL"):
            with st.spinner("Carregando dados..."):
                df = carregar_dados_url(url_custom)
    
    else:  # Upload de arquivo
        arquivo = st.sidebar.file_uploader(
            "Envie seu arquivo CSV:",
            type=['csv'],
            help="Arraste e solte ou clique para selecionar"
        )
        if arquivo:
            with st.spinner("Processando arquivo..."):
                df = carregar_dados_arquivo(arquivo)
    
    # ==================== PROCESSAMENTO DOS DADOS ====================
    if df is not None:
        df = processar_dados(df)
        
        if df.empty:
            st.error("❌ Nenhum dado válido encontrado!")
            return
        
        st.success(f"✅ Dados carregados com sucesso! {len(df)} registros encontrados.")
        
        # ==================== FILTROS ====================
        st.sidebar.subheader("🔍 Filtros")
        
        # Criar cópia para filtros
        df_original = df.copy()
        
        # Filtro por ano
        if 'ano' in df.columns:
            anos_disponiveis = sorted(df['ano'].dropna().unique())
            ano_selecionado = st.sidebar.selectbox("Ano:", ['Todos'] + list(anos_disponiveis))
            if ano_selecionado != 'Todos':
                df = df[df['ano'] == ano_selecionado]
        
        # Filtro por mês
        if 'mes' in df.columns:
            meses_disponiveis = sorted(df['mes'].dropna().unique())
            mes_selecionado = st.sidebar.selectbox("Mês:", ['Todos'] + list(meses_disponiveis))
            if mes_selecionado != 'Todos':
                df = df[df['mes'] == mes_selecionado]
        
        # Filtro por município
        if 'municipio' in df.columns:
            municipios_disponiveis = sorted(df['municipio'].dropna().unique())
            municipio_selecionado = st.sidebar.selectbox("Município:", ['Todos'] + list(municipios_disponiveis))
            if municipio_selecionado != 'Todos':
                df = df[df['municipio'] == municipio_selecionado]
        
        # Filtro por serventia
        if 'serventia' in df.columns:
            servenias_disponiveis = sorted(df['serventia'].dropna().unique())
            serventia_selecionada = st.sidebar.selectbox("Serventia:", ['Todas'] + list(servenias_disponiveis))
            if serventia_selecionada != 'Todas':
                df = df[df['serventia'] == serventia_selecionada]
        
        # Filtro por percentual
        if 'percentual' in df.columns:
            min_perc, max_perc = st.sidebar.slider(
                "Faixa de Percentual:",
                float(df['percentual'].min()),
                float(df['percentual'].max()),
                (float(df['percentual'].min()), float(df['percentual'].max()))
            )
            df = df[(df['percentual'] >= min_perc) & (df['percentual'] <= max_perc)]
        
        # Mostrar info sobre filtros aplicados
        if len(df) != len(df_original):
            st.sidebar.info(f"Filtros aplicados: {len(df)} de {len(df_original)} registros")
        
        # ==================== ABAS PRINCIPAIS ====================
        tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "🗺️ Análise Geográfica", "📋 Relatório"])
        
        with tab1:
            st.header("📈 Dashboard Principal")
            
            # Métricas principais
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                total_nascimentos = df['nascimentos'].sum() if 'nascimentos' in df.columns else 0
                st.metric("Total Nascimentos", f"{total_nascimentos:,}")
            
            with col2:
                total_registros = df['registros'].sum() if 'registros' in df.columns else 0
                st.metric("Total Registros", f"{total_registros:,}")
            
            with col3:
                percentual_medio = df['percentual'].mean() if 'percentual' in df.columns else 0
                st.metric("Percentual Médio", f"{percentual_medio:.1f}%")
            
            with col4:
                municipios_unicos = df['municipio'].nunique() if 'municipio' in df.columns else 0
                st.metric("Municípios", municipios_unicos)
            
            st.markdown("---")
            
            # Gráficos nativos do Streamlit
            criar_graficos_streamlit(df)
            
            st.markdown("---")
            
            # Tabela de dados
            st.subheader("📋 Dados Detalhados")
            
            # Configurar colunas para exibição
            colunas_exibir = []
            if 'municipio' in df.columns:
                colunas_exibir.append('municipio')
            if 'serventia' in df.columns:
                colunas_exibir.append('serventia')
            if 'posto_unidade' in df.columns:
                colunas_exibir.append('posto_unidade')
            if 'ano' in df.columns:
                colunas_exibir.append('ano')
            if 'mes' in df.columns:
                colunas_exibir.append('mes')
            if 'nascimentos' in df.columns:
                colunas_exibir.append('nascimentos')
            if 'registros' in df.columns:
                colunas_exibir.append('registros')
            if 'percentual' in df.columns:
                colunas_exibir.append('percentual')
            
            if colunas_exibir:
                st.dataframe(
                    df[colunas_exibir],
                    use_container_width=True,
                    height=400
                )
            else:
                st.dataframe(df, use_container_width=True, height=400)
        
        with tab2:
            st.header("🗺️ Análise Geográfica")
            st.markdown("Distribuição e performance por município no Maranhão")
            
            dados_geograficos = criar_resumo_geografico(df)
            
            if not dados_geograficos.empty:
                # Gráfico de pizza para distribuição de status
                st.subheader("📊 Distribuição de Performance")
                
                status_counts = dados_geograficos['status'].value_counts()
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**Contagem por Status:**")
                    for status, count in status_counts.items():
                        st.write(f"{status}: {count} municípios")
                
                with col2:
                    # Gráfico de barras para status
                    st.bar_chart(status_counts)
        
        with tab3:
            st.header("📋 Relatório Executivo")
            
            relatorio_texto = gerar_relatorio_completo(df)
            
            # Download do relatório
            st.download_button(
                label="💾 Download Relatório (TXT)",
                data=relatorio_texto,
                file_name=f"relatorio_provimento_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain"
            )
            
            # Download dos dados filtrados
            csv_dados = df.to_csv(index=False)
            st.download_button(
                label="💾 Download Dados CSV",
                data=csv_dados,
                file_name=f"dados_filtrados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        
        # Rodapé com informações
        st.markdown("---")
        st.markdown(f"""
        <div style='text-align: center; color: gray; font-size: 12px;'>
        Sistema atualizado em {datetime.now().strftime('%d/%m/%Y às %H:%M')} | 
        Dados do Provimento 07/2021 | 
        {len(df)} registros processados
        </div>
        """, unsafe_allow_html=True)
    
    else:
        st.info("👆 Selecione uma fonte de dados na barra lateral para começar.")
        
        # Informações sobre o sistema
        st.markdown("""
        ## 📋 Sobre o Sistema
        
        Este sistema foi desenvolvido para monitorar e visualizar os dados do **Provimento 07/2021** 
        referente aos registros de nascimentos em unidades interligadas.
        
        ### 🔧 Funcionalidades:
        - ✅ Carregamento automático da planilha oficial
        - ✅ Upload de arquivos CSV personalizados
        - ✅ URLs personalizadas para fontes externas
        - ✅ Filtros dinâmicos por ano, mês, município, serventia e percentual
        - ✅ Gráficos nativos do Streamlit (barras, linhas, área)
        - ✅ Análise geográfica com classificação de performance
        - ✅ Relatório executivo automático
        - ✅ Download de dados e relatórios
        - ✅ Interface responsiva e rápida
        - ✅ Cache inteligente para melhor performance
        
        ### 📊 Campos Monitorados:
        - Carimbo de data e hora
        - Município e serventia
        - Posto/unidade interligada
        - Nascimentos e registros
        - Percentuais de cobertura calculados automaticamente
        - Motivos de não atingimento de 100%
        
        ### 🎯 Objetivo:
        Facilitar o monitoramento e a tomada de decisões baseada em dados para 
        melhorar a cobertura de registros de nascimentos no estado do Maranhão.
        """)

# ==================== EXECUTAR APLICAÇÃO ====================
if __name__ == "__main__":
    main()
