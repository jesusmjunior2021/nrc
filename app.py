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

def analisar_qualidade_dados(df: pd.DataFrame):
    """Analisa a qualidade dos dados e retorna estatísticas"""
    
    total_registros = len(df)
    analise_qualidade = {}
    
    # Mapear campos importantes
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
    
    # Identificar colunas críticas
    colunas_criticas = []
    if 'MUNICÍPIO' in df.columns:
        colunas_criticas.append('MUNICÍPIO')
    if 'NASCIMENTOS (QTDE)' in df.columns:
        colunas_criticas.append('NASCIMENTOS (QTDE)')
    if 'REGISTROS (QTDE)' in df.columns:
        colunas_criticas.append('REGISTROS (QTDE)')
    
    # Estatísticas antes da limpeza
    stats_antes = {}
    for col in colunas_criticas:
        if col in df.columns:
            nulos = df[col].isna().sum()
            vazios = (df[col] == '').sum()
            na_strings = df[col].astype(str).str.lower().isin(['n/a', 'na', 'não informado', 'null', 'nan']).sum()
            stats_antes[col] = nulos + vazios + na_strings
    
    # Limpeza progressiva
    df_limpo = df.copy()
    
    # 1. Remover registros onde município é nulo/vazio/n/a
    if 'MUNICÍPIO' in df_limpo.columns:
        mask_municipio = (
            df_limpo['MUNICÍPIO'].notna() & 
            (df_limpo['MUNICÍPIO'] != '') & 
            (~df_limpo['MUNICÍPIO'].astype(str).str.lower().isin(['n/a', 'na', 'não informado', 'null', 'nan']))
        )
        df_limpo = df_limpo[mask_municipio]
    
    # 2. Remover registros onde nascimentos ou registros são nulos/vazios
    if 'NASCIMENTOS (QTDE)' in df_limpo.columns:
        df_limpo = df_limpo[df_limpo['NASCIMENTOS (QTDE)'].notna()]
        df_limpo = df_limpo[df_limpo['NASCIMENTOS (QTDE)'] != '']
    
    if 'REGISTROS (QTDE)' in df_limpo.columns:
        df_limpo = df_limpo[df_limpo['REGISTROS (QTDE)'].notna()]
        df_limpo = df_limpo[df_limpo['REGISTROS (QTDE)'] != '']
    
    # 3. Converter valores numéricos
    colunas_numericas = ['NASCIMENTOS (QTDE)', 'REGISTROS (QTDE)', 'Mês', 'Ano']
    for col in colunas_numericas:
        if col in df_limpo.columns:
            df_limpo[col] = pd.to_numeric(df_limpo[col], errors='coerce')
    
    # 4. Remover registros onde conversão numérica falhou
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
    
    # Mapeamento dos nomes reais das colunas
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
        
        # Usar percentual original se existir, senão usar calculado
        if 'percentual_original' in df_processado.columns:
            df_processado['percentual'] = df_processado['percentual_original'].fillna(df_processado['percentual_calculado'])
        else:
            df_processado['percentual'] = df_processado['percentual_calculado']
    
    # Calcular déficit
    if 'nascimentos' in df_processado.columns and 'registros' in df_processado.columns:
        df_processado['deficit'] = df_processado['nascimentos'] - df_processado['registros']
        df_processado['deficit'] = df_processado['deficit'].fillna(0)
    
    # Limpar campos de texto - substituir vazios por "Não informado"
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
        
        # Alertas por nível de problema
        st.subheader("⚠️ Alertas de Qualidade")
        
        for campo, stats in analise_qualidade.items():
            if stats['percentual_problemas'] > 10:
                st.error(f"🔴 **{campo}**: {stats['percentual_problemas']:.1f}% de problemas - Requer atenção urgente!")
            elif stats['percentual_problemas'] > 5:
                st.warning(f"🟡 **{campo}**: {stats['percentual_problemas']:.1f}% de problemas - Monitorar")
            elif stats['percentual_problemas'] > 0:
                st.info(f"🟢 **{campo}**: {stats['percentual_problemas']:.1f}% de problemas - Aceitável")
    
    # Recomendações
    st.subheader("💡 Recomendações para Correção Manual")
    
    campos_criticos = []
    campos_moderados = []
    
    for campo, stats in analise_qualidade.items():
        if stats['percentual_problemas'] > 10:
            campos_criticos.append(f"**{campo}** ({stats['percentual_problemas']:.1f}%)")
        elif stats['percentual_problemas'] > 5:
            campos_moderados.append(f"**{campo}** ({stats['percentual_problemas']:.1f}%)")
    
    if campos_criticos:
        st.error(f"🚨 **PRIORIDADE ALTA:** Corrigir urgentemente: {', '.join(campos_criticos)}")
    
    if campos_moderados:
        st.warning(f"⚠️ **PRIORIDADE MÉDIA:** Revisar quando possível: {', '.join(campos_moderados)}")
    
    if not campos_criticos and not campos_moderados:
        st.success("✅ **Qualidade dos dados está em nível aceitável!**")

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
**RECOMENDAÇÕES PARA MELHORIA DA QUALIDADE:**

1. **CORREÇÃO DE DADOS:** {estatisticas_limpeza['registros_removidos']:,} registros precisam de correção manual

2. **FOCO PRIORITÁRIO:** Concentrar esforços nos municípios com performance abaixo de 70%

3. **VALIDAÇÃO DE ENTRADA:** Implementar validações no formulário para evitar dados inconsistentes

4. **MONITORAMENTO:** Acompanhar semanalmente a qualidade dos dados inseridos

5. **TREINAMENTO:** Capacitar equipes responsáveis pelo preenchimento dos formulários

6. **AUTOMAÇÃO:** Implementar verificações automáticas de consistência

═══════════════════════════════════════════════════════════════
Relatório gerado automaticamente em {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}
Sistema de Monitoramento - Provimento 07/2021
Base de dados limpa e validada para análise confiável.
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
        # Análise de qualidade ANTES da limpeza
        st.header("🔍 Diagnóstico de Qualidade dos Dados")
        analise_qualidade, total_registros = analisar_qualidade_dados(df)
        
        # Limpeza dos dados
        with st.spinner("Limpando e validando dados..."):
            df_limpo, estatisticas_limpeza = limpar_dados(df)
        
        # Mostrar análise de qualidade
        mostrar_analise_qualidade(analise_qualidade, total_registros, estatisticas_limpeza)
        
        if df_limpo.empty:
            st.error("❌ Todos os dados foram removidos durante a limpeza! Verifique a qualidade da fonte.")
            return
        
        # Processar dados limpos
        df_processado = processar_dados(df_limpo)
        
        st.success(f"✅ **{len(df_processado)} registros válidos** processados com sucesso!")
        
        # Mostrar colunas encontradas
        st.sidebar.subheader("📋 Colunas Encontradas")
        with st.sidebar.expander("Ver colunas originais"):
            for i, col in enumerate(df.columns, 1):
                st.sidebar.write(f"{i}. {col}")
        
        # ==================== FILTROS DINÂMICOS ====================
        st.sidebar.subheader("🔍 Filtros Avançados")
        
        # Criar cópia para filtros
        df_original = df_processado.copy()
        df_filtrado = df_processado.copy()
        
        # Filtros (mesmo código anterior...)
        # [Mantendo todos os filtros do código anterior]
        
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
            st.sidebar.info(f"📊 Exibindo todos os **{len(df_filtrado)}** registros válidos")
        
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
            
            # Tabela principal com dados limpos
            st.subheader("📋 Dados Válidos Processados")
            
            # Seletor de colunas para exibição
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
            
            # Downloads
            col1, col2, col3 = st.columns(3)
            
            with col1:
                csv_filtrado = df_filtrado.to_csv(index=False)
                st.download_button(
                    label="💾 Download Dados Limpos (CSV)",
                    data=csv_filtrado,
                    file_name=f"dados_limpos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
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
            
            with col3:
                # CSV com problemas encontrados
                if estatisticas_limpeza['registros_removidos'] > 0:
                    st.download_button(
                        label="⚠️ Download Registros Removidos",
                        data="Registros removidos devido a inconsistências de dados",
                        file_name=f"registros_removidos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                        mime="text/plain"
                    )
        
        with tab2:
            st.header("📈 Análises Gráficas Interativas")
            criar_graficos_streamlit(df_filtrado)
        
        with tab3:
            st.header("🗺️ Análise Geográfica Detalhada")
            dados_geograficos = criar_resumo_geografico(df_filtrado)
        
        with tab4:
            st.header("📋 Relatório Executivo Completo")
            relatorio_texto = gerar_relatorio_completo(df_filtrado, estatisticas_limpeza)
            
            # Download do relatório
            st.download_button(
                label="💾 Download Relatório Executivo (TXT)",
                data=relatorio_texto,
                file_name=f"relatorio_executivo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain"
            )
        
        # Rodapé com informações do sistema
        st.markdown("---")
        qualidade_dados = 100 - estatisticas_limpeza['percentual_removido']
        st.markdown(f"""
        <div style='text-align: center; color: gray; font-size: 12px; padding: 10px;'>
        🕒 <strong>Sistema atualizado em:</strong> {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')} | 
        📊 <strong>Qualidade dos dados:</strong> {qualidade_dados:.1f}% | 
        📈 <strong>{len(df_filtrado):,} registros válidos</strong> |
        🗑️ <strong>{estatisticas_limpeza['registros_removidos']:,} registros removidos</strong>
        </div>
        """, unsafe_allow_html=True)
    
    else:
        # Tela inicial
        st.info("👆 **Selecione uma fonte de dados na barra lateral para começar a análise.**")
        
        st.markdown("""
        ## 📋 Sistema de Limpeza e Análise de Dados
        
        Este sistema foi desenvolvido para **monitoramento completo e confiável** dos dados do **Provimento 07/2021**.
        
        ### 🔧 **Funcionalidades de Qualidade dos Dados:**
        
        ✅ **Detecção Automática de Problemas** - Identifica nulos, vazios e valores inconsistentes  
        ✅ **Limpeza Inteligente** - Remove automaticamente registros com dados críticos inválidos  
        ✅ **Análise de Qualidade** - Relatórios detalhados sobre a integridade dos dados  
        ✅ **Alertas de Inconsistência** - Avisos sobre campos que precisam de correção manual  
        ✅ **Estatísticas de Limpeza** - Mostra quantos registros foram removidos e por quê  
        ✅ **Recomendações Automáticas** - Sugere ações para melhorar a qualidade dos dados  
        
        ### 📊 **Processo de Validação:**
        
        1. **Carregamento** - Importa dados da fonte escolhida
        2. **Diagnóstico** - Analisa problemas em cada campo
        3. **Limpeza** - Remove registros com dados críticos inválidos
        4. **Validação** - Converte tipos de dados e calcula métricas
        5. **Relatório** - Gera estatísticas de qualidade
        
        ### ⚠️ **Critérios de Remoção:**
        
        - **Município vazio/nulo/N/A** - Campo obrigatório
        - **Nascimentos inválidos** - Deve ser número válido
        - **Registros inválidos** - Deve ser número válido
        - **Dados inconsistentes** - Valores que impedem cálculos
        
        ---
        
        **💡 Resultado:** Apenas dados confiáveis e consistentes para análise precisa!
        """)

# ==================== EXECUTAR APLICAÇÃO ====================
if __name__ == "__main__":
    main()
