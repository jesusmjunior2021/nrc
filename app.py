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
    """Processa e limpa os dados usando os cabeçalhos reais"""
    
    # Mapeamento dos nomes reais das colunas (sem alteração)
    colunas_reais = {
        'Carimbo de data/hora': 'timestamp',
        'Endereço de e-mail': 'email',
        'MUNICÍPIO': 'municipio',
        'Nome da Serventia': 'serventia',
        'Posto/Unidade Interligada': 'posto_unidade',
        'Mês': 'mes',
        'Ano': 'ano',
        'NASCIMENTOS (QTDE)': 'nascimentos',
        'REGISTROS (QTDE)': 'registros',
        'Quais os principais motivos de não terem sido feitos 100% registros?': 'motivos',
        '% Ok.': 'percentual_original'
    }
    
    # Criar cópia para não modificar original
    df_processado = df.copy()
    
    # Renomear apenas se as colunas existirem
    for col_original, col_nova in colunas_reais.items():
        if col_original in df_processado.columns:
            df_processado[col_nova] = df_processado[col_original]
    
    # Processar timestamp se existir
    if 'timestamp' in df_processado.columns:
        df_processado['timestamp'] = pd.to_datetime(df_processado['timestamp'], errors='coerce')
        df_processado['ano_timestamp'] = df_processado['timestamp'].dt.year
        df_processado['mes_timestamp'] = df_processado['timestamp'].dt.month
        df_processado['data_formatada'] = df_processado['timestamp'].dt.strftime('%d/%m/%Y %H:%M')
    
    # Converter colunas numéricas
    colunas_numericas = ['mes', 'ano', 'nascimentos', 'registros']
    for col in colunas_numericas:
        if col in df_processado.columns:
            df_processado[col] = pd.to_numeric(df_processado[col], errors='coerce')
    
    # Calcular percentual se não existir ou estiver vazio
    if 'nascimentos' in df_processado.columns and 'registros' in df_processado.columns:
        # Calcular percentual próprio
        df_processado['percentual_calculado'] = (
            (df_processado['registros'] / df_processado['nascimentos']) * 100
        ).round(2)
        df_processado['percentual_calculado'] = df_processado['percentual_calculado'].fillna(0)
        df_processado['percentual_calculado'] = df_processado['percentual_calculado'].clip(upper=100)
        
        # Usar percentual original se existir, senão usar calculado
        if 'percentual_original' in df_processado.columns:
            df_processado['percentual'] = df_processado['percentual_original'].fillna(df_processado['percentual_calculado'])
        else:
            df_processado['percentual'] = df_processado['percentual_calculado']
    
    # Calcular déficit
    if 'nascimentos' in df_processado.columns and 'registros' in df_processado.columns:
        df_processado['deficit'] = df_processado['nascimentos'] - df_processado['registros']
        df_processado['deficit'] = df_processado['deficit'].fillna(0)
    
    # Limpeza básica - manter todos os dados, apenas converter vazios
    for col in df_processado.columns:
        if df_processado[col].dtype == 'object':
            df_processado[col] = df_processado[col].fillna('Não informado')
    
    return df_processado

def criar_graficos_streamlit(df: pd.DataFrame):
    """Cria gráficos usando funcionalidades nativas do Streamlit"""
    
    st.subheader("📊 Análises Gráficas")
    
    # Seletor de tipo de análise
    tipo_analise = st.selectbox(
        "Escolha o tipo de análise:",
        ["Nascimentos vs Registros", "Evolução Temporal", "Análise por Percentual", "Déficit por Região"]
    )
    
    # Seletor de agrupamento
    col1, col2 = st.columns(2)
    
    with col1:
        opcoes_agrupamento = []
        if 'municipio' in df.columns:
            opcoes_agrupamento.append('Município')
        if 'serventia' in df.columns:
            opcoes_agrupamento.append('Serventia')
        if 'posto_unidade' in df.columns:
            opcoes_agrupamento.append('Posto/Unidade')
        if 'ano' in df.columns:
            opcoes_agrupamento.append('Ano')
        if 'mes' in df.columns:
            opcoes_agrupamento.append('Mês')
        
        agrupamento = st.selectbox("Agrupar por:", opcoes_agrupamento)
    
    with col2:
        # Limite de registros para melhor visualização
        limite_registros = st.slider("Limite de registros no gráfico:", 5, 50, 20)
    
    # Mapear seleção para coluna
    mapa_colunas = {
        'Município': 'municipio',
        'Serventia': 'serventia', 
        'Posto/Unidade': 'posto_unidade',
        'Ano': 'ano',
        'Mês': 'mes'
    }
    
    coluna_agrupamento = mapa_colunas.get(agrupamento, 'municipio')
    
    if tipo_analise == "Nascimentos vs Registros":
        if all(col in df.columns for col in [coluna_agrupamento, 'nascimentos', 'registros']):
            dados_agrupados = df.groupby(coluna_agrupamento).agg({
                'nascimentos': 'sum',
                'registros': 'sum'
            }).reset_index()
            
            # Ordenar e limitar
            dados_agrupados = dados_agrupados.nlargest(limite_registros, 'nascimentos')
            
            chart_data = dados_agrupados.set_index(coluna_agrupamento)[['nascimentos', 'registros']]
            st.bar_chart(chart_data)
            
            # Tabela de dados do gráfico
            st.subheader("📋 Dados do Gráfico")
            st.dataframe(dados_agrupados, use_container_width=True)
    
    elif tipo_analise == "Evolução Temporal":
        if all(col in df.columns for col in ['ano', 'mes', 'registros', 'nascimentos']):
            df_temporal = df.groupby(['ano', 'mes']).agg({
                'registros': 'sum',
                'nascimentos': 'sum'
            }).reset_index()
            
            df_temporal['periodo'] = df_temporal['ano'].astype(str) + '-' + df_temporal['mes'].astype(str).str.zfill(2)
            df_temporal = df_temporal.sort_values(['ano', 'mes'])
            
            chart_temporal = df_temporal.set_index('periodo')[['nascimentos', 'registros']]
            st.line_chart(chart_temporal)
            
            st.subheader("📋 Dados Temporais")
            st.dataframe(df_temporal, use_container_width=True)
    
    elif tipo_analise == "Análise por Percentual":
        if all(col in df.columns for col in [coluna_agrupamento, 'percentual']):
            dados_percentual = df.groupby(coluna_agrupamento)['percentual'].mean().reset_index()
            dados_percentual = dados_percentual.sort_values('percentual', ascending=False).head(limite_registros)
            
            chart_percentual = dados_percentual.set_index(coluna_agrupamento)['percentual']
            st.bar_chart(chart_percentual)
            
            st.subheader("📋 Dados de Percentual")
            st.dataframe(dados_percentual, use_container_width=True)
    
    elif tipo_analise == "Déficit por Região":
        if all(col in df.columns for col in [coluna_agrupamento, 'deficit']):
            dados_deficit = df.groupby(coluna_agrupamento)['deficit'].sum().reset_index()
            dados_deficit = dados_deficit.sort_values('deficit', ascending=False).head(limite_registros)
            
            chart_deficit = dados_deficit.set_index(coluna_agrupamento)['deficit']
            st.bar_chart(chart_deficit)
            
            st.subheader("📋 Dados de Déficit")
            st.dataframe(dados_deficit, use_container_width=True)

def criar_resumo_geografico(df: pd.DataFrame):
    """Cria resumo geográfico completo"""
    
    if 'municipio' in df.columns:
        st.subheader("🗺️ Análise Completa por Município")
        
        # Agrupar dados por município com TODOS os campos
        dados_municipios = df.groupby('municipio').agg({
            'nascimentos': 'sum',
            'registros': 'sum',
            'percentual': 'mean',
            'deficit': 'sum',
            'serventia': 'nunique',
            'posto_unidade': 'nunique'
        }).round(2).reset_index()
        
        # Renomear colunas para melhor visualização
        dados_municipios.columns = [
            'Município', 'Total Nascimentos', 'Total Registros', 
            'Percentual Médio', 'Déficit Total', 'Nº Serventias', 'Nº Postos/Unidades'
        ]
        
        # Adicionar classificação de performance
        dados_municipios['Status'] = dados_municipios['Percentual Médio'].apply(
            lambda x: '🟢 Excelente' if x >= 90 
                     else '🟡 Bom' if x >= 70 
                     else '🔴 Atenção'
        )
        
        # Ordenar por percentual decrescente
        dados_municipios = dados_municipios.sort_values('Percentual Médio', ascending=False)
        
        # Filtro para a tabela geográfica
        col1, col2 = st.columns(2)
        with col1:
            status_filtro = st.selectbox(
                "Filtrar por Status:",
                ['Todos', '🟢 Excelente', '🟡 Bom', '🔴 Atenção']
            )
        
        with col2:
            limite_municipios = st.slider("Mostrar quantos municípios:", 10, len(dados_municipios), min(30, len(dados_municipios)))
        
        # Aplicar filtros
        if status_filtro != 'Todos':
            dados_filtrados = dados_municipios[dados_municipios['Status'] == status_filtro]
        else:
            dados_filtrados = dados_municipios
        
        dados_filtrados = dados_filtrados.head(limite_municipios)
        
        # Exibir tabela com formatação
        st.dataframe(
            dados_filtrados,
            use_container_width=True,
            height=400
        )
        
        # Estatísticas resumidas
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            excelentes = len(dados_municipios[dados_municipios['Percentual Médio'] >= 90])
            st.metric("🟢 Excelentes", f"{excelentes}")
        
        with col2:
            bons = len(dados_municipios[(dados_municipios['Percentual Médio'] >= 70) & (dados_municipios['Percentual Médio'] < 90)])
            st.metric("🟡 Bons", f"{bons}")
        
        with col3:
            atencao = len(dados_municipios[dados_municipios['Percentual Médio'] < 70])
            st.metric("🔴 Atenção", f"{atencao}")
        
        with col4:
            deficit_total = dados_municipios['Déficit Total'].sum()
            st.metric("Total Déficit", f"{deficit_total:,.0f}")
        
        return dados_municipios
    
    return pd.DataFrame()

def gerar_relatorio_completo(df: pd.DataFrame):
    """Gera relatório executivo completo"""
    
    st.subheader("📋 Relatório Executivo Completo")
    
    # Calcular estatísticas principais
    total_nascimentos = df['nascimentos'].sum() if 'nascimentos' in df.columns else 0
    total_registros = df['registros'].sum() if 'registros' in df.columns else 0
    percentual_geral = (total_registros / total_nascimentos * 100) if total_nascimentos > 0 else 0
    deficit_total = total_nascimentos - total_registros
    
    # Informações temporais
    data_inicio = df['timestamp'].min() if 'timestamp' in df.columns else 'N/A'
    data_fim = df['timestamp'].max() if 'timestamp' in df.columns else 'N/A'
    
    relatorio = f"""
**RELATÓRIO EXECUTIVO - PROVIMENTO 07/2021**
**Sistema de Monitoramento de Registros de Nascimentos**

═══════════════════════════════════════════════════════════════

**PERÍODO DE ANÁLISE:**
• Data de Início: {data_inicio.strftime('%d/%m/%Y') if data_inicio != 'N/A' else 'N/A'}
• Data de Fim: {data_fim.strftime('%d/%m/%Y') if data_fim != 'N/A' else 'N/A'}
• Total de Registros na Base: {len(df):,}

**INDICADORES PRINCIPAIS:**
• Total de Nascimentos: {total_nascimentos:,}
• Total de Registros Realizados: {total_registros:,}
• Percentual Geral de Cobertura: {percentual_geral:.2f}%
• Déficit Total de Registros: {deficit_total:,}

**DISTRIBUIÇÃO GEOGRÁFICA:**
• Municípios Atendidos: {df['municipio'].nunique() if 'municipio' in df.columns else 0}
• Serventias Participantes: {df['serventia'].nunique() if 'serventia' in df.columns else 0}
• Postos/Unidades Interligadas: {df['posto_unidade'].nunique() if 'posto_unidade' in df.columns else 0}

**DISTRIBUIÇÃO TEMPORAL:**
• Anos Cobertos: {df['ano'].nunique() if 'ano' in df.columns else 0}
• Meses com Dados: {df['mes'].nunique() if 'mes' in df.columns else 0}
    """
    
    # Análise de performance por município
    if 'percentual' in df.columns and 'municipio' in df.columns:
        dados_municipios = df.groupby('municipio')['percentual'].mean()
        excelentes = len(dados_municipios[dados_municipios >= 90])
        bons = len(dados_municipios[(dados_municipios >= 70) & (dados_municipios < 90)])
        atencao = len(dados_municipios[dados_municipios < 70])
        
        relatorio += f"""
**ANÁLISE DE PERFORMANCE:**
• Municípios com Performance Excelente (≥90%): {excelentes} ({excelentes/len(dados_municipios)*100:.1f}%)
• Municípios com Performance Boa (70-89%): {bons} ({bons/len(dados_municipios)*100:.1f}%)
• Municípios que Necessitam Atenção (<70%): {atencao} ({atencao/len(dados_municipios)*100:.1f}%)

**TOP 10 MUNICÍPIOS (Maior Percentual):**"""
        
        top10 = dados_municipios.nlargest(10)
        for i, (municipio, perc) in enumerate(top10.items(), 1):
            relatorio += f"\n{i:2d}. {municipio}: {perc:.1f}%"
        
        relatorio += f"\n\n**MUNICÍPIOS QUE PRECISAM DE ATENÇÃO (Menor Percentual):**"
        bottom10 = dados_municipios.nsmallest(10)
        for i, (municipio, perc) in enumerate(bottom10.items(), 1):
            relatorio += f"\n{i:2d}. {municipio}: {perc:.1f}%"
    
    # Análise de motivos
    if 'motivos' in df.columns:
        motivos_freq = df[df['motivos'] != 'Não informado']['motivos'].value_counts().head(10)
        if not motivos_freq.empty:
            relatorio += f"\n\n**PRINCIPAIS MOTIVOS DE NÃO ATINGIMENTO DE 100%:**"
            for i, (motivo, freq) in enumerate(motivos_freq.items(), 1):
                relatorio += f"\n{i:2d}. {motivo}: {freq} ocorrências"
    
    # Análise temporal
    if all(col in df.columns for col in ['ano', 'mes', 'nascimentos', 'registros']):
        relatorio += f"\n\n**EVOLUÇÃO TEMPORAL:**"
        evolucao = df.groupby(['ano', 'mes']).agg({
            'nascimentos': 'sum',
            'registros': 'sum'
        })
        evolucao['percentual'] = (evolucao['registros'] / evolucao['nascimentos'] * 100).round(2)
        
        melhor_periodo = evolucao['percentual'].idxmax()
        pior_periodo = evolucao['percentual'].idxmin()
        
        relatorio += f"\n• Melhor Período: {melhor_periodo[0]}/{melhor_periodo[1]:02d} ({evolucao.loc[melhor_periodo, 'percentual']:.1f}%)"
        relatorio += f"\n• Período com Menor Performance: {pior_periodo[0]}/{pior_periodo[1]:02d} ({evolucao.loc[pior_periodo, 'percentual']:.1f}%)"
    
    relatorio += f"""

═══════════════════════════════════════════════════════════════
**RECOMENDAÇÕES:**

1. **FOCO PRIORITÁRIO:** Concentrar esforços nos {len(dados_municipios[dados_municipios < 70]) if 'percentual' in df.columns and 'municipio' in df.columns else 'N/A'} municípios com performance abaixo de 70%

2. **BOAS PRÁTICAS:** Replicar as estratégias dos municípios com melhor performance

3. **MONITORAMENTO:** Acompanhar mensalmente a evolução dos indicadores

4. **CAPACITAÇÃO:** Investir em treinamento das serventias com maior déficit

5. **TECNOLOGIA:** Implementar sistemas automatizados para reduzir gaps de registro

═══════════════════════════════════════════════════════════════
Relatório gerado automaticamente em {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}
Sistema de Monitoramento - Provimento 07/2021
    """
    
    st.markdown(relatorio)
    return relatorio

# ==================== INTERFACE PRINCIPAL ====================

def main():
    st.title("📊 Sistema de Monitoramento - Provimento 07/2021")
    st.markdown("**Registros de Nascimentos em Unidades Interligadas do Maranhão**")
    
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
        # Mostrar colunas originais encontradas
        st.sidebar.subheader("📋 Colunas Encontradas")
        with st.sidebar.expander("Ver colunas da planilha"):
            for i, col in enumerate(df.columns, 1):
                st.sidebar.write(f"{i}. {col}")
        
        df_processado = processar_dados(df)
        
        if df_processado.empty:
            st.error("❌ Nenhum dado válido encontrado!")
            return
        
        st.success(f"✅ Dados carregados com sucesso! **{len(df_processado)} registros** encontrados.")
        
        # ==================== FILTROS DINÂMICOS ====================
        st.sidebar.subheader("🔍 Filtros Avançados")
        
        # Criar cópia para filtros
        df_original = df_processado.copy()
        df_filtrado = df_processado.copy()
        
        # Filtro por ano
        if 'ano' in df_filtrado.columns:
            anos_disponiveis = sorted(df_filtrado['ano'].dropna().unique())
            if anos_disponiveis:
                ano_selecionado = st.sidebar.selectbox("📅 Ano:", ['Todos'] + list(anos_disponiveis))
                if ano_selecionado != 'Todos':
                    df_filtrado = df_filtrado[df_filtrado['ano'] == ano_selecionado]
        
        # Filtro por mês
        if 'mes' in df_filtrado.columns:
            meses_disponiveis = sorted(df_filtrado['mes'].dropna().unique())
            if meses_disponiveis:
                mes_selecionado = st.sidebar.selectbox("📅 Mês:", ['Todos'] + list(meses_disponiveis))
                if mes_selecionado != 'Todos':
                    df_filtrado = df_filtrado[df_filtrado['mes'] == mes_selecionado]
        
        # Filtro por município
        if 'municipio' in df_filtrado.columns:
            municipios_disponiveis = sorted(df_filtrado['municipio'].dropna().unique())
            if municipios_disponiveis:
                municipio_selecionado = st.sidebar.selectbox("🏙️ Município:", ['Todos'] + list(municipios_disponiveis))
                if municipio_selecionado != 'Todos':
                    df_filtrado = df_filtrado[df_filtrado['municipio'] == municipio_selecionado]
        
        # Filtro por serventia
        if 'serventia' in df_filtrado.columns:
            serventias_disponiveis = sorted(df_filtrado['serventia'].dropna().unique())
            if serventias_disponiveis:
                serventia_selecionada = st.sidebar.selectbox("🏢 Serventia:", ['Todas'] + list(serventias_disponiveis))
                if serventia_selecionada != 'Todas':
                    df_filtrado = df_filtrado[df_filtrado['serventia'] == serventia_selecionada]
        
        # Filtro por posto/unidade
        if 'posto_unidade' in df_filtrado.columns:
            postos_disponiveis = sorted(df_filtrado['posto_unidade'].dropna().unique())
            if postos_disponiveis:
                posto_selecionado = st.sidebar.selectbox("🏛️ Posto/Unidade:", ['Todos'] + list(postos_disponiveis))
                if posto_selecionado != 'Todos':
                    df_filtrado = df_filtrado[df_filtrado['posto_unidade'] == posto_selecionado]
        
        # Filtro por faixa de percentual
        if 'percentual' in df_filtrado.columns:
            min_perc = float(df_filtrado['percentual'].min())
            max_perc = float(df_filtrado['percentual'].max())
            if min_perc < max_perc:
                faixa_percentual = st.sidebar.slider(
                    "📊 Faixa de Percentual:",
                    min_perc, max_perc,
                    (min_perc, max_perc),
                    step=0.1
                )
                df_filtrado = df_filtrado[
                    (df_filtrado['percentual'] >= faixa_percentual[0]) & 
                    (df_filtrado['percentual'] <= faixa_percentual[1])
                ]
        
        # Mostrar info sobre filtros aplicados
        if len(df_filtrado) != len(df_original):
            st.sidebar.success(f"📊 Filtros aplicados: **{len(df_filtrado)}** de **{len(df_original)}** registros")
        else:
            st.sidebar.info(f"📊 Exibindo todos os **{len(df_filtrado)}** registros")
        
        # ==================== ABAS PRINCIPAIS ====================
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "📈 Gráficos", "🗺️ Análise Geográfica", "📋 Relatório Executivo"])
        
        with tab1:
            st.header("📈 Dashboard Principal")
            
            # Métricas principais em destaque
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                total_nascimentos = df_filtrado['nascimentos'].sum() if 'nascimentos' in df_filtrado.columns else 0
                st.metric("👶 Total Nascimentos", f"{total_nascimentos:,}")
            
            with col2:
                total_registros = df_filtrado['registros'].sum() if 'registros' in df_filtrado.columns else 0
                st.metric("📝 Total Registros", f"{total_registros:,}")
            
            with col3:
                percentual_medio = df_filtrado['percentual'].mean() if 'percentual' in df_filtrado.columns else 0
                delta_perc = percentual_medio - 85  # Meta de 85%
                st.metric("📊 Percentual Médio", f"{percentual_medio:.1f}%", f"{delta_perc:+.1f}%")
            
            with col4:
                municipios_unicos = df_filtrado['municipio'].nunique() if 'municipio' in df_filtrado.columns else 0
                st.metric("🏙️ Municípios", municipios_unicos)
            
            with col5:
                deficit_total = df_filtrado['deficit'].sum() if 'deficit' in df_filtrado.columns else 0
                st.metric("⚠️ Déficit Total", f"{deficit_total:,}")
            
            st.markdown("---")
            
            # Tabela principal com TODOS os dados
            st.subheader("📋 Dados Completos da Base")
            
            # Seletor de colunas para exibir
            todas_colunas = df_filtrado.columns.tolist()
            colunas_originais = df.columns.tolist()
            
            col1, col2 = st.columns(2)
            
            with col1:
                exibir_processados = st.checkbox("Exibir dados processados", value=True)
            
            with col2:
                exibir_originais = st.checkbox("Exibir dados originais", value=False)
            
            if exibir_processados:
                # Selecionar colunas mais importantes para exibição
                colunas_importantes = []
                mapeamento_exibicao = {
                    'data_formatada': 'Data/Hora',
                    'municipio': 'Município', 
                    'serventia': 'Serventia',
                    'posto_unidade': 'Posto/Unidade',
                    'ano': 'Ano',
                    'mes': 'Mês',
                    'nascimentos': 'Nascimentos',
                    'registros': 'Registros',
                    'percentual': 'Percentual (%)',
                    'deficit': 'Déficit',
                    'motivos': 'Motivos'
                }
                
                for col_interna, col_exibicao in mapeamento_exibicao.items():
                    if col_interna in df_filtrado.columns:
                        colunas_importantes.append(col_interna)
                
                if colunas_importantes:
                    df_exibicao = df_filtrado[colunas_importantes].copy()
                    
                    # Renomear para exibição
                    df_exibicao = df_exibicao.rename(columns=mapeamento_exibicao)
                    
                    st.dataframe(
                        df_exibicao,
                        use_container_width=True,
                        height=500
                    )
                else:
                    st.dataframe(df_filtrado, use_container_width=True, height=500)
            
            if exibir_originais:
                st.subheader("📄 Dados Originais da Planilha")
                st.dataframe(df, use_container_width=True, height=400)
            
            # Downloads
            col1, col2 = st.columns(2)
            
            with col1:
                csv_filtrado = df_filtrado.to_csv(index=False)
                st.download_button(
                    label="💾 Download Dados Filtrados (CSV)",
                    data=csv_filtrado,
                    file_name=f"dados_filtrados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            
            with col2:
                csv_original = df.to_csv(index=False)
                st.download_button(
                    label="💾 Download Dados Originais (CSV)",
                    data=csv_original,
                    file_name=f"dados_originais_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
        
        with tab2:
            st.header("📈 Análises Gráficas Interativas")
            criar_graficos_streamlit(df_filtrado)
        
        with tab3:
            st.header("🗺️ Análise Geográfica Detalhada")
            dados_geograficos = criar_resumo_geografico(df_filtrado)
        
        with tab4:
            st.header("📋 Relatório Executivo")
            relatorio_texto = gerar_relatorio_completo(df_filtrado)
            
            # Download do relatório
            st.download_button(
                label="💾 Download Relatório Executivo (TXT)",
                data=relatorio_texto,
                file_name=f"relatorio_executivo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain"
            )
        
        # Rodapé com informações do sistema
        st.markdown("---")
        st.markdown(f"""
        <div style='text-align: center; color: gray; font-size: 12px; padding: 10px;'>
        🕒 <strong>Sistema atualizado em:</strong> {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')} | 
        📊 <strong>Dados do Provimento 07/2021</strong> | 
        📈 <strong>{len(df_filtrado):,} registros processados</strong> |
        🔄 <strong>Cache ativo</strong>
        </div>
        """, unsafe_allow_html=True)
    
    else:
        # Tela inicial
        st.info("👆 **Selecione uma fonte de dados na barra lateral para começar a análise.**")
        
        st.markdown("""
        ## 📋 Sobre o Sistema
        
        Este sistema foi desenvolvido para **monitoramento completo** dos dados do **Provimento 07/2021** 
        referente aos registros de nascimentos em unidades interligadas do estado do Maranhão.
        
        ### 🎯 **Funcionalidades Implementadas:**
        
        ✅ **Carregamento Automático** - Conexão direta com a planilha oficial  
        ✅ **Upload Personalizado** - Drag & drop de arquivos CSV  
        ✅ **URLs Externas** - Importação de planilhas via link  
        ✅ **Filtros Avançados** - Por todos os campos: ano, mês, município, serventia, posto/unidade, percentual  
        ✅ **Visualizações Dinâmicas** - Gráficos interativos organizáveis por qualquer campo  
        ✅ **Análise Geográfica** - Performance detalhada por município  
        ✅ **Relatório Executivo** - Relatório automático completo  
        ✅ **Downloads Múltiplos** - Dados filtrados, originais e relatórios  
        ✅ **Cache Inteligente** - Performance otimizada  
        ✅ **Interface Responsiva** - Totalmente adaptável  
        
        ### 📊 **Campos Monitorados (Cabeçalhos Reais):**
        
        1. **Carimbo de data/hora** - Timestamp completo
        2. **Endereço de e-mail** - Identificação do responsável
        3. **MUNICÍPIO** - Localização geográfica
        4. **Nome da Serventia** - Cartório responsável
        5. **Posto/Unidade Interligada** - Unidade específica
        6. **Mês** e **Ano** - Período de referência
        7. **NASCIMENTOS (QTDE)** - Total de nascimentos
        8. **REGISTROS (QTDE)** - Total de registros realizados
        9. **Motivos de não 100%** - Justificativas de déficit
        10. **% Ok** - Percentual de cobertura
        
        ### 🚀 **Como Usar:**
        
        1. **Clique em "🔄 Carregar Dados"** na barra lateral
        2. **Aguarde** o carregamento dos dados (4.191 registros)
        3. **Use os filtros** para segmentar a análise
        4. **Navegue pelas abas** para diferentes visões
        5. **Faça downloads** dos dados e relatórios
        
        ---
        
        **💡 Dica:** O sistema mantém 100% dos dados originais e permite análise completa 
        com filtros dinâmicos e visualizações interativas!
        """)

# ==================== EXECUTAR APLICAÇÃO ====================
if __name__ == "__main__":
    main()
