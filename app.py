import streamlit as st
import pandas as pd
import requests
import io
from datetime import datetime
import base64
from typing import Optional
import time
import json

# ==================== CONFIGURAÇÃO DA PÁGINA ====================
st.set_page_config(
    page_title="Provimento 07/2021 - Sistema Completo",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== INICIALIZAÇÃO DO CACHE TRANSPARENTE ====================
def inicializar_cache():
    """Inicializa o sistema de cache transparente"""
    if 'dados_cache' not in st.session_state:
        st.session_state.dados_cache = None
    if 'dados_originais_cache' not in st.session_state:
        st.session_state.dados_originais_cache = None
    if 'estatisticas_cache' not in st.session_state:
        st.session_state.estatisticas_cache = None
    if 'analise_qualidade_cache' not in st.session_state:
        st.session_state.analise_qualidade_cache = None
    if 'timestamp_cache' not in st.session_state:
        st.session_state.timestamp_cache = None
    if 'cache_ativo' not in st.session_state:
        st.session_state.cache_ativo = False

def salvar_no_cache(df_processado, df_original, estatisticas, analise_qualidade):
    """Salva dados no cache transparente automaticamente"""
    st.session_state.dados_cache = df_processado.copy()
    st.session_state.dados_originais_cache = df_original.copy() 
    st.session_state.estatisticas_cache = estatisticas.copy()
    st.session_state.analise_qualidade_cache = analise_qualidade.copy()
    st.session_state.timestamp_cache = datetime.now()
    st.session_state.cache_ativo = True

def limpar_cache():
    """Limpa o cache quando solicitado"""
    st.session_state.dados_cache = None
    st.session_state.dados_originais_cache = None
    st.session_state.estatisticas_cache = None
    st.session_state.analise_qualidade_cache = None
    st.session_state.timestamp_cache = None
    st.session_state.cache_ativo = False

# ==================== FUNÇÕES DE CARREGAMENTO ====================

@st.cache_data(ttl=300)
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

# ==================== ANÁLISE DE QUALIDADE ====================

def analisar_qualidade_dados(df: pd.DataFrame):
    """Analisa a qualidade dos dados e retorna estatísticas"""
    
    total_registros = len(df)
    analise_qualidade = {}
    
    campos_criticos = {
        'Carimbo de data/hora': 'timestamp',
        'MUNICÍPIO': 'municipio',
        'Nome da Serventia': 'serventia',
        'Posto/Unidade Interligada': 'posto_unidade',
        'Mês': 'mes',
        'Ano': 'ano',
        'NASCIMENTOS (QTDE)': 'nascimentos',
        'REGISTROS (QTDE)': 'registros'
    }
    
    for campo_original, campo_interno in campos_criticos.items():
        if campo_original in df.columns:
            nulos = df[campo_original].isna().sum()
            vazios = (df[campo_original] == '').sum()
            na_strings = df[campo_original].astype(str).str.lower().isin(['n/a', 'na', 'não informado', 'null']).sum()
            
            total_problemas = nulos + vazios + na_strings
            percentual_problemas = (total_problemas / total_registros) * 100
            
            analise_qualidade[campo_original] = {
                'total_problemas': total_problemas,
                'nulos': nulos,
                'vazios': vazios,
                'na_strings': na_strings,
                'percentual_problemas': percentual_problemas,
                'registros_validos': total_registros - total_problemas
            }
    
    return analise_qualidade, total_registros

def limpar_dados(df: pd.DataFrame):
    """Remove registros com dados críticos nulos e retorna estatísticas de limpeza"""
    
    df_original = df.copy()
    total_original = len(df_original)
    
    colunas_criticas = []
    if 'MUNICÍPIO' in df.columns:
        colunas_criticas.append('MUNICÍPIO')
    if 'NASCIMENTOS (QTDE)' in df.columns:
        colunas_criticas.append('NASCIMENTOS (QTDE)')
    if 'REGISTROS (QTDE)' in df.columns:
        colunas_criticas.append('REGISTROS (QTDE)')
    
    stats_antes = {}
    for col in colunas_criticas:
        if col in df.columns:
            nulos = df[col].isna().sum()
            vazios = (df[col] == '').sum()
            na_strings = df[col].astype(str).str.lower().isin(['n/a', 'na', 'não informado', 'null', 'nan']).sum()
            stats_antes[col] = nulos + vazios + na_strings
    
    df_limpo = df.copy()
    
    # Limpeza progressiva
    if 'MUNICÍPIO' in df_limpo.columns:
        mask_municipio = (
            df_limpo['MUNICÍPIO'].notna() & 
            (df_limpo['MUNICÍPIO'] != '') & 
            (~df_limpo['MUNICÍPIO'].astype(str).str.lower().isin(['n/a', 'na', 'não informado', 'null', 'nan']))
        )
        df_limpo = df_limpo[mask_municipio]
    
    if 'NASCIMENTOS (QTDE)' in df_limpo.columns:
        df_limpo = df_limpo[df_limpo['NASCIMENTOS (QTDE)'].notna()]
        df_limpo = df_limpo[df_limpo['NASCIMENTOS (QTDE)'] != '']
    
    if 'REGISTROS (QTDE)' in df_limpo.columns:
        df_limpo = df_limpo[df_limpo['REGISTROS (QTDE)'].notna()]
        df_limpo = df_limpo[df_limpo['REGISTROS (QTDE)'] != '']
    
    # Converter valores numéricos
    colunas_numericas = ['NASCIMENTOS (QTDE)', 'REGISTROS (QTDE)', 'Mês', 'Ano']
    for col in colunas_numericas:
        if col in df_limpo.columns:
            df_limpo[col] = pd.to_numeric(df_limpo[col], errors='coerce')
    
    # Remover onde conversão falhou
    if 'NASCIMENTOS (QTDE)' in df_limpo.columns:
        df_limpo = df_limpo[df_limpo['NASCIMENTOS (QTDE)'].notna()]
    if 'REGISTROS (QTDE)' in df_limpo.columns:
        df_limpo = df_limpo[df_limpo['REGISTROS (QTDE)'].notna()]
    
    total_apos_limpeza = len(df_limpo)
    registros_removidos = total_original - total_apos_limpeza
    percentual_removido = (registros_removidos / total_original) * 100 if total_original > 0 else 0
    
    estatisticas_limpeza = {
        'total_original': total_original,
        'total_limpo': total_apos_limpeza,
        'registros_removidos': registros_removidos,
        'percentual_removido': percentual_removido,
        'stats_antes': stats_antes
    }
    
    return df_limpo, estatisticas_limpeza

def processar_dados(df: pd.DataFrame):
    """Processa dados já limpos"""
    
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
    
    df_processado = df.copy()
    
    for col_original, col_nova in colunas_reais.items():
        if col_original in df_processado.columns:
            df_processado[col_nova] = df_processado[col_original]
    
    # Processar timestamp
    if 'timestamp' in df_processado.columns:
        df_processado['timestamp'] = pd.to_datetime(df_processado['timestamp'], errors='coerce')
        df_processado['ano_timestamp'] = df_processado['timestamp'].dt.year
        df_processado['mes_timestamp'] = df_processado['timestamp'].dt.month
        df_processado['data_formatada'] = df_processado['timestamp'].dt.strftime('%d/%m/%Y %H:%M')
    
    # Calcular percentual
    if 'nascimentos' in df_processado.columns and 'registros' in df_processado.columns:
        df_processado['percentual_calculado'] = (
            (df_processado['registros'] / df_processado['nascimentos']) * 100
        ).round(2)
        df_processado['percentual_calculado'] = df_processado['percentual_calculado'].fillna(0)
        df_processado['percentual_calculado'] = df_processado['percentual_calculado'].clip(upper=100)
        
        if 'percentual_original' in df_processado.columns:
            df_processado['percentual'] = df_processado['percentual_original'].fillna(df_processado['percentual_calculado'])
        else:
            df_processado['percentual'] = df_processado['percentual_calculado']
    
    # Calcular déficit
    if 'nascimentos' in df_processado.columns and 'registros' in df_processado.columns:
        df_processado['deficit'] = df_processado['nascimentos'] - df_processado['registros']
        df_processado['deficit'] = df_processado['deficit'].fillna(0)
    
    # Limpar campos de texto
    campos_texto = ['email', 'serventia', 'posto_unidade', 'motivos']
    for col in campos_texto:
        if col in df_processado.columns:
            df_processado[col] = df_processado[col].fillna('Não informado')
            df_processado[col] = df_processado[col].replace('', 'Não informado')
    
    return df_processado

def mostrar_analise_qualidade(analise_qualidade, total_registros, estatisticas_limpeza):
    """Mostra análise detalhada da qualidade dos dados"""
    
    st.subheader("🔍 Análise de Qualidade dos Dados")
    
    # Métricas de limpeza
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "📊 Registros Originais", 
            f"{estatisticas_limpeza['total_original']:,}"
        )
    
    with col2:
        st.metric(
            "✅ Registros Válidos", 
            f"{estatisticas_limpeza['total_limpo']:,}",
            f"-{estatisticas_limpeza['registros_removidos']:,}"
        )
    
    with col3:
        st.metric(
            "🗑️ Registros Removidos", 
            f"{estatisticas_limpeza['registros_removidos']:,}",
            f"{estatisticas_limpeza['percentual_removido']:.1f}%"
        )
    
    with col4:
        qualidade_geral = 100 - estatisticas_limpeza['percentual_removido']
        st.metric(
            "📈 Qualidade Geral", 
            f"{qualidade_geral:.1f}%"
        )
    
    # Detalhamento por campo
    st.subheader("📋 Problemas Encontrados por Campo")
    
    dados_qualidade = []
    for campo, stats in analise_qualidade.items():
        dados_qualidade.append({
            'Campo': campo,
            'Registros Válidos': f"{stats['registros_validos']:,}",
            'Problemas Total': f"{stats['total_problemas']:,}",
            'Nulos': f"{stats['nulos']:,}",
            'Vazios': f"{stats['vazios']:,}",
            'N/A Strings': f"{stats['na_strings']:,}",
            '% Problemas': f"{stats['percentual_problemas']:.1f}%"
        })
    
    if dados_qualidade:
        df_qualidade = pd.DataFrame(dados_qualidade)
        st.dataframe(df_qualidade, use_container_width=True)

# ==================== ANÁLISE DE CONFORMIDADE ====================

def analisar_conformidade_municipio(df: pd.DataFrame, municipio: str):
    """Analisa conformidade de envio mensal por município conforme Provimento 07/2021"""
    
    if 'municipio' not in df.columns or 'ano' not in df.columns or 'mes' not in df.columns:
        return None
    
    # Filtrar dados do município específico
    df_municipio = df[df['municipio'] == municipio].copy()
    
    if df_municipio.empty:
        return None
    
    # Anos disponíveis nos dados
    anos_disponiveis = sorted(df_municipio['ano'].unique())
    
    analise_conformidade = {}
    
    for ano in anos_disponiveis:
        dados_ano = df_municipio[df_municipio['ano'] == ano]
        
        # Meses informados neste ano
        meses_informados = sorted(dados_ano['mes'].unique())
        meses_esperados = list(range(1, 13))  # 1 a 12
        meses_faltantes = [mes for mes in meses_esperados if mes not in meses_informados]
        
        # Calcular estatísticas
        total_esperado = 12
        total_informado = len(meses_informados)
        total_faltante = len(meses_faltantes)
        percentual_conformidade = (total_informado / total_esperado) * 100
        percentual_defasagem = (total_faltante / total_esperado) * 100
        
        # Converter números de meses para nomes
        nomes_meses = {
            1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
            5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
            9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
        }
        
        meses_faltantes_nomes = [f"{nomes_meses[mes]}/{ano}" for mes in meses_faltantes]
        meses_informados_nomes = [f"{nomes_meses[mes]}/{ano}" for mes in meses_informados]
        
        analise_conformidade[ano] = {
            'total_esperado': total_esperado,
            'total_informado': total_informado,
            'total_faltante': total_faltante,
            'percentual_conformidade': percentual_conformidade,
            'percentual_defasagem': percentual_defasagem,
            'meses_informados': meses_informados,
            'meses_faltantes': meses_faltantes,
            'meses_informados_nomes': meses_informados_nomes,
            'meses_faltantes_nomes': meses_faltantes_nomes
        }
    
    # Calcular totais gerais
    total_meses_esperados = len(anos_disponiveis) * 12
    total_meses_informados = sum([dados['total_informado'] for dados in analise_conformidade.values()])
    total_meses_faltantes = total_meses_esperados - total_meses_informados
    
    conformidade_geral = (total_meses_informados / total_meses_esperados) * 100 if total_meses_esperados > 0 else 0
    defasagem_geral = (total_meses_faltantes / total_meses_esperados) * 100 if total_meses_esperados > 0 else 0
    
    # Todos os meses faltantes
    todos_meses_faltantes = []
    for ano_dados in analise_conformidade.values():
        todos_meses_faltantes.extend(ano_dados['meses_faltantes_nomes'])
    
    resultado = {
        'municipio': municipio,
        'anos_analisados': anos_disponiveis,
        'analise_por_ano': analise_conformidade,
        'total_meses_esperados': total_meses_esperados,
        'total_meses_informados': total_meses_informados,
        'total_meses_faltantes': total_meses_faltantes,
        'conformidade_geral': conformidade_geral,
        'defasagem_geral': defasagem_geral,
        'todos_meses_faltantes': todos_meses_faltantes
    }
    
    return resultado

def gerar_relatorio_conformidade(analise: dict):
    """Gera relatório executivo de conformidade para um município"""
    
    municipio = analise['municipio']
    conformidade = analise['conformidade_geral']
    defasagem = analise['defasagem_geral']
    meses_faltantes = analise['todos_meses_faltantes']
    
    if not meses_faltantes:
        relatorio = f"""
**📋 RELATÓRIO DE CONFORMIDADE - PROVIMENTO 07/2021**

✅ **A unidade {municipio} está em CONFORMIDADE TOTAL!**

• Todos os meses foram informados conforme exigido
• Percentual de Conformidade: {conformidade:.1f}%
• Status: EM DIA com as obrigações

**Parabéns! Esta unidade está cumprindo integralmente o Provimento 07/2021.**
        """
    else:
        relatorio = f"""
**📋 RELATÓRIO DE CONFORMIDADE - PROVIMENTO 07/2021**

⚠️ **A unidade {municipio} possui PENDÊNCIAS!**

• Percentual de Conformidade: {conformidade:.1f}%
• Percentual de Defasagem: {defasagem:.1f}%
• Total de meses em débito: {len(meses_faltantes)}

**🔴 MESES EM DÉBITO:**
{chr(10).join([f"• {mes}" for mes in meses_faltantes])}

**📝 AÇÃO NECESSÁRIA:**
A unidade deve regularizar os envios em atraso conforme determina o Provimento 07/2021, 
que obriga o envio mensal até o dia 10 de cada mês das informações sobre nascimentos e registros.

**⚡ URGÊNCIA:** {
    "ALTA - Mais de 6 meses em atraso" if len(meses_faltantes) > 6 
    else "MÉDIA - Entre 3 e 6 meses em atraso" if len(meses_faltantes) > 3
    else "BAIXA - Poucos meses em atraso"
}
        """
    
    return relatorio

def criar_grafico_conformidade(analise: dict):
    """Cria visualização de conformidade vs não conformidade"""
    
    conformidade = analise['conformidade_geral']
    defasagem = analise['defasagem_geral']
    
    # Dados para o gráfico
    dados_grafico = pd.DataFrame({
        'Status': ['Em Conformidade', 'Em Defasagem'],
        'Percentual': [conformidade, defasagem],
        'Cor': ['🟢', '🔴']
    })
    
    return dados_grafico

# ==================== GRÁFICOS ====================

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

# ==================== ANÁLISE GEOGRÁFICA ====================

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

# ==================== RELATÓRIO EXECUTIVO ====================

def gerar_relatorio_completo(df: pd.DataFrame, estatisticas_limpeza: dict):
    """Gera relatório executivo completo incluindo qualidade dos dados"""
    
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

**QUALIDADE DOS DADOS:**
• Registros Originais Carregados: {estatisticas_limpeza['total_original']:,}
• Registros Válidos Processados: {estatisticas_limpeza['total_limpo']:,}
• Registros Removidos (Dados Inconsistentes): {estatisticas_limpeza['registros_removidos']:,}
• Percentual de Dados Removidos: {estatisticas_limpeza['percentual_removido']:.2f}%
• Qualidade Geral dos Dados: {100 - estatisticas_limpeza['percentual_removido']:.2f}%

**PERÍODO DE ANÁLISE:**
• Data de Início: {data_inicio.strftime('%d/%m/%Y') if data_inicio != 'N/A' else 'N/A'}
• Data de Fim: {data_fim.strftime('%d/%m/%Y') if data_fim != 'N/A' else 'N/A'}
• Total de Registros Válidos na Análise: {len(df):,}

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
        
        if atencao > 0:
            relatorio += f"\n\n**MUNICÍPIOS QUE PRECISAM DE ATENÇÃO URGENTE (Menor Percentual):**"
            bottom10 = dados_municipios.nsmallest(min(10, atencao))
            for i, (municipio, perc) in enumerate(bottom10.items(), 1):
                relatorio += f"\n{i:2d}. {municipio}: {perc:.1f}%"
    
    relatorio += f"""

═══════════════════════════════════════════════════════════════
**RECOMENDAÇÕES PARA MELHORIA:**

1. **CORREÇÃO DE DADOS:** {estatisticas_limpeza['registros_removidos']:,} registros precisam de correção manual

2. **FOCO PRIORITÁRIO:** Concentrar esforços nos municípios com performance abaixo de 70%

3. **CONFORMIDADE PROVIMENTO 07/2021:** Monitorar envios mensais até dia 10

4. **MONITORAMENTO:** Acompanhar semanalmente a qualidade dos dados inseridos

5. **TREINAMENTO:** Capacitar equipes responsáveis pelo preenchimento dos formulários

═══════════════════════════════════════════════════════════════
Relatório gerado automaticamente em {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}
Sistema Completo - Provimento 07/2021
Base de dados limpa, validada e em cache para análise otimizada.
    """
    
    st.markdown(relatorio)
    return relatorio

# ==================== INTERFACE PRINCIPAL ====================

def main():
    # Inicializar cache transparente
    inicializar_cache()
    
    st.title("📊 Sistema Completo - Provimento 07/2021")
    st.markdown("**Monitoramento Avançado + Análise de Conformidade + Cache Transparente**")
    
    # ==================== SIDEBAR ====================
    st.sidebar.header("⚙️ Configurações do Sistema")
    
    # Status do Cache Transparente
    st.sidebar.subheader("💾 Cache Transparente")
    if st.session_state.cache_ativo:
        st.sidebar.success(f"✅ Dados em memória desde {st.session_state.timestamp_cache.strftime('%d/%m/%Y %H:%M')}")
        st.sidebar.info(f"📊 {len(st.session_state.dados_cache):,} registros armazenados")
        
        # Botões de gerenciamento do cache
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.button("🗑️ Limpar"):
                limpar_cache()
                st.rerun()
        
        with col2:
            # Export do cache
            dados_cache = st.session_state.dados_cache.to_csv(index=False) if st.session_state.dados_cache is not None else None
            if dados_cache:
                st.download_button(
                    label="💾 Export",
                    data=dados_cache,
                    file_name=f"cache_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
    else:
        st.sidebar.info("🔄 Cache vazio - carregue dados")
    
    # URL padrão da planilha
    url_padrao = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRtKiqlosLL5_CJgGom7BlWpFYExhLTQEjQT_Pdgnv3uEYMlWPpsSeaxfjqy0IxTluVlKSpcZ1IoXQY/pub?gid=152355120&single=true&output=csv"
    
    st.sidebar.subheader("📥 Fonte de Dados")
    fonte_dados = st.sidebar.radio(
        "Escolha a fonte:",
        ["URL Padrão", "URL Personalizada", "Upload de Arquivo"]
    )
    
    df = None
    carregar_novos_dados = False
    
    if fonte_dados == "URL Padrão":
        st.sidebar.info("Planilha padrão do Provimento 07/2021")
        if st.sidebar.button("🔄 Carregar Dados"):
            with st.spinner("Carregando dados..."):
                df = carregar_dados_url(url_padrao)
                carregar_novos_dados = True
    
    elif fonte_dados == "URL Personalizada":
        url_custom = st.sidebar.text_input("Cole a URL do CSV:", placeholder="https://...")
        if url_custom and st.sidebar.button("🔄 Carregar da URL"):
            with st.spinner("Carregando dados..."):
                df = carregar_dados_url(url_custom)
                carregar_novos_dados = True
    
    else:  # Upload de arquivo
        arquivo = st.sidebar.file_uploader(
            "Envie seu arquivo CSV:",
            type=['csv'],
            help="Arraste e solte ou clique para selecionar"
        )
        if arquivo:
            with st.spinner("Processando arquivo..."):
                df = carregar_dados_arquivo(arquivo)
                carregar_novos_dados = True
    
    # ==================== PROCESSAMENTO DOS DADOS ====================
    
    # Se há dados em cache E não está carregando novos dados, usar cache
    if st.session_state.cache_ativo and not carregar_novos_dados and df is None:
        df_processado = st.session_state.dados_cache
        df_original = st.session_state.dados_originais_cache
        estatisticas_limpeza = st.session_state.estatisticas_cache
        analise_qualidade = st.session_state.analise_qualidade_cache
        
        st.success(f"✅ **{len(df_processado):,} registros** carregados do cache automaticamente!")
        
    elif df is not None:
        # Processar novos dados
        with st.expander("🔍 Processamento e Análise de Qualidade", expanded=False):
            
            # Análise de qualidade
            analise_qualidade, total_registros = analisar_qualidade_dados(df)
            
            # Limpeza dos dados
            with st.spinner("Limpando e validando dados..."):
                df_limpo, estatisticas_limpeza = limpar_dados(df)
            
            if df_limpo.empty:
                st.error("❌ Todos os dados foram removidos durante a limpeza!")
                return
            
            # Processar dados limpos
            df_processado = processar_dados(df_limpo)
            df_original = df
            
            # Salvar automaticamente no cache
            salvar_no_cache(df_processado, df_original, estatisticas_limpeza, analise_qualidade)
            
            # Mostrar análise de qualidade
            mostrar_analise_qualidade(analise_qualidade, total_registros, estatisticas_limpeza)
        
        st.success(f"✅ **{len(df_processado):,} registros** processados e armazenados automaticamente no cache!")
        
    else:
        # Verificar se há cache para usar
        if st.session_state.cache_ativo:
            df_processado = st.session_state.dados_cache
            df_original = st.session_state.dados_originais_cache
            estatisticas_limpeza = st.session_state.estatisticas_cache
            analise_qualidade = st.session_state.analise_qualidade_cache
            
            st.info("📊 Usando dados armazenados no cache. Para carregar novos dados, use as opções da sidebar.")
        else:
            # Tela inicial
            st.info("👆 **Selecione uma fonte de dados na barra lateral para começar.**")
            
            st.markdown("""
            ## 🚀 Sistema Completo - Principais Funcionalidades
            
            ### 💾 **Cache Transparente Automático**
            ✅ **Armazenamento Automático** - Dados ficam em memória automaticamente após carregamento  
            ✅ **Preservação de Trabalho** - Navegue entre abas sem perder dados ou filtros  
            ✅ **Performance Otimizada** - Acesso instantâneo aos dados processados  
            ✅ **Propriedades ACID** - Consistência, integridade e durabilidade na sessão  
            
            ### ⚖️ **Análise de Conformidade - Provimento 07/2021**
            ✅ **Verificação Automática** - Analisa cumprimento da obrigação mensal por município  
            ✅ **Cálculo de Defasagem** - Quantos meses foram informados vs esperados  
            ✅ **Meses Faltantes** - Lista exata dos períodos em débito  
            ✅ **Relatório Executivo** - Mensagem automática para cobrança  
            
            ### 📊 **Análise Completa de Dados**
            ✅ **Limpeza Automática** - Remove dados N/A e inconsistentes  
            ✅ **Análise de Qualidade** - Relatórios detalhados de integridade  
            ✅ **Filtros Dinâmicos** - Por ano, mês, município, serventia, percentual  
            ✅ **Gráficos Interativos** - Visualizações organizáveis por qualquer campo  
            ✅ **Análise Geográfica** - Performance detalhada por município  
            
            ---
            
            **🎯 Navegue entre as 5 abas sem perder dados graças ao cache transparente!**
            """)
            return
    
    # ==================== FILTROS DINÂMICOS ====================
    st.sidebar.subheader("🔍 Filtros Avançados")
    
    df_original_completo = df_processado.copy()
    df_filtrado = df_processado.copy()
    
    # Filtros
    if 'ano' in df_filtrado.columns:
        anos_disponiveis = sorted(df_filtrado['ano'].dropna().unique())
        if anos_disponiveis:
            ano_selecionado = st.sidebar.selectbox("📅 Ano:", ['Todos'] + list(anos_disponiveis))
            if ano_selecionado != 'Todos':
                df_filtrado = df_filtrado[df_filtrado['ano'] == ano_selecionado]
    
    if 'mes' in df_filtrado.columns:
        meses_disponiveis = sorted(df_filtrado['mes'].dropna().unique())
        if meses_disponiveis:
            mes_selecionado = st.sidebar.selectbox("📅 Mês:", ['Todos'] + list(meses_disponiveis))
            if mes_selecionado != 'Todos':
                df_filtrado = df_filtrado[df_filtrado['mes'] == mes_selecionado]
    
    if 'municipio' in df_filtrado.columns:
        municipios_disponiveis = sorted(df_filtrado['municipio'].dropna().unique())
        if municipios_disponiveis:
            municipio_selecionado = st.sidebar.selectbox("🏙️ Município:", ['Todos'] + list(municipios_disponiveis))
            if municipio_selecionado != 'Todos':
                df_filtrado = df_filtrado[df_filtrado['municipio'] == municipio_selecionado]
    
    if 'serventia' in df_filtrado.columns:
        serventias_disponiveis = sorted(df_filtrado['serventia'].dropna().unique())
        if serventias_disponiveis:
            serventia_selecionada = st.sidebar.selectbox("🏢 Serventia:", ['Todas'] + list(serventias_disponiveis))
            if serventia_selecionada != 'Todas':
                df_filtrado = df_filtrado[df_filtrado['serventia'] == serventia_selecionada]
    
    if 'posto_unidade' in df_filtrado.columns:
        postos_disponiveis = sorted(df_filtrado['posto_unidade'].dropna().unique())
        if postos_disponiveis:
            posto_selecionado = st.sidebar.selectbox("🏛️ Posto/Unidade:", ['Todos'] + list(postos_disponiveis))
            if posto_selecionado != 'Todos':
                df_filtrado = df_filtrado[df_filtrado['posto_unidade'] == posto_selecionado]
    
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
    if len(df_filtrado) != len(df_original_completo):
        st.sidebar.success(f"📊 Filtros aplicados: **{len(df_filtrado):,}** de **{len(df_original_completo):,}** registros")
    else:
        st.sidebar.info(f"📊 Exibindo todos os **{len(df_filtrado):,}** registros válidos")
    
    # ==================== ABAS PRINCIPAIS ====================
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Dashboard", 
        "⚖️ Análise de Conformidade", 
        "📈 Gráficos Interativos", 
        "🗺️ Análise Geográfica", 
        "📋 Relatório Executivo"
    ])
    
    with tab1:
        st.header("📈 Dashboard Principal")
        
        # Métricas principais
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
        
        # Tabela principal
        st.subheader("📋 Dados Processados (Cache Ativo)")
        
        colunas_importantes = ['data_formatada', 'municipio', 'serventia', 'posto_unidade', 
                             'ano', 'mes', 'nascimentos', 'registros', 'percentual', 'deficit']
        
        colunas_existentes = [col for col in colunas_importantes if col in df_filtrado.columns]
        
        if colunas_existentes:
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
                'deficit': 'Déficit'
            }
            
            df_exibicao = df_filtrado[colunas_existentes].copy()
            df_exibicao = df_exibicao.rename(columns=mapeamento_exibicao)
            
            st.dataframe(
                df_exibicao,
                use_container_width=True,
                height=500
            )
        
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
            csv_original = df_original.to_csv(index=False)
            st.download_button(
                label="💾 Download Dados Originais (CSV)",
                data=csv_original,
                file_name=f"dados_originais_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
    
    with tab2:
        st.header("⚖️ Análise de Conformidade - Provimento 07/2021")
        st.markdown("**Verificação de cumprimento da obrigação mensal de envio de dados**")
        
        # Seletor de município para análise
        if 'municipio' in df_processado.columns:
            municipios_disponiveis = sorted(df_processado['municipio'].dropna().unique())
            
            col1, col2 = st.columns(2)
            
            with col1:
                municipio_analise = st.selectbox(
                    "🏙️ Selecione o município para análise detalhada:",
                    municipios_disponiveis,
                    key="municipio_conformidade"
                )
            
            with col2:
                st.info("📋 **Provimento 07/2021**: Obriga envio mensal até dia 10")
            
            if municipio_analise:
                # Realizar análise de conformidade
                analise_conformidade = analisar_conformidade_municipio(df_processado, municipio_analise)
                
                if analise_conformidade:
                    # Métricas de conformidade
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric(
                            "✅ Meses Informados", 
                            analise_conformidade['total_meses_informados']
                        )
                    
                    with col2:
                        st.metric(
                            "📅 Meses Esperados", 
                            analise_conformidade['total_meses_esperados']
                        )
                    
                    with col3:
                        st.metric(
                            "🔴 Meses Faltantes", 
                            analise_conformidade['total_meses_faltantes']
                        )
                    
                    with col4:
                        conformidade = analise_conformidade['conformidade_geral']
                        st.metric(
                            "📊 Conformidade", 
                            f"{conformidade:.1f}%",
                            f"{conformidade - 100:.1f}%" if conformidade < 100 else "✅"
                        )
                    
                    st.markdown("---")
                    
                    # Gráfico de conformidade
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("📊 Situação Geral")
                        dados_grafico = criar_grafico_conformidade(analise_conformidade)
                        chart_data = dados_grafico.set_index('Status')['Percentual']
                        st.bar_chart(chart_data)
                    
                    with col2:
                        st.subheader("📋 Análise por Ano")
                        dados_por_ano = []
                        for ano, dados in analise_conformidade['analise_por_ano'].items():
                            dados_por_ano.append({
                                'Ano': ano,
                                'Informados': dados['total_informado'],
                                'Faltantes': dados['total_faltante'],
                                'Conformidade (%)': f"{dados['percentual_conformidade']:.1f}%"
                            })
                        
                        if dados_por_ano:
                            df_anos = pd.DataFrame(dados_por_ano)
                            st.dataframe(df_anos, use_container_width=True)
                    
                    st.markdown("---")
                    
                    # Relatório executivo automático
                    st.subheader("📄 Relatório Executivo Automático")
                    relatorio_conformidade = gerar_relatorio_conformidade(analise_conformidade)
                    st.markdown(relatorio_conformidade)
                    
                    # Download do relatório de conformidade
                    st.download_button(
                        label="💾 Download Relatório de Conformidade",
                        data=relatorio_conformidade,
                        file_name=f"conformidade_{municipio_analise}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                        mime="text/plain"
                    )
                    
                    # Detalhamento por ano
                    if analise_conformidade['todos_meses_faltantes']:
                        st.subheader("🔍 Detalhamento de Pendências")
                        
                        for ano, dados in analise_conformidade['analise_por_ano'].items():
                            if dados['meses_faltantes']:
                                st.warning(f"**{ano}**: Faltam {len(dados['meses_faltantes'])} meses - {', '.join(dados['meses_faltantes_nomes'])}")
                            else:
                                st.success(f"**{ano}**: ✅ Todos os meses informados")
        
        else:
            st.warning("⚠️ Dados insuficientes para análise de conformidade")
    
    with tab3:
        st.header("📈 Análises Gráficas Interativas")
        criar_graficos_streamlit(df_filtrado)
    
    with tab4:
        st.header("🗺️ Análise Geográfica Detalhada")
        dados_geograficos = criar_resumo_geografico(df_filtrado)
    
    with tab5:
        st.header("📋 Relatório Executivo Completo")
        relatorio_texto = gerar_relatorio_completo(df_filtrado, estatisticas_limpeza)
        
        # Download do relatório
        st.download_button(
            label="💾 Download Relatório Executivo (TXT)",
            data=relatorio_texto,
            file_name=f"relatorio_executivo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain"
        )
    
    # ==================== RODAPÉ ====================
    st.markdown("---")
    cache_info = f"Cache Ativo: {len(st.session_state.dados_cache):,} registros" if st.session_state.cache_ativo else "Cache: Inativo"
    qualidade_dados = 100 - estatisticas_limpeza['percentual_removido']
    
    st.markdown(f"""
    <div style='text-align: center; color: gray; font-size: 12px; padding: 10px;'>
    🕒 <strong>Sistema Completo atualizado em:</strong> {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')} | 
    💾 <strong>{cache_info}</strong> | 
    📊 <strong>Qualidade:</strong> {qualidade_dados:.1f}% | 
    ⚖️ <strong>Conformidade + ACID</strong>
    </div>
    """, unsafe_allow_html=True)

# ==================== EXECUTAR APLICAÇÃO ====================
if __name__ == "__main__":
    main()
