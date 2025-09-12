import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import folium
from streamlit_folium import st_folium
import requests
import io
from datetime import datetime, timedelta
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
    
    # Limpeza de dados
    df = df.dropna(subset=['municipio']) if 'municipio' in df.columns else df
    
    return df

def criar_graficos(df: pd.DataFrame):
    """Cria gráficos interativos"""
    
    # Gráfico 1: Nascimentos vs Registros por Município
    if all(col in df.columns for col in ['municipio', 'nascimentos', 'registros']):
        fig1 = go.Figure()
        
        municipios_agrupados = df.groupby('municipio').agg({
            'nascimentos': 'sum',
            'registros': 'sum'
        }).reset_index()
        
        fig1.add_trace(go.Bar(
            name='Nascimentos',
            x=municipios_agrupados['municipio'],
            y=municipios_agrupados['nascimentos'],
            marker_color='lightblue'
        ))
        
        fig1.add_trace(go.Bar(
            name='Registros',
            x=municipios_agrupados['municipio'],
            y=municipios_agrupados['registros'],
            marker_color='darkblue'
        ))
        
        fig1.update_layout(
            title='Nascimentos vs Registros por Município',
            xaxis_title='Município',
            yaxis_title='Quantidade',
            barmode='group',
            height=500
        )
        
        st.plotly_chart(fig1, use_container_width=True)
    
    # Gráfico 2: Percentual de Registros
    if 'percentual' in df.columns and 'municipio' in df.columns:
        percentual_medio = df.groupby('municipio')['percentual'].mean().reset_index()
        
        fig2 = px.bar(
            percentual_medio,
            x='municipio',
            y='percentual',
            title='Percentual Médio de Registros por Município',
            color='percentual',
            color_continuous_scale='RdYlGn'
        )
        
        fig2.update_layout(height=500)
        st.plotly_chart(fig2, use_container_width=True)
    
    # Gráfico 3: Evolução Temporal
    if all(col in df.columns for col in ['ano', 'mes', 'registros']):
        df_temporal = df.groupby(['ano', 'mes'])['registros'].sum().reset_index()
        df_temporal['data'] = pd.to_datetime(df_temporal[['ano', 'mes']].assign(day=1))
        
        fig3 = px.line(
            df_temporal,
            x='data',
            y='registros',
            title='Evolução Temporal dos Registros',
            markers=True
        )
        
        fig3.update_layout(height=400)
        st.plotly_chart(fig3, use_container_width=True)

# Coordenadas dos municípios do Maranhão (amostra)
COORDENADAS_MUNICIPIOS = {
    'São Luís': [-2.5307, -44.2706],
    'Imperatriz': [-5.5294, -47.4916],
    'Timon': [-5.0951, -42.8369],
    'Caxias': [-4.8587, -43.3563],
    'Codó': [-4.4553, -43.8856],
    'Açailândia': [-4.9472, -47.5078],
    'Bacabal': [-4.2251, -43.4261],
    'Balsas': [-7.5324, -46.0351],
    'Santa Inês': [-3.6679, -45.3788],
    'Pinheiro': [-2.5218, -45.0836]
}

def criar_mapa(df: pd.DataFrame):
    """Cria mapa interativo com dados dos municípios"""
    
    # Criar mapa centrado no Maranhão
    mapa = folium.Map(
        location=[-4.9609, -45.2744],  # Centro do Maranhão
        zoom_start=7,
        tiles='OpenStreetMap'
    )
    
    if 'municipio' in df.columns:
        # Agrupar dados por município
        dados_municipios = df.groupby('municipio').agg({
            'nascimentos': 'sum',
            'registros': 'sum',
            'percentual': 'mean'
        }).reset_index()
        
        # Adicionar marcadores no mapa
        for _, row in dados_municipios.iterrows():
            municipio = row['municipio']
            
            if municipio in COORDENADAS_MUNICIPIOS:
                lat, lon = COORDENADAS_MUNICIPIOS[municipio]
                
                # Criar popup com informações
                popup_text = f"""
                <b>{municipio}</b><br>
                Nascimentos: {int(row['nascimentos'])}<br>
                Registros: {int(row['registros'])}<br>
                Percentual: {row['percentual']:.1f}%
                """
                
                # Cor do marcador baseada no percentual
                cor = 'green' if row['percentual'] >= 90 else 'orange' if row['percentual'] >= 70 else 'red'
                
                folium.Marker(
                    location=[lat, lon],
                    popup=folium.Popup(popup_text, max_width=200),
                    tooltip=municipio,
                    icon=folium.Icon(color=cor, icon='info-sign')
                ).add_to(mapa)
    
    return mapa

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
        
        # ==================== ABAS PRINCIPAIS ====================
        tab1, tab2 = st.tabs(["📊 Análise e Gráficos", "🗺️ Mapa Geográfico"])
        
        with tab1:
            st.header("📈 Análise dos Dados")
            
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
            
            # Gráficos
            criar_graficos(df)
            
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
            
            # Download dos dados filtrados
            csv_dados = df.to_csv(index=False)
            st.download_button(
                label="💾 Download CSV Filtrado",
                data=csv_dados,
                file_name=f"dados_filtrados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        
        with tab2:
            st.header("🗺️ Visualização Geográfica")
            st.markdown("Distribuição dos dados por município no estado do Maranhão")
            
            # Criar e exibir mapa
            mapa = criar_mapa(df)
            st_folium(mapa, width=None, height=500)
            
            # Legenda do mapa
            st.markdown("""
            **Legenda dos Marcadores:**
            - 🟢 Verde: Percentual ≥ 90%
            - 🟠 Laranja: Percentual entre 70% e 90%
            - 🔴 Vermelho: Percentual < 70%
            """)
            
            # Resumo por município
            if 'municipio' in df.columns:
                st.subheader("📊 Resumo por Município")
                resumo_municipio = df.groupby('municipio').agg({
                    'nascimentos': 'sum',
                    'registros': 'sum',
                    'percentual': 'mean'
                }).round(2).reset_index()
                
                st.dataframe(
                    resumo_municipio,
                    use_container_width=True,
                    height=300
                )
    
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
        - ✅ Filtros dinâmicos por ano, mês, município, serventia e percentual
        - ✅ Gráficos interativos e analíticos
        - ✅ Mapa geográfico com distribuição por município
        - ✅ Download de dados filtrados
        - ✅ Interface responsiva e intuitiva
        
        ### 📊 Campos Monitorados:
        - Carimbo de data e hora
        - Município e serventia
        - Nascimentos e registros
        - Percentuais de cobertura
        - Motivos de não atingimento de 100%
        """)

# ==================== EXECUTAR APLICAÇÃO ====================
if __name__ == "__main__":
    main()
