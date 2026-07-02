import streamlit as st
import pandas as pd
import requests
import io
from datetime import datetime
import base64
from typing import Optional
import time
import json
import calendar

# ==================== CONFIGURAÇÃO DA PÁGINA ====================
st.set_page_config(
    page_title="Provimento 07/2021 - Sistema Avançado Final",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== INICIALIZAÇÃO DO CACHE PERSISTENTE ====================
def inicializar_cache():
    """Inicializa o sistema de cache persistente otimizado"""
    if 'dados_cache' not in st.session_state:
        st.session_state.dados_cache = None
    if 'dados_originais_cache' not in st.session_state:
        st.session_state.dados_originais_cache = None
    if 'estatisticas_cache' not in st.session_state:
        st.session_state.estatisticas_cache = None
    if 'analise_qualidade_cache' not in st.session_state:
        st.session_state.analise_qualidade_cache = None
    if 'conformidade_cache' not in st.session_state:
        st.session_state.conformidade_cache = {}
    if 'timestamp_cache' not in st.session_state:
        st.session_state.timestamp_cache = None
    if 'cache_ativo' not in st.session_state:
        st.session_state.cache_ativo = False
    if 'filtros_aplicados' not in st.session_state:
        st.session_state.filtros_aplicados = {}

def salvar_no_cache(df_processado, df_original, estatisticas, analise_qualidade):
    """Salva dados no cache persistente com otimizações"""
    st.session_state.dados_cache = df_processado.copy()
    st.session_state.dados_originais_cache = df_original.copy() 
    st.session_state.estatisticas_cache = estatisticas.copy()
    st.session_state.analise_qualidade_cache = analise_qualidade.copy()
    st.session_state.conformidade_cache = {}  # Reset conformidade cache
    st.session_state.timestamp_cache = datetime.now()
    st.session_state.cache_ativo = True
    
    # Pré-calcular análises de conformidade para todos os municípios
    if 'municipio' in df_processado.columns:
        municipios = df_processado['municipio'].unique()
        st.session_state.conformidade_cache = {}
        for municipio in municipios:
            analise = analisar_conformidade_municipio(df_processado, municipio)
            if analise:
                st.session_state.conformidade_cache[municipio] = analise

def limpar_cache():
    """Limpa o cache quando solicitado"""
    st.session_state.dados_cache = None
    st.session_state.dados_originais_cache = None
    st.session_state.estatisticas_cache = None
    st.session_state.analise_qualidade_cache = None
    st.session_state.conformidade_cache = {}
    st.session_state.timestamp_cache = None
    st.session_state.cache_ativo = False
    st.session_state.filtros_aplicados = {}

# ==================== NORMALIZAÇÃO DE SCHEMA DA PLANILHA PÚBLICA ====================

# Na planilha publicada em CSV, a 1a coluna (Carimbo de data/hora) sai sem
# cabeçalho (o Google Sheets omite o nome quando a coluna é a chave do form).
# O pandas nomeia essa coluna automaticamente como "Unnamed: 0".
COLUNA_TIMESTAMP_PADRAO = 'Carimbo de data/hora'

MESES_PT = {
    'JANEIRO': 1, 'FEVEREIRO': 2, 'MARÇO': 3, 'MARCO': 3, 'ABRIL': 4,
    'MAIO': 5, 'JUNHO': 6, 'JULHO': 7, 'AGOSTO': 8,
    'SETEMBRO': 9, 'OUTUBRO': 10, 'NOVEMBRO': 11, 'DEZEMBRO': 12
}

def converter_mes(valor) -> Optional[int]:
    """Converte o campo 'Mês' (nome em português OU número) para 1-12.

    A planilha pública traz o mês como texto (ex.: 'JANEIRO'), não como
    número. Aceita também valores já numéricos para manter compatibilidade
    com exportações antigas."""
    if pd.isna(valor):
        return None
    texto = str(valor).strip().upper()
    if texto in MESES_PT:
        return MESES_PT[texto]
    try:
        numero = int(float(texto.replace(',', '.')))
        if 1 <= numero <= 12:
            return numero
    except (ValueError, TypeError):
        pass
    return None

def normalizar_planilha(df: pd.DataFrame) -> pd.DataFrame:
    """Corrige divergências de schema entre o CSV publicado no Google Sheets
    e os nomes de coluna que o restante do app espera."""
    df = df.copy()

    # 1) Renomear a 1a coluna (timestamp) quando ela vier sem nome
    primeira_coluna = df.columns[0]
    if primeira_coluna != COLUNA_TIMESTAMP_PADRAO and (
        str(primeira_coluna).strip() == '' or str(primeira_coluna).startswith('Unnamed')
    ):
        df = df.rename(columns={primeira_coluna: COLUNA_TIMESTAMP_PADRAO})

    # 2) A coluna de percentual pronto vem como "%" na planilha pública
    #    (o app internamente procura por "% Ok.")
    if '%' in df.columns and '% Ok.' not in df.columns:
        df = df.rename(columns={'%': '% Ok.'})

    # 3) Remover colunas fantasma totalmente vazias (ex.: "Unnamed: 10")
    for col in list(df.columns):
        if str(col).startswith('Unnamed') and col != COLUNA_TIMESTAMP_PADRAO and df[col].isna().all():
            df = df.drop(columns=[col])

    # 4) Remover marcas invisíveis (LRM/RLM) e espaços extras que o Google
    #    Forms injeta em nomes de município/serventia (ex.: "Açailândia\u200e")
    #    e que quebram agrupamentos (2 chaves distintas para o mesmo município)
    campos_texto = ['MUNICÍPIO', 'Nome da Serventia', 'Posto/Unidade Interligada']
    for col in campos_texto:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace('\u200e', '', regex=False)
                .str.replace('\u200f', '', regex=False)
                .str.strip()
            )
            df[col] = df[col].replace('nan', pd.NA)

    return df

# ==================== FUNÇÕES DE CARREGAMENTO ====================

@st.cache_data(ttl=300)
def carregar_dados_url(url: str) -> Optional[pd.DataFrame]:
    """Carrega dados de uma URL CSV"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        df = normalizar_planilha(df)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar dados da URL: {str(e)}")
        return None

@st.cache_data
def carregar_dados_arquivo(arquivo) -> Optional[pd.DataFrame]:
    """Carrega dados de um arquivo enviado"""
    try:
        df = pd.read_csv(arquivo)
        df = normalizar_planilha(df)
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
    colunas_numericas = ['NASCIMENTOS (QTDE)', 'REGISTROS (QTDE)', 'Ano']
    for col in colunas_numericas:
        if col in df_limpo.columns:
            df_limpo[col] = pd.to_numeric(df_limpo[col], errors='coerce')

    # "Mês" vem como nome em português (JANEIRO, FEVEREIRO...) na planilha
    # pública, não como número — usar conversor dedicado em vez de to_numeric
    if 'Mês' in df_limpo.columns:
        df_limpo['Mês'] = df_limpo['Mês'].apply(converter_mes)
    
    # Remover onde conversão falhou
    if 'NASCIMENTOS (QTDE)' in df_limpo.columns:
        df_limpo = df_limpo[df_limpo['NASCIMENTOS (QTDE)'].notna()]
    if 'REGISTROS (QTDE)' in df_limpo.columns:
        df_limpo = df_limpo[df_limpo['REGISTROS (QTDE)'].notna()]
    if 'Mês' in df_limpo.columns:
        df_limpo = df_limpo[df_limpo['Mês'].notna()]
        df_limpo['Mês'] = df_limpo['Mês'].astype(int)
    
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
        df_processado['timestamp'] = pd.to_datetime(df_processado['timestamp'], errors='coerce', dayfirst=True)
        df_processado['ano_timestamp'] = df_processado['timestamp'].dt.year
        df_processado['mes_timestamp'] = df_processado['timestamp'].dt.month
        df_processado['data_formatada'] = df_processado['timestamp'].dt.strftime('%d/%m/%Y %H:%M')

    # A coluna "Ano" do formulário fica em branco em algumas respostas
    # (~1% dos registros) — usar o ano do carimbo de data/hora como fallback
    if 'ano' in df_processado.columns and 'ano_timestamp' in df_processado.columns:
        df_processado['ano'] = pd.to_numeric(df_processado['ano'], errors='coerce')
        df_processado['ano'] = df_processado['ano'].fillna(df_processado['ano_timestamp'])
        df_processado['ano'] = df_processado['ano'].astype('Int64')

    if 'mes' in df_processado.columns:
        df_processado['mes'] = pd.to_numeric(df_processado['mes'], errors='coerce').astype('Int64')
    
    # Calcular percentual
    if 'nascimentos' in df_processado.columns and 'registros' in df_processado.columns:
        df_processado['percentual_calculado'] = (
            (df_processado['registros'] / df_processado['nascimentos']) * 100
        ).round(2)
        df_processado['percentual_calculado'] = df_processado['percentual_calculado'].fillna(0)
        df_processado['percentual_calculado'] = df_processado['percentual_calculado'].clip(upper=100)
        
        if 'percentual_original' in df_processado.columns:
            # A planilha traz o percentual pronto como texto BR (ex.: "62,07%"),
            # não como número — sem essa conversão a coluna 'percentual' fica
            # com tipo misto (str + float) e qualquer .min()/.max()/.mean()
            # quebra com TypeError
            df_processado['percentual_original'] = (
                df_processado['percentual_original']
                .astype(str)
                .str.replace('%', '', regex=False)
                .str.replace(',', '.', regex=False)
                .str.strip()
            )
            df_processado['percentual_original'] = pd.to_numeric(
                df_processado['percentual_original'], errors='coerce'
            )
            df_processado['percentual'] = df_processado['percentual_original'].fillna(df_processado['percentual_calculado'])
        else:
            df_processado['percentual'] = df_processado['percentual_calculado']
        df_processado['percentual'] = pd.to_numeric(df_processado['percentual'], errors='coerce').fillna(0)
    
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
    with st.expander("📋 Detalhamento de Problemas por Campo", expanded=False):
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

# ==================== ANÁLISE DE CONFORMIDADE MELHORADA ====================

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
        
        # Para o ano atual, considerar apenas meses até o mês atual
        ano_atual = datetime.now().year
        mes_atual = datetime.now().month
        
        if ano == ano_atual:
            meses_esperados = list(range(1, mes_atual + 1))
        else:
            meses_esperados = list(range(1, 13))  # 1 a 12
        
        meses_faltantes = [mes for mes in meses_esperados if mes not in meses_informados]
        
        # Calcular estatísticas
        total_esperado = len(meses_esperados)
        total_informado = len(meses_informados)
        total_faltante = len(meses_faltantes)
        percentual_conformidade = (total_informado / total_esperado) * 100 if total_esperado > 0 else 0
        percentual_defasagem = (total_faltante / total_esperado) * 100 if total_esperado > 0 else 0
        
        # Converter números de meses para nomes
        nomes_meses = {
            1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
            5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
            9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
        }
        
        meses_faltantes_nomes = [f"{nomes_meses[mes]}/{ano}" for mes in meses_faltantes]
        meses_informados_nomes = [f"{nomes_meses[mes]}/{ano}" for mes in meses_informados]
        
        # Calcular totais do ano
        total_nascimentos_ano = dados_ano['nascimentos'].sum()
        total_registros_ano = dados_ano['registros'].sum()
        deficit_ano = total_nascimentos_ano - total_registros_ano
        
        analise_conformidade[ano] = {
            'total_esperado': total_esperado,
            'total_informado': total_informado,
            'total_faltante': total_faltante,
            'percentual_conformidade': percentual_conformidade,
            'percentual_defasagem': percentual_defasagem,
            'meses_informados': meses_informados,
            'meses_faltantes': meses_faltantes,
            'meses_informados_nomes': meses_informados_nomes,
            'meses_faltantes_nomes': meses_faltantes_nomes,
            'total_nascimentos': total_nascimentos_ano,
            'total_registros': total_registros_ano,
            'deficit': deficit_ano
        }
    
    # Calcular totais gerais
    total_meses_esperados = sum([dados['total_esperado'] for dados in analise_conformidade.values()])
    total_meses_informados = sum([dados['total_informado'] for dados in analise_conformidade.values()])
    total_meses_faltantes = total_meses_esperados - total_meses_informados
    
    conformidade_geral = (total_meses_informados / total_meses_esperados) * 100 if total_meses_esperados > 0 else 0
    defasagem_geral = (total_meses_faltantes / total_meses_esperados) * 100 if total_meses_esperados > 0 else 0
    
    # Todos os meses faltantes
    todos_meses_faltantes = []
    for ano_dados in analise_conformidade.values():
        todos_meses_faltantes.extend(ano_dados['meses_faltantes_nomes'])
    
    # Totais gerais de nascimentos e registros
    total_nascimentos_geral = sum([dados['total_nascimentos'] for dados in analise_conformidade.values()])
    total_registros_geral = sum([dados['total_registros'] for dados in analise_conformidade.values()])
    deficit_geral = total_nascimentos_geral - total_registros_geral
    
    resultado = {
        'municipio': municipio,
        'anos_analisados': anos_disponiveis,
        'analise_por_ano': analise_conformidade,
        'total_meses_esperados': total_meses_esperados,
        'total_meses_informados': total_meses_informados,
        'total_meses_faltantes': total_meses_faltantes,
        'conformidade_geral': conformidade_geral,
        'defasagem_geral': defasagem_geral,
        'todos_meses_faltantes': todos_meses_faltantes,
        'total_nascimentos_geral': total_nascimentos_geral,
        'total_registros_geral': total_registros_geral,
        'deficit_geral': deficit_geral
    }
    
    return resultado

def gerar_relatorio_conformidade(analise: dict):
    """Gera relatório executivo de conformidade para um município"""
    
    municipio = analise['municipio']
    conformidade = analise['conformidade_geral']
    defasagem = analise['defasagem_geral']
    meses_faltantes = analise['todos_meses_faltantes']
    total_nascimentos = analise['total_nascimentos_geral']
    total_registros = analise['total_registros_geral']
    deficit = analise['deficit_geral']
    
    if not meses_faltantes:
        relatorio = f"""
**📋 RELATÓRIO DE CONFORMIDADE - PROVIMENTO 07/2021**

✅ **A unidade {municipio} está em CONFORMIDADE TOTAL!**

• Todos os meses foram informados conforme exigido
• Percentual de Conformidade: {conformidade:.1f}%
• Status: EM DIA com as obrigações
• Total de Nascimentos: {total_nascimentos:,}
• Total de Registros: {total_registros:,}
• Percentual de Cobertura: {(total_registros/total_nascimentos*100):.1f}%

**Parabéns! Esta unidade está cumprindo integralmente o Provimento 07/2021.**
        """
    else:
        urgencia = "ALTA - Mais de 6 meses em atraso" if len(meses_faltantes) > 6 else "MÉDIA - Entre 3 e 6 meses em atraso" if len(meses_faltantes) > 3 else "BAIXA - Poucos meses em atraso"
        
        relatorio = f"""
**📋 RELATÓRIO DE CONFORMIDADE - PROVIMENTO 07/2021**

⚠️ **A unidade {municipio} possui PENDÊNCIAS!**

**RESUMO EXECUTIVO:**
• Percentual de Conformidade: {conformidade:.1f}%
• Percentual de Defasagem: {defasagem:.1f}%
• Total de meses em débito: {len(meses_faltantes)}
• Total de Nascimentos: {total_nascimentos:,}
• Total de Registros: {total_registros:,}
• Déficit de Registros: {deficit:,}
• Percentual de Cobertura: {(total_registros/total_nascimentos*100):.1f}%

**🔴 MESES EM DÉBITO:**
{chr(10).join([f"• {mes}" for mes in meses_faltantes])}

**📝 AÇÃO NECESSÁRIA:**
A unidade deve regularizar os envios em atraso conforme determina o Provimento 07/2021, 
que obriga o envio mensal até o dia 10 de cada mês das informações sobre nascimentos e registros.

**⚡ URGÊNCIA:** {urgencia}

**📞 RECOMENDAÇÃO:**
Contatar imediatamente a unidade para regularização dos meses pendentes e 
implementação de procedimentos para garantir cumprimento futuro.
        """
    
    return relatorio

def analisar_conformidade_geral(df: pd.DataFrame):
    """Analisa conformidade geral de todos os municípios"""
    
    if 'municipio' not in df.columns:
        return None
    
    municipios = df['municipio'].unique()
    analise_geral = []
    
    for municipio in municipios:
        if municipio in st.session_state.conformidade_cache:
            analise = st.session_state.conformidade_cache[municipio]
        else:
            analise = analisar_conformidade_municipio(df, municipio)
            if analise:
                st.session_state.conformidade_cache[municipio] = analise
        
        if analise:
            analise_geral.append({
                'Município': municipio,
                'Conformidade (%)': analise['conformidade_geral'],
                'Meses Informados': analise['total_meses_informados'],
                'Meses Faltantes': analise['total_meses_faltantes'],
                'Status': '🟢 Conforme' if analise['conformidade_geral'] >= 90 
                         else '🟡 Atenção' if analise['conformidade_geral'] >= 70 
                         else '🔴 Crítico',
                'Nascimentos': analise['total_nascimentos_geral'],
                'Registros': analise['total_registros_geral'],
                'Déficit': analise['deficit_geral']
            })
    
    if analise_geral:
        return pd.DataFrame(analise_geral).sort_values('Conformidade (%)', ascending=False)
    
    return None

# ==================== GRÁFICOS INTERATIVOS MELHORADOS ====================

def criar_graficos_avancados(df: pd.DataFrame):
    """Cria gráficos interativos avançados com dados do cache"""
    
    st.subheader("📊 Centro de Análise Gráfica Avançada")
    
    # Configurações principais
    col1, col2, col3 = st.columns(3)
    
    with col1:
        tipo_analise = st.selectbox(
            "🎯 Tipo de Análise:",
            [
                "Nascimentos vs Registros",
                "Evolução Temporal",
                "Análise de Percentuais",
                "Déficit por Região",
                "Comparativo de Performance",
                "Análise de Tendências",
                "Distribuição Estatística",
                "Análise de Conformidade Visual"
            ]
        )
    
    with col2:
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
        
        agrupamento = st.selectbox("📋 Agrupar por:", opcoes_agrupamento)
    
    with col3:
        limite_registros = st.slider("📊 Quantidade no gráfico:", 5, 100, 25)
    
    # Mapear seleção para coluna
    mapa_colunas = {
        'Município': 'municipio',
        'Serventia': 'serventia', 
        'Posto/Unidade': 'posto_unidade',
        'Ano': 'ano',
        'Mês': 'mes'
    }
    
    coluna_agrupamento = mapa_colunas.get(agrupamento, 'municipio')
    
    st.markdown("---")
    
    # Gráficos específicos
    if tipo_analise == "Nascimentos vs Registros":
        criar_grafico_nascimentos_registros(df, coluna_agrupamento, limite_registros)
    
    elif tipo_analise == "Evolução Temporal":
        criar_grafico_evolucao_temporal(df)
    
    elif tipo_analise == "Análise de Percentuais":
        criar_grafico_percentuais(df, coluna_agrupamento, limite_registros)
    
    elif tipo_analise == "Déficit por Região":
        criar_grafico_deficit(df, coluna_agrupamento, limite_registros)
    
    elif tipo_analise == "Comparativo de Performance":
        criar_grafico_comparativo_performance(df, coluna_agrupamento, limite_registros)
    
    elif tipo_analise == "Análise de Tendências":
        criar_grafico_tendencias(df)
    
    elif tipo_analise == "Distribuição Estatística":
        criar_grafico_distribuicao(df, coluna_agrupamento)
    
    elif tipo_analise == "Análise de Conformidade Visual":
        criar_grafico_conformidade_visual(df)

def criar_grafico_nascimentos_registros(df, coluna_agrupamento, limite):
    """Gráfico de nascimentos vs registros"""
    
    if all(col in df.columns for col in [coluna_agrupamento, 'nascimentos', 'registros']):
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 Nascimentos vs Registros")
            
            dados_agrupados = df.groupby(coluna_agrupamento).agg({
                'nascimentos': 'sum',
                'registros': 'sum'
            }).reset_index()
            
            dados_agrupados = dados_agrupados.nlargest(limite, 'nascimentos')
            chart_data = dados_agrupados.set_index(coluna_agrupamento)[['nascimentos', 'registros']]
            st.bar_chart(chart_data)
        
        with col2:
            st.subheader("📈 Gap de Registros")
            
            dados_agrupados['gap'] = dados_agrupados['nascimentos'] - dados_agrupados['registros']
            dados_agrupados['percentual'] = (dados_agrupados['registros'] / dados_agrupados['nascimentos'] * 100).round(1)
            
            chart_gap = dados_agrupados.set_index(coluna_agrupamento)['gap']
            st.bar_chart(chart_gap)
        
        # Tabela de dados detalhada
        st.subheader("📋 Dados Detalhados")
        dados_agrupados_display = dados_agrupados.copy()
        dados_agrupados_display.columns = [
            coluna_agrupamento.title(), 
            'Nascimentos', 'Registros', 
            'Gap (Déficit)', 'Percentual (%)'
        ]
        st.dataframe(dados_agrupados_display, use_container_width=True)

def criar_grafico_evolucao_temporal(df):
    """Gráfico de evolução temporal"""
    
    if all(col in df.columns for col in ['ano', 'mes', 'registros', 'nascimentos']):
        
        # Opções de visualização temporal
        col1, col2 = st.columns(2)
        
        with col1:
            modo_temporal = st.selectbox(
                "Modo de Visualização:",
                ["Mensal", "Anual", "Trimestral"]
            )
        
        with col2:
            metricas_temporais = st.multiselect(
                "Métricas a exibir:",
                ["Nascimentos", "Registros", "Percentual", "Déficit"],
                default=["Nascimentos", "Registros"]
            )
        
        if modo_temporal == "Mensal":
            df_temporal = df.groupby(['ano', 'mes']).agg({
                'registros': 'sum',
                'nascimentos': 'sum'
            }).reset_index()
            
            df_temporal['periodo'] = df_temporal['ano'].astype(str) + '-' + df_temporal['mes'].astype(str).str.zfill(2)
            df_temporal = df_temporal.sort_values(['ano', 'mes'])
            
        elif modo_temporal == "Anual":
            df_temporal = df.groupby('ano').agg({
                'registros': 'sum',
                'nascimentos': 'sum'
            }).reset_index()
            df_temporal['periodo'] = df_temporal['ano'].astype(str)
            
        else:  # Trimestral
            df_temporal = df.copy()
            df_temporal['trimestre'] = ((df_temporal['mes'] - 1) // 3) + 1
            df_temporal = df_temporal.groupby(['ano', 'trimestre']).agg({
                'registros': 'sum',
                'nascimentos': 'sum'
            }).reset_index()
            df_temporal['periodo'] = df_temporal['ano'].astype(str) + '-T' + df_temporal['trimestre'].astype(str)
        
        # Calcular métricas adicionais
        df_temporal['percentual'] = (df_temporal['registros'] / df_temporal['nascimentos'] * 100).round(1)
        df_temporal['deficit'] = df_temporal['nascimentos'] - df_temporal['registros']
        
        # Criar gráfico baseado nas métricas selecionadas
        colunas_grafico = []
        if "Nascimentos" in metricas_temporais:
            colunas_grafico.append('nascimentos')
        if "Registros" in metricas_temporais:
            colunas_grafico.append('registros')
        if "Déficit" in metricas_temporais:
            colunas_grafico.append('deficit')
        
        if colunas_grafico:
            st.subheader(f"📈 Evolução {modo_temporal}")
            chart_temporal = df_temporal.set_index('periodo')[colunas_grafico]
            st.line_chart(chart_temporal)
        
        if "Percentual" in metricas_temporais:
            st.subheader("📊 Evolução do Percentual de Cobertura")
            chart_percentual = df_temporal.set_index('periodo')['percentual']
            st.line_chart(chart_percentual)
        
        # Tabela de dados temporais
        st.subheader("📋 Dados Temporais")
        st.dataframe(df_temporal, use_container_width=True)

def criar_grafico_percentuais(df, coluna_agrupamento, limite):
    """Análise de percentuais"""
    
    if all(col in df.columns for col in [coluna_agrupamento, 'percentual']):
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 Ranking de Percentuais")
            
            dados_percentual = df.groupby(coluna_agrupamento)['percentual'].mean().reset_index()
            dados_percentual = dados_percentual.sort_values('percentual', ascending=False).head(limite)
            
            chart_percentual = dados_percentual.set_index(coluna_agrupamento)['percentual']
            st.bar_chart(chart_percentual)
        
        with col2:
            st.subheader("📈 Distribuição de Performance")
            
            # Criar faixas de performance
            df_performance = df.copy()
            df_performance['faixa_performance'] = pd.cut(
                df_performance['percentual'], 
                bins=[0, 50, 70, 85, 95, 100],
                labels=['Crítico (0-50%)', 'Baixo (50-70%)', 'Médio (70-85%)', 'Bom (85-95%)', 'Excelente (95-100%)']
            )
            
            distribuicao = df_performance['faixa_performance'].value_counts()
            st.bar_chart(distribuicao)
        
        # Estatísticas descritivas
        st.subheader("📊 Estatísticas Descritivas")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Média", f"{df['percentual'].mean():.1f}%")
        with col2:
            st.metric("Mediana", f"{df['percentual'].median():.1f}%")
        with col3:
            st.metric("Desvio Padrão", f"{df['percentual'].std():.1f}")
        with col4:
            st.metric("Coef. Variação", f"{(df['percentual'].std()/df['percentual'].mean()*100):.1f}%")

def criar_grafico_deficit(df, coluna_agrupamento, limite):
    """Análise de déficit"""
    
    if all(col in df.columns for col in [coluna_agrupamento, 'deficit']):
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("⚠️ Maiores Déficits")
            
            dados_deficit = df.groupby(coluna_agrupamento)['deficit'].sum().reset_index()
            dados_deficit = dados_deficit.sort_values('deficit', ascending=False).head(limite)
            
            chart_deficit = dados_deficit.set_index(coluna_agrupamento)['deficit']
            st.bar_chart(chart_deficit)
        
        with col2:
            st.subheader("📊 Déficit vs Nascimentos")
            
            dados_comparativo = df.groupby(coluna_agrupamento).agg({
                'deficit': 'sum',
                'nascimentos': 'sum'
            }).reset_index()
            
            dados_comparativo['percentual_deficit'] = (dados_comparativo['deficit'] / dados_comparativo['nascimentos'] * 100).round(1)
            dados_comparativo = dados_comparativo.sort_values('percentual_deficit', ascending=False).head(limite)
            
            chart_perc_deficit = dados_comparativo.set_index(coluna_agrupamento)['percentual_deficit']
            st.bar_chart(chart_perc_deficit)

def criar_grafico_comparativo_performance(df, coluna_agrupamento, limite):
    """Gráfico comparativo de performance"""
    
    if all(col in df.columns for col in [coluna_agrupamento, 'nascimentos', 'registros', 'percentual']):
        
        dados_performance = df.groupby(coluna_agrupamento).agg({
            'nascimentos': 'sum',
            'registros': 'sum',
            'percentual': 'mean'
        }).reset_index()
        
        dados_performance = dados_performance.sort_values('percentual', ascending=False).head(limite)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🏆 Top Performers")
            top_performers = dados_performance.head(10)
            chart_top = top_performers.set_index(coluna_agrupamento)['percentual']
            st.bar_chart(chart_top)
        
        with col2:
            st.subheader("⚠️ Necessitam Atenção")
            bottom_performers = dados_performance.tail(10)
            chart_bottom = bottom_performers.set_index(coluna_agrupamento)['percentual']
            st.bar_chart(chart_bottom)

def criar_grafico_tendencias(df):
    """Análise de tendências"""
    
    if all(col in df.columns for col in ['ano', 'mes', 'percentual']):
        
        # Calcular tendência mensal
        df_tendencia = df.groupby(['ano', 'mes']).agg({
            'percentual': 'mean',
            'nascimentos': 'sum',
            'registros': 'sum'
        }).reset_index()
        
        df_tendencia['periodo'] = df_tendencia['ano'].astype(str) + '-' + df_tendencia['mes'].astype(str).str.zfill(2)
        df_tendencia = df_tendencia.sort_values(['ano', 'mes'])
        
        # Calcular média móvel
        df_tendencia['media_movel_3'] = df_tendencia['percentual'].rolling(window=3).mean()
        df_tendencia['media_movel_6'] = df_tendencia['percentual'].rolling(window=6).mean()
        
        st.subheader("📈 Análise de Tendências")
        
        col1, col2 = st.columns(2)
        
        with col1:
            chart_tendencia = df_tendencia.set_index('periodo')[['percentual', 'media_movel_3', 'media_movel_6']]
            st.line_chart(chart_tendencia)
        
        with col2:
            # Análise de sazonalidade
            df_sazonalidade = df.groupby('mes')['percentual'].mean().reset_index()
            chart_sazonalidade = df_sazonalidade.set_index('mes')['percentual']
            st.bar_chart(chart_sazonalidade)

def criar_grafico_distribuicao(df, coluna_agrupamento):
    """Análise de distribuição estatística"""
    
    if 'percentual' in df.columns:
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 Histograma de Percentuais")
            
            # Criar bins para histograma
            bins = range(0, 101, 10)
            df_hist = df.copy()
            df_hist['faixa'] = pd.cut(df_hist['percentual'], bins=bins)
            hist_data = df_hist['faixa'].value_counts().sort_index()
            
            st.bar_chart(hist_data)
        
        with col2:
            st.subheader("📈 Box Plot Simplificado")
            
            # Estatísticas para box plot
            q1 = df['percentual'].quantile(0.25)
            q2 = df['percentual'].quantile(0.50)  # mediana
            q3 = df['percentual'].quantile(0.75)
            
            dados_box = pd.DataFrame({
                'Estatística': ['Q1 (25%)', 'Q2 (50%)', 'Q3 (75%)'],
                'Valor': [q1, q2, q3]
            })
            
            chart_box = dados_box.set_index('Estatística')['Valor']
            st.bar_chart(chart_box)

def criar_grafico_conformidade_visual(df):
    """Análise visual de conformidade"""
    
    if st.session_state.conformidade_cache:
        
        st.subheader("⚖️ Dashboard de Conformidade Visual")
        
        # Criar dados de conformidade geral
        dados_conformidade = []
        
        for municipio, analise in st.session_state.conformidade_cache.items():
            dados_conformidade.append({
                'Município': municipio,
                'Conformidade': analise['conformidade_geral'],
                'Meses_Faltantes': analise['total_meses_faltantes']
            })
        
        if dados_conformidade:
            df_conformidade = pd.DataFrame(dados_conformidade)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("📊 Ranking de Conformidade")
                df_conf_ranking = df_conformidade.sort_values('Conformidade', ascending=False).head(20)
                chart_ranking = df_conf_ranking.set_index('Município')['Conformidade']
                st.bar_chart(chart_ranking)
            
            with col2:
                st.subheader("⚠️ Municípios com Mais Pendências")
                df_pendencias = df_conformidade.sort_values('Meses_Faltantes', ascending=False).head(20)
                chart_pendencias = df_pendencias.set_index('Município')['Meses_Faltantes']
                st.bar_chart(chart_pendencias)
            
            # Distribuição de conformidade
            st.subheader("📈 Distribuição de Conformidade")
            
            # Criar faixas de conformidade
            df_conformidade['Faixa'] = pd.cut(
                df_conformidade['Conformidade'],
                bins=[0, 50, 70, 85, 95, 100],
                labels=['Crítico', 'Baixo', 'Médio', 'Bom', 'Excelente']
            )
            
            distribuicao_conf = df_conformidade['Faixa'].value_counts()
            st.bar_chart(distribuicao_conf)

# ==================== ANÁLISE GEOGRÁFICA ====================

def criar_resumo_geografico(df: pd.DataFrame):
    """Cria resumo geográfico completo"""
    
    if 'municipio' in df.columns:
        st.subheader("🗺️ Análise Geográfica Completa")
        
        # Agrupar dados por município com TODOS os campos
        dados_municipios = df.groupby('municipio').agg({
            'nascimentos': 'sum',
            'registros': 'sum',
            'percentual': 'mean',
            'deficit': 'sum',
            'serventia': 'nunique',
            'posto_unidade': 'nunique'
        }).round(2).reset_index()
        
        # Adicionar análise de conformidade se disponível
        if st.session_state.conformidade_cache:
            conformidade_dados = []
            for municipio in dados_municipios['municipio']:
                if municipio in st.session_state.conformidade_cache:
                    conf = st.session_state.conformidade_cache[municipio]['conformidade_geral']
                    conformidade_dados.append(conf)
                else:
                    conformidade_dados.append(0)
            
            dados_municipios['Conformidade (%)'] = conformidade_dados
        
        # Renomear colunas para melhor visualização
        dados_municipios.columns = [
            'Município', 'Total Nascimentos', 'Total Registros', 
            'Percentual Médio', 'Déficit Total', 'Nº Serventias', 'Nº Postos/Unidades'
        ] + (['Conformidade (%)'] if 'Conformidade (%)' in dados_municipios.columns else [])
        
        # Adicionar classificação de performance
        dados_municipios['Status Performance'] = dados_municipios['Percentual Médio'].apply(
            lambda x: '🟢 Excelente' if x >= 90 
                     else '🟡 Bom' if x >= 70 
                     else '🔴 Atenção'
        )
        
        # Adicionar classificação de conformidade se disponível
        if 'Conformidade (%)' in dados_municipios.columns:
            dados_municipios['Status Conformidade'] = dados_municipios['Conformidade (%)'].apply(
                lambda x: '🟢 Conforme' if x >= 90 
                         else '🟡 Atenção' if x >= 70 
                         else '🔴 Crítico'
            )
        
        # Ordenar por múltiplos critérios
        col1, col2 = st.columns(2)
        
        with col1:
            criterio_ordem = st.selectbox(
                "Ordenar por:",
                ["Percentual Médio", "Total Nascimentos", "Déficit Total"] + 
                (["Conformidade (%)"] if 'Conformidade (%)' in dados_municipios.columns else [])
            )
        
        with col2:
            ordem_crescente = st.checkbox("Ordem crescente", value=False)
        
        dados_municipios = dados_municipios.sort_values(criterio_ordem, ascending=ordem_crescente)
        
        # Filtros para a tabela geográfica
        col1, col2, col3 = st.columns(3)
        
        with col1:
            status_filtro = st.selectbox(
                "Filtrar por Status Performance:",
                ['Todos', '🟢 Excelente', '🟡 Bom', '🔴 Atenção']
            )
        
        with col2:
            if 'Status Conformidade' in dados_municipios.columns:
                status_conf_filtro = st.selectbox(
                    "Filtrar por Status Conformidade:",
                    ['Todos', '🟢 Conforme', '🟡 Atenção', '🔴 Crítico']
                )
            else:
                status_conf_filtro = 'Todos'
        
        with col3:
            limite_municipios = st.slider("Mostrar quantos municípios:", 10, len(dados_municipios), min(50, len(dados_municipios)))
        
        # Aplicar filtros
        dados_filtrados = dados_municipios.copy()
        
        if status_filtro != 'Todos':
            dados_filtrados = dados_filtrados[dados_filtrados['Status Performance'] == status_filtro]
        
        if status_conf_filtro != 'Todos' and 'Status Conformidade' in dados_filtrados.columns:
            dados_filtrados = dados_filtrados[dados_filtrados['Status Conformidade'] == status_conf_filtro]
        
        dados_filtrados = dados_filtrados.head(limite_municipios)
        
        # Exibir tabela com formatação
        st.dataframe(
            dados_filtrados,
            use_container_width=True,
            height=500
        )
        
        # Estatísticas resumidas
        colunas_metricas = 5 if 'Conformidade (%)' in dados_municipios.columns else 4
        cols = st.columns(colunas_metricas)
        
        with cols[0]:
            excelentes = len(dados_municipios[dados_municipios['Percentual Médio'] >= 90])
            st.metric("🟢 Performance Excelente", f"{excelentes}")
        
        with cols[1]:
            bons = len(dados_municipios[(dados_municipios['Percentual Médio'] >= 70) & (dados_municipios['Percentual Médio'] < 90)])
            st.metric("🟡 Performance Boa", f"{bons}")
        
        with cols[2]:
            atencao = len(dados_municipios[dados_municipios['Percentual Médio'] < 70])
            st.metric("🔴 Precisam Atenção", f"{atencao}")
        
        with cols[3]:
            deficit_total = dados_municipios['Déficit Total'].sum()
            st.metric("⚠️ Déficit Total", f"{deficit_total:,.0f}")
        
        if 'Conformidade (%)' in dados_municipios.columns:
            with cols[4]:
                conformes = len(dados_municipios[dados_municipios['Conformidade (%)'] >= 90])
                st.metric("✅ Conformes", f"{conformes}")
        
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
    
    # Análise de conformidade geral
    conformidade_geral = None
    if st.session_state.conformidade_cache:
        conformidades = [analise['conformidade_geral'] for analise in st.session_state.conformidade_cache.values()]
        if conformidades:
            conformidade_geral = sum(conformidades) / len(conformidades)
    
    relatorio = f"""
**RELATÓRIO EXECUTIVO COMPLETO - PROVIMENTO 07/2021**
**Sistema de Monitoramento Avançado de Registros de Nascimentos**

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

**CONFORMIDADE PROVIMENTO 07/2021:**"""
    
    if conformidade_geral is not None:
        relatorio += f"""
• Conformidade Média Geral: {conformidade_geral:.1f}%
• Municípios Analisados: {len(st.session_state.conformidade_cache)}
• Status Geral: {'🟢 CONFORME' if conformidade_geral >= 90 else '🟡 ATENÇÃO' if conformidade_geral >= 70 else '🔴 CRÍTICO'}"""
    else:
        relatorio += f"""
• Status: Análise de conformidade não disponível"""
    
    relatorio += f"""

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
            relatorio += f"\n\n**MUNICÍPIOS QUE PRECISAM DE ATENÇÃO URGENTE:**"
            bottom10 = dados_municipios.nsmallest(min(10, atencao))
            for i, (municipio, perc) in enumerate(bottom10.items(), 1):
                relatorio += f"\n{i:2d}. {municipio}: {perc:.1f}%"
    
    # Análise de conformidade detalhada
    if st.session_state.conformidade_cache:
        municipios_criticos = []
        for municipio, analise in st.session_state.conformidade_cache.items():
            if analise['conformidade_geral'] < 70:
                municipios_criticos.append((municipio, analise['conformidade_geral'], len(analise['todos_meses_faltantes'])))
        
        if municipios_criticos:
            relatorio += f"\n\n**MUNICÍPIOS COM CONFORMIDADE CRÍTICA (<70%):**"
            municipios_criticos.sort(key=lambda x: x[1])  # Ordenar por conformidade
            for municipio, conf, meses_falt in municipios_criticos[:10]:
                relatorio += f"\n• {municipio}: {conf:.1f}% ({meses_falt} meses em débito)"
    
    relatorio += f"""

═══════════════════════════════════════════════════════════════
**RECOMENDAÇÕES ESTRATÉGICAS:**

1. **QUALIDADE DE DADOS:** {estatisticas_limpeza['registros_removidos']:,} registros necessitam correção manual

2. **PERFORMANCE:** Focar nos {atencao if 'atencao' in locals() else 'N/A'} municípios com performance abaixo de 70%

3. **CONFORMIDADE:** Implementar cobrança sistemática para municípios em débito

4. **MONITORAMENTO:** Estabelecer rotina semanal de acompanhamento

5. **CAPACITAÇÃO:** Treinamento das equipes com menor performance

6. **TECNOLOGIA:** Implementar alertas automáticos para atrasos

7. **GESTÃO:** Criar comitê de acompanhamento mensal

═══════════════════════════════════════════════════════════════
**SISTEMA DE CACHE ATIVO - DADOS PERSISTENTES**
Relatório gerado automaticamente em {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}
Sistema Avançado Final - Provimento 07/2021
Cache otimizado para navegação fluida e análises em tempo real.
    """
    
    st.markdown(relatorio)
    return relatorio

# ==================== INTERFACE PRINCIPAL ====================

def main():
    # Inicializar cache transparente
    inicializar_cache()
    
    st.title("📊 Sistema Avançado Final - Provimento 07/2021")
    st.markdown("**Análise Completa + Gráficos Avançados + Cache Persistente Otimizado**")
    
    # ==================== SIDEBAR ====================
    st.sidebar.header("⚙️ Central de Controle do Sistema")
    
    # Status do Cache Otimizado
    st.sidebar.subheader("💾 Cache Persistente")
    if st.session_state.cache_ativo:
        tempo_cache = datetime.now() - st.session_state.timestamp_cache
        minutos_cache = int(tempo_cache.total_seconds() / 60)
        
        st.sidebar.success(f"✅ Cache ativo há {minutos_cache} min")
        st.sidebar.info(f"📊 {len(st.session_state.dados_cache):,} registros")
        st.sidebar.info(f"⚖️ {len(st.session_state.conformidade_cache)} análises de conformidade")
        
        # Botões de gerenciamento do cache
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.button("🗑️ Limpar", help="Limpa todo o cache"):
                limpar_cache()
                st.rerun()
        
        with col2:
            # Export do cache
            if st.session_state.dados_cache is not None:
                dados_cache = st.session_state.dados_cache.to_csv(index=False)
                st.download_button(
                    label="💾 Export",
                    data=dados_cache,
                    file_name=f"cache_completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    help="Exporta dados do cache"
                )
    else:
        st.sidebar.warning("⚠️ Cache inativo")
        st.sidebar.info("Carregue dados para ativar")
    
    # URL padrão da planilha
    url_padrao = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRtKiqlosLL5_CJgGom7BlWpFYExhLTQEjQT_Pdgnv3uEYMlWPpsSeaxfjqy0IxTluVlKSpcZ1IoXQY/pub?output=csv"
    
    st.sidebar.subheader("📥 Carregamento de Dados")
    fonte_dados = st.sidebar.radio(
        "Selecione a fonte:",
        ["URL Padrão", "URL Personalizada", "Upload de Arquivo"]
    )
    
    df = None
    carregar_novos_dados = False
    
    if fonte_dados == "URL Padrão":
        st.sidebar.info("📡 Planilha oficial do Provimento 07/2021")
        if st.sidebar.button("🔄 Carregar Dados", type="primary"):
            with st.spinner("Carregando e processando dados..."):
                df = carregar_dados_url(url_padrao)
                carregar_novos_dados = True
    
    elif fonte_dados == "URL Personalizada":
        url_custom = st.sidebar.text_input("🔗 Cole a URL do CSV:", placeholder="https://...")
        if url_custom and st.sidebar.button("🔄 Carregar da URL", type="primary"):
            with st.spinner("Carregando e processando dados..."):
                df = carregar_dados_url(url_custom)
                carregar_novos_dados = True
    
    else:  # Upload de arquivo
        arquivo = st.sidebar.file_uploader(
            "📁 Envie seu arquivo CSV:",
            type=['csv'],
            help="Arraste e solte ou clique para selecionar"
        )
        if arquivo:
            with st.spinner("Processando arquivo enviado..."):
                df = carregar_dados_arquivo(arquivo)
                carregar_novos_dados = True
    
    # ==================== PROCESSAMENTO DOS DADOS ====================
    
    # Se há dados em cache E não está carregando novos dados, usar cache
    if st.session_state.cache_ativo and not carregar_novos_dados and df is None:
        df_processado = st.session_state.dados_cache
        df_original = st.session_state.dados_originais_cache
        estatisticas_limpeza = st.session_state.estatisticas_cache
        analise_qualidade = st.session_state.analise_qualidade_cache
        
        st.success(f"🚀 **{len(df_processado):,} registros** carregados automaticamente do cache persistente!")
        
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
            
            # Salvar automaticamente no cache (incluindo pré-cálculo de conformidade)
            with st.spinner("Salvando no cache e pré-calculando análises..."):
                salvar_no_cache(df_processado, df_original, estatisticas_limpeza, analise_qualidade)
            
            # Mostrar análise de qualidade
            mostrar_analise_qualidade(analise_qualidade, total_registros, estatisticas_limpeza)
        
        st.success(f"✅ **{len(df_processado):,} registros** processados e armazenados no cache com análises pré-calculadas!")
        
    else:
        # Verificar se há cache para usar
        if st.session_state.cache_ativo:
            df_processado = st.session_state.dados_cache
            df_original = st.session_state.dados_originais_cache
            estatisticas_limpeza = st.session_state.estatisticas_cache
            analise_qualidade = st.session_state.analise_qualidade_cache
            
            st.info("📊 **Sistema usando dados em cache.** Para carregar novos dados, use as opções da sidebar.")
        else:
            # Tela inicial
            st.info("👆 **Selecione uma fonte de dados na barra lateral para começar.**")
            
            st.markdown("""
            ## 🚀 Sistema Avançado Final - Principais Funcionalidades
            
            ### 💾 **Cache Persistente Otimizado**
            ✅ **Armazenamento Inteligente** - Dados + análises pré-calculadas em memória  
            ✅ **Performance Máxima** - Navegação instantânea entre todas as abas  
            ✅ **Pré-cálculo** - Análises de conformidade calculadas automaticamente  
            ✅ **Propriedades ACID** - Consistência total durante toda a sessão  
            
            ### 📊 **Gráficos Interativos Avançados**
            ✅ **8 Tipos de Análise** - Nascimentos vs Registros, Evolução, Tendências, etc.  
            ✅ **Múltiplos Agrupamentos** - Por município, serventia, posto, ano, mês  
            ✅ **Configurações Dinâmicas** - Limites, filtros, modos de visualização  
            ✅ **Estatísticas Descritivas** - Médias, medianas, distribuições  
            
            ### ⚖️ **Análise de Conformidade Provimento 07/2021**
            ✅ **Análise Individual** - Por município com relatório executivo  
            ✅ **Dashboard Geral** - Status de todos os municípios  
            ✅ **Identificação de Débitos** - Meses faltantes específicos  
            ✅ **Classificação Automática** - Conforme/Atenção/Crítico  
            
            ### 🗺️ **Análise Geográfica Completa**
            ✅ **Rankings Dinâmicos** - Por performance e conformidade  
            ✅ **Filtros Múltiplos** - Status, critérios, quantidades  
            ✅ **Estatísticas Consolidadas** - Visão geral do estado  
            
            ### 📋 **Relatório Executivo Inteligente**
            ✅ **Integração Total** - Qualidade + Performance + Conformidade  
            ✅ **Recomendações Automáticas** - Baseadas nos dados analisados  
            ✅ **Downloads Múltiplos** - CSV, TXT, relatórios específicos  
            
            ---
            
            **🎯 Navegue livremente entre as 5 abas - todos os dados ficam em cache!**
            """)
            return
    
    # ==================== FILTROS DINÂMICOS MELHORADOS ====================
    st.sidebar.subheader("🔍 Filtros Avançados")
    
    df_original_completo = df_processado.copy()
    df_filtrado = df_processado.copy()
    
    # Salvar filtros no session state
    with st.sidebar:
        # Filtro por ano
        if 'ano' in df_filtrado.columns:
            anos_disponiveis = sorted(df_filtrado['ano'].dropna().unique())
            if anos_disponiveis:
                ano_selecionado = st.selectbox(
                    "📅 Ano:", 
                    ['Todos'] + list(anos_disponiveis),
                    key="filtro_ano"
                )
                if ano_selecionado != 'Todos':
                    df_filtrado = df_filtrado[df_filtrado['ano'] == ano_selecionado]
        
        # Filtro por mês
        if 'mes' in df_filtrado.columns:
            meses_disponiveis = sorted(df_filtrado['mes'].dropna().unique())
            if meses_disponiveis:
                meses_nomes = {
                    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
                    5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
                    9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
                }
                opcoes_meses = ['Todos'] + [f"{meses_nomes[mes]} ({mes})" for mes in meses_disponiveis]
                
                mes_selecionado = st.selectbox(
                    "📅 Mês:", 
                    opcoes_meses,
                    key="filtro_mes"
                )
                if mes_selecionado != 'Todos':
                    mes_numero = int(mes_selecionado.split('(')[1].split(')')[0])
                    df_filtrado = df_filtrado[df_filtrado['mes'] == mes_numero]
        
        # Filtro por município com busca
        if 'municipio' in df_filtrado.columns:
            municipios_disponiveis = sorted(df_filtrado['municipio'].dropna().unique())
            if municipios_disponiveis:
                busca_municipio = st.text_input("🔍 Buscar município:", placeholder="Digite para filtrar...")
                
                if busca_municipio:
                    municipios_filtrados = [m for m in municipios_disponiveis if busca_municipio.lower() in m.lower()]
                else:
                    municipios_filtrados = municipios_disponiveis
                
                municipio_selecionado = st.selectbox(
                    "🏙️ Município:", 
                    ['Todos'] + municipios_filtrados,
                    key="filtro_municipio"
                )
                if municipio_selecionado != 'Todos':
                    df_filtrado = df_filtrado[df_filtrado['municipio'] == municipio_selecionado]
        
        # Filtro por serventia
        if 'serventia' in df_filtrado.columns:
            serventias_disponiveis = sorted(df_filtrado['serventia'].dropna().unique())
            if serventias_disponiveis and len(serventias_disponiveis) <= 50:  # Só mostrar se não for muitas
                serventia_selecionada = st.selectbox(
                    "🏢 Serventia:", 
                    ['Todas'] + list(serventias_disponiveis),
                    key="filtro_serventia"
                )
                if serventia_selecionada != 'Todas':
                    df_filtrado = df_filtrado[df_filtrado['serventia'] == serventia_selecionada]
        
        # Filtro por faixa de percentual
        if 'percentual' in df_filtrado.columns:
            min_perc = float(df_filtrado['percentual'].min())
            max_perc = float(df_filtrado['percentual'].max())
            if min_perc < max_perc:
                faixa_percentual = st.slider(
                    "📊 Faixa de Percentual:",
                    min_perc, max_perc,
                    (min_perc, max_perc),
                    step=0.1,
                    key="filtro_percentual"
                )
                df_filtrado = df_filtrado[
                    (df_filtrado['percentual'] >= faixa_percentual[0]) & 
                    (df_filtrado['percentual'] <= faixa_percentual[1])
                ]
        
        # Mostrar info sobre filtros aplicados
        if len(df_filtrado) != len(df_original_completo):
            st.success(f"🎯 **{len(df_filtrado):,}** de **{len(df_original_completo):,}** registros")
            reducao = (1 - len(df_filtrado)/len(df_original_completo)) * 100
            st.info(f"📉 Redução: {reducao:.1f}%")
        else:
            st.info(f"📊 **{len(df_filtrado):,}** registros (sem filtros)")
    
    # ==================== ABAS PRINCIPAIS MELHORADAS ====================
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Dashboard Principal", 
        "⚖️ Análise de Conformidade", 
        "📈 Gráficos Avançados", 
        "🗺️ Análise Geográfica", 
        "📋 Relatório Executivo"
    ])
    
    with tab1:
        st.header("📈 Dashboard Principal Interativo")
        
        # Métricas principais em cards
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            total_nascimentos = df_filtrado['nascimentos'].sum() if 'nascimentos' in df_filtrado.columns else 0
            variacao_nasc = ((total_nascimentos / df_original_completo['nascimentos'].sum()) - 1) * 100 if total_nascimentos > 0 else 0
            st.metric("👶 Nascimentos", f"{total_nascimentos:,}", f"{variacao_nasc:+.1f}%" if variacao_nasc != 0 else None)
        
        with col2:
            total_registros = df_filtrado['registros'].sum() if 'registros' in df_filtrado.columns else 0
            variacao_reg = ((total_registros / df_original_completo['registros'].sum()) - 1) * 100 if total_registros > 0 else 0
            st.metric("📝 Registros", f"{total_registros:,}", f"{variacao_reg:+.1f}%" if variacao_reg != 0 else None)
        
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
        
        # Quick insights
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🎯 Quick Insights")
            if 'percentual' in df_filtrado.columns:
                melhor_municipio = df_filtrado.groupby('municipio')['percentual'].mean().idxmax()
                melhor_perc = df_filtrado.groupby('municipio')['percentual'].mean().max()
                st.success(f"🏆 Melhor: **{melhor_municipio}** ({melhor_perc:.1f}%)")
                
                pior_municipio = df_filtrado.groupby('municipio')['percentual'].mean().idxmin()
                pior_perc = df_filtrado.groupby('municipio')['percentual'].mean().min()
                st.error(f"⚠️ Precisa atenção: **{pior_municipio}** ({pior_perc:.1f}%)")
        
        with col2:
            st.subheader("📊 Distribuição de Performance")
            if 'percentual' in df_filtrado.columns:
                excelente = len(df_filtrado[df_filtrado['percentual'] >= 90])
                bom = len(df_filtrado[(df_filtrado['percentual'] >= 70) & (df_filtrado['percentual'] < 90)])
                ruim = len(df_filtrado[df_filtrado['percentual'] < 70])
                
                st.write(f"🟢 Excelente (≥90%): **{excelente:,}** registros")
                st.write(f"🟡 Bom (70-89%): **{bom:,}** registros")
                st.write(f"🔴 Atenção (<70%): **{ruim:,}** registros")
        
        st.markdown("---")
        
        # Tabela principal com paginação
        st.subheader("📋 Dados Detalhados (Cache Ativo)")
        
        # Configurações da tabela
        col1, col2 = st.columns(2)
        
        with col1:
            registros_por_pagina = st.selectbox("Registros por página:", [25, 50, 100, 200], index=1)
        
        with col2:
            total_paginas = (len(df_filtrado) + registros_por_pagina - 1) // registros_por_pagina
            pagina_atual = st.number_input("Página:", min_value=1, max_value=total_paginas, value=1) if total_paginas > 1 else 1
        
        # Calcular índices para paginação
        inicio = (pagina_atual - 1) * registros_por_pagina
        fim = inicio + registros_por_pagina
        
        # Preparar dados para exibição
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
            
            df_pagina = df_filtrado[colunas_existentes].iloc[inicio:fim].copy()
            df_pagina = df_pagina.rename(columns=mapeamento_exibicao)
            
            st.dataframe(
                df_pagina,
                use_container_width=True,
                height=500
            )
            
            st.info(f"Exibindo registros {inicio+1} a {min(fim, len(df_filtrado))} de {len(df_filtrado):,} total")
        
        # Downloads melhorados
        st.subheader("💾 Downloads Disponíveis")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            csv_filtrado = df_filtrado.to_csv(index=False)
            st.download_button(
                label="📊 Dados Filtrados (CSV)",
                data=csv_filtrado,
                file_name=f"dados_filtrados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                help="Baixa apenas os dados com filtros aplicados"
            )
        
        with col2:
            csv_original = df_original.to_csv(index=False)
            st.download_button(
                label="📁 Dados Originais (CSV)",
                data=csv_original,
                file_name=f"dados_originais_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                help="Baixa todos os dados originais da fonte"
            )
        
        with col3:
            if st.session_state.dados_cache is not None:
                csv_cache = st.session_state.dados_cache.to_csv(index=False)
                st.download_button(
                    label="💾 Cache Completo (CSV)",
                    data=csv_cache,
                    file_name=f"cache_completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    help="Baixa todos os dados processados do cache"
                )
    
    with tab2:
        st.header("⚖️ Central de Análise de Conformidade")
        st.markdown("**Monitoramento do cumprimento do Provimento 07/2021**")
        
        # Análise geral de conformidade
        st.subheader("📊 Dashboard Geral de Conformidade")
        
        conformidade_geral_df = analisar_conformidade_geral(df_processado)
        
        if conformidade_geral_df is not None:
            # Métricas gerais de conformidade
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                conformes = len(conformidade_geral_df[conformidade_geral_df['Conformidade (%)'] >= 90])
                st.metric("🟢 Conformes", conformes)
            
            with col2:
                atencao = len(conformidade_geral_df[(conformidade_geral_df['Conformidade (%)'] >= 70) & (conformidade_geral_df['Conformidade (%)'] < 90)])
                st.metric("🟡 Atenção", atencao)
            
            with col3:
                criticos = len(conformidade_geral_df[conformidade_geral_df['Conformidade (%)'] < 70])
                st.metric("🔴 Críticos", criticos)
            
            with col4:
                media_conformidade = conformidade_geral_df['Conformidade (%)'].mean()
                st.metric("📊 Média Geral", f"{media_conformidade:.1f}%")
            
            # Tabela de conformidade geral
            st.subheader("📋 Status de Conformidade por Município")
            
            # Filtros para a tabela de conformidade
            col1, col2 = st.columns(2)
            
            with col1:
                status_conf_filtro = st.selectbox(
                    "Filtrar por status:",
                    ['Todos', '🟢 Conforme', '🟡 Atenção', '🔴 Crítico'],
                    key="conformidade_filtro_status"
                )
            
            with col2:
                limite_conf = st.slider("Mostrar quantos municípios:", 10, len(conformidade_geral_df), 25, key="conformidade_limite")
            
            # Aplicar filtro
            df_conf_filtrado = conformidade_geral_df.copy()
            if status_conf_filtro != 'Todos':
                df_conf_filtrado = df_conf_filtrado[df_conf_filtrado['Status'] == status_conf_filtro]
            
            df_conf_filtrado = df_conf_filtrado.head(limite_conf)
            
            st.dataframe(df_conf_filtrado, use_container_width=True, height=400)
        
        st.markdown("---")
        
        # Análise individual detalhada
        st.subheader("🔍 Análise Individual Detalhada")
        
        if 'municipio' in df_processado.columns:
            municipios_disponiveis = sorted(df_processado['municipio'].dropna().unique())
            
            col1, col2 = st.columns(2)
            
            with col1:
                municipio_analise = st.selectbox(
                    "🏙️ Selecione o município para análise detalhada:",
                    municipios_disponiveis,
                    key="municipio_conformidade_detalhada"
                )
            
            with col2:
                st.info("📋 **Provimento 07/2021**: Envio obrigatório até dia 10 de cada mês")
            
            if municipio_analise:
                # Buscar análise no cache ou calcular
                if municipio_analise in st.session_state.conformidade_cache:
                    analise_conformidade = st.session_state.conformidade_cache[municipio_analise]
                else:
                    analise_conformidade = analisar_conformidade_municipio(df_processado, municipio_analise)
                    if analise_conformidade:
                        st.session_state.conformidade_cache[municipio_analise] = analise_conformidade
                
                if analise_conformidade:
                    # Métricas de conformidade individual
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
                        status_emoji = "🟢" if conformidade >= 90 else "🟡" if conformidade >= 70 else "🔴"
                        st.metric(
                            "📊 Conformidade", 
                            f"{conformidade:.1f}%",
                            f"{status_emoji} {conformidade - 100:.1f}%" if conformidade < 100 else "✅ Conforme"
                        )
                    
                    st.markdown("---")
                    
                    # Análise visual
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("📊 Situação Geral")
                        dados_grafico = pd.DataFrame({
                            'Status': ['Em Conformidade', 'Em Defasagem'],
                            'Percentual': [analise_conformidade['conformidade_geral'], analise_conformidade['defasagem_geral']]
                        })
                        chart_data = dados_grafico.set_index('Status')['Percentual']
                        st.bar_chart(chart_data)
                    
                    with col2:
                        st.subheader("📋 Detalhamento por Ano")
                        dados_por_ano = []
                        for ano, dados in analise_conformidade['analise_por_ano'].items():
                            dados_por_ano.append({
                                'Ano': ano,
                                'Informados': dados['total_informado'],
                                'Esperados': dados['total_esperado'],
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
                    
                    # Downloads específicos
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.download_button(
                            label="💾 Download Relatório de Conformidade",
                            data=relatorio_conformidade,
                            file_name=f"conformidade_{municipio_analise}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                            mime="text/plain"
                        )
                    
                    with col2:
                        # Criar CSV específico do município
                        dados_municipio_csv = df_processado[df_processado['municipio'] == municipio_analise].to_csv(index=False)
                        st.download_button(
                            label="📊 Download Dados do Município",
                            data=dados_municipio_csv,
                            file_name=f"dados_{municipio_analise}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )
                    
                    # Detalhamento de pendências por ano
                    if analise_conformidade['todos_meses_faltantes']:
                        st.subheader("🔍 Detalhamento de Pendências por Ano")
                        
                        for ano, dados in analise_conformidade['analise_por_ano'].items():
                            with st.expander(f"📅 Ano {ano} - {dados['total_informado']}/{dados['total_esperado']} meses informados", expanded=False):
                                if dados['meses_faltantes']:
                                    st.warning(f"**Meses em débito:** {', '.join(dados['meses_faltantes_nomes'])}")
                                    st.error(f"**Déficit:** {dados['total_faltante']} meses ({dados['percentual_defasagem']:.1f}%)")
                                else:
                                    st.success("✅ Todos os meses informados")
                                
                                # Mostrar dados detalhados do ano
                                if dados['total_nascimentos'] > 0:
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        st.metric("👶 Nascimentos", f"{dados['total_nascimentos']:,}")
                                    with col2:
                                        st.metric("📝 Registros", f"{dados['total_registros']:,}")
                                    with col3:
                                        st.metric("⚠️ Déficit", f"{dados['deficit']:,}")
                    
                    else:
                        st.success("🎉 **Parabéns!** Este município está em conformidade total com o Provimento 07/2021")
                
                else:
                    st.warning("⚠️ Não foi possível analisar a conformidade para este município")
        
        else:
            st.warning("⚠️ Dados insuficientes para análise de conformidade")
    
    with tab3:
        st.header("📈 Centro de Gráficos Interativos Avançados")
        criar_graficos_avancados(df_filtrado)
    
    with tab4:
        st.header("🗺️ Análise Geográfica Completa")
        dados_geograficos = criar_resumo_geografico(df_filtrado)
        
        # Adicionar visualização de mapas conceitual
        if dados_geograficos is not None and not dados_geograficos.empty:
            st.markdown("---")
            st.subheader("🗺️ Visualização Geográfica Conceitual")
            
            # Criar um mapa conceitual simples baseado nos dados
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🏆 Top 10 Municípios")
                top_municipios = dados_geograficos.head(10)
                
                for idx, row in top_municipios.iterrows():
                    emoji = "🟢" if row['Percentual Médio'] >= 90 else "🟡" if row['Percentual Médio'] >= 70 else "🔴"
                    st.write(f"{emoji} **{row['Município']}**: {row['Percentual Médio']:.1f}%")
            
            with col2:
                st.subheader("⚠️ Municípios que Precisam Atenção")
                atencao_municipios = dados_geograficos[dados_geograficos['Status Performance'] == '🔴 Atenção'].head(10)
                
                if not atencao_municipios.empty:
                    for idx, row in atencao_municipios.iterrows():
                        st.write(f"🔴 **{row['Município']}**: {row['Percentual Médio']:.1f}% (Déficit: {row['Déficit Total']:,})")
                else:
                    st.success("✅ Nenhum município necessita atenção urgente!")
    
    with tab5:
        st.header("📋 Relatório Executivo Completo")
        relatorio_texto = gerar_relatorio_completo(df_filtrado, estatisticas_limpeza)
        
        st.markdown("---")
        
        # Seção de downloads do relatório
        st.subheader("💾 Downloads de Relatórios")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.download_button(
                label="📋 Relatório Executivo (TXT)",
                data=relatorio_texto,
                file_name=f"relatorio_executivo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain",
                help="Relatório completo em formato texto"
            )
        
        with col2:
            # Criar relatório de conformidade geral
            if st.session_state.conformidade_cache:
                relatorio_conf_geral = f"""
RELATÓRIO GERAL DE CONFORMIDADE - PROVIMENTO 07/2021
Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

RESUMO EXECUTIVO:
- Total de municípios analisados: {len(st.session_state.conformidade_cache)}
- Conformidade média: {sum([a['conformidade_geral'] for a in st.session_state.conformidade_cache.values()]) / len(st.session_state.conformidade_cache):.1f}%

DETALHAMENTO POR MUNICÍPIO:
"""
                for municipio, analise in st.session_state.conformidade_cache.items():
                    relatorio_conf_geral += f"""
{municipio}:
- Conformidade: {analise['conformidade_geral']:.1f}%
- Meses faltantes: {analise['total_meses_faltantes']}
- Status: {'Conforme' if analise['conformidade_geral'] >= 90 else 'Atenção' if analise['conformidade_geral'] >= 70 else 'Crítico'}
"""
                
                st.download_button(
                    label="⚖️ Relatório Conformidade (TXT)",
                    data=relatorio_conf_geral,
                    file_name=f"relatorio_conformidade_geral_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain",
                    help="Relatório de conformidade de todos os municípios"
                )
        
        with col3:
            # Criar relatório de estatísticas
            relatorio_stats = f"""
RELATÓRIO DE ESTATÍSTICAS - PROVIMENTO 07/2021
Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

ESTATÍSTICAS GERAIS:
- Total de registros processados: {len(df_processado):,}
- Total de nascimentos: {df_processado['nascimentos'].sum():,}
- Total de registros: {df_processado['registros'].sum():,}
- Percentual médio geral: {df_processado['percentual'].mean():.2f}%
- Déficit total: {df_processado['deficit'].sum():,}

DISTRIBUIÇÃO POR FAIXAS DE PERFORMANCE:
- Excelente (≥90%): {len(df_processado[df_processado['percentual'] >= 90]):,} registros
- Bom (70-89%): {len(df_processado[(df_processado['percentual'] >= 70) & (df_processado['percentual'] < 90)]):,} registros
- Atenção (<70%): {len(df_processado[df_processado['percentual'] < 70]):,} registros

QUALIDADE DOS DADOS:
- Registros originais: {estatisticas_limpeza['total_original']:,}
- Registros válidos: {estatisticas_limpeza['total_limpo']:,}
- Registros removidos: {estatisticas_limpeza['registros_removidos']:,}
- Qualidade geral: {100 - estatisticas_limpeza['percentual_removido']:.1f}%
"""
            
            st.download_button(
                label="📊 Relatório Estatísticas (TXT)",
                data=relatorio_stats,
                file_name=f"relatorio_estatisticas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain",
                help="Relatório com todas as estatísticas"
            )
        
        # Seção de insights e recomendações
        st.markdown("---")
        st.subheader("💡 Insights Automáticos")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**🎯 Principais Achados:**")
            
            # Calcular insights automáticos
            if 'percentual' in df_processado.columns:
                municipios_perf = df_processado.groupby('municipio')['percentual'].mean()
                melhor_muni = municipios_perf.idxmax()
                pior_muni = municipios_perf.idxmin()
                
                st.write(f"• Melhor performance: **{melhor_muni}** ({municipios_perf.max():.1f}%)")
                st.write(f"• Necessita atenção: **{pior_muni}** ({municipios_perf.min():.1f}%)")
                
                # Tendência
                if 'ano' in df_processado.columns and df_processado['ano'].nunique() > 1:
                    tend_anual = df_processado.groupby('ano')['percentual'].mean()
                    if len(tend_anual) >= 2:
                        tendencia = "crescente" if tend_anual.iloc[-1] > tend_anual.iloc[0] else "decrescente"
                        st.write(f"• Tendência geral: **{tendencia}**")
                
                # Performance por faixa
                criticos = len(municipios_perf[municipios_perf < 70])
                if criticos > 0:
                    st.write(f"• **{criticos}** municípios precisam atenção urgente")
        
        with col2:
            st.write("**📋 Recomendações Prioritárias:**")
            
            if st.session_state.conformidade_cache:
                municipios_criticos = []
                for muni, analise in st.session_state.conformidade_cache.items():
                    if analise['conformidade_geral'] < 70:
                        municipios_criticos.append((muni, analise['total_meses_faltantes']))
                
                if municipios_criticos:
                    municipios_criticos.sort(key=lambda x: x[1], reverse=True)
                    st.write(f"• Cobrar urgentemente {len(municipios_criticos)} municípios")
                    st.write(f"• Priorizar: **{municipios_criticos[0][0]}** ({municipios_criticos[0][1]} meses em débito)")
                else:
                    st.write("• ✅ Conformidade geral satisfatória")
            
            # Recomendações baseadas em qualidade
            if estatisticas_limpeza['percentual_removido'] > 10:
                st.write("• 🔴 Melhorar qualidade dos dados de entrada")
            elif estatisticas_limpeza['percentual_removido'] > 5:
                st.write("• 🟡 Monitorar qualidade dos dados")
            else:
                st.write("• ✅ Qualidade dos dados adequada")
    
    # ==================== RODAPÉ MELHORADO ====================
    st.markdown("---")
    
    # Informações do sistema
    col1, col2, col3 = st.columns(3)
    
    with col1:
        cache_info = f"Cache: {len(st.session_state.dados_cache):,} registros" if st.session_state.cache_ativo else "Cache: Inativo"
        st.markdown(f"💾 **{cache_info}**")
        
        if st.session_state.cache_ativo:
            tempo_cache = datetime.now() - st.session_state.timestamp_cache
            st.markdown(f"⏱️ **Tempo ativo:** {int(tempo_cache.total_seconds() / 60)} minutos")
    
    with col2:
        qualidade_dados = 100 - estatisticas_limpeza['percentual_removido']
        emoji_qualidade = "🟢" if qualidade_dados >= 95 else "🟡" if qualidade_dados >= 85 else "🔴"
        st.markdown(f"📊 **Qualidade:** {emoji_qualidade} {qualidade_dados:.1f}%")
        
        conformidade_media = None
        if st.session_state.conformidade_cache:
            conformidades = [a['conformidade_geral'] for a in st.session_state.conformidade_cache.values()]
            if conformidades:
                conformidade_media = sum(conformidades) / len(conformidades)
                emoji_conf = "🟢" if conformidade_media >= 90 else "🟡" if conformidade_media >= 70 else "🔴"
                st.markdown(f"⚖️ **Conformidade:** {emoji_conf} {conformidade_media:.1f}%")
    
    with col3:
        st.markdown(f"🕒 **Atualizado:** {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        st.markdown(f"📋 **Registros ativos:** {len(df_filtrado):,}")
    
    # Rodapé final
    st.markdown(f"""
    <div style='text-align: center; color: gray; font-size: 11px; padding: 15px; border-top: 1px solid #ddd; margin-top: 20px;'>
    <strong>Sistema Avançado Final - Provimento 07/2021 v3.0</strong><br>
    Cache Persistente Otimizado • Gráficos Interativos Avançados • Análise de Conformidade Completa<br>
    Propriedades ACID • Performance Otimizada • Navegação Fluida
    </div>
    """, unsafe_allow_html=True)

# ==================== EXECUTAR APLICAÇÃO ====================
if __name__ == "__main__":
    main()
