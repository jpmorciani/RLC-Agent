#!/usr/bin/env python3
"""
Script para baixar dados de exportação de soja do Brasil em 2025
Fonte: COMEXSTAT (MDIC)
"""

import requests
import json
import csv
from datetime import datetime
from pathlib import Path

# Configuração
API_URL = "https://api-comexstat.mdic.gov.br/general"
OUTPUT_DIR = Path("./data/comexstat")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Códigos NCM para soja e derivados
SOYBEAN_NCM_CODES = {
    'soja_graos': ['12019000', '12011000'],           # Soja em grãos
    'farelo_soja': ['23040010', '23040090'],          # Farelo de soja
    'oleo_soja': ['15071000', '15079011', '15079019', '15079090'],  # Óleo de soja
}

def fetch_soybean_exports(year: int = 2025):
    """Baixa dados de exportação de soja do COMEXSTAT"""

    print(f"Buscando dados de exportação de soja - {year}")
    print("=" * 60)

    all_records = []

    # Buscar cada tipo de produto
    for product_name, ncm_codes in SOYBEAN_NCM_CODES.items():
        print(f"\nBuscando {product_name}...")

        payload = {
            "flow": "export",
            "monthDetail": True,
            "period": {
                "from": f"{year}-01",
                "to": f"{year}-12"
            },
            "filters": [
                {
                    "filter": "ncm",
                    "values": ncm_codes
                }
            ],
            "details": ["country", "state"],
            "metrics": ["metricFOB", "metricKG"]
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        try:
            response = requests.post(API_URL, json=payload, headers=headers, timeout=120)

            if response.status_code == 200:
                data = response.json()

                # Extrair registros
                if isinstance(data, dict) and 'data' in data:
                    records = data['data']
                elif isinstance(data, list):
                    records = data
                else:
                    records = []

                print(f"  -> {len(records)} registros encontrados")

                # Adicionar nome do produto aos registros
                for record in records:
                    record['produto'] = product_name
                    all_records.append(record)

            else:
                print(f"  -> Erro: {response.status_code}")
                print(f"     {response.text[:200]}")

        except Exception as e:
            print(f"  -> Erro: {e}")

    return all_records

def process_records(records: list) -> list:
    """Processa e padroniza os registros"""

    processed = []

    for r in records:
        # Extrair valores com diferentes nomes de campo possíveis
        year = r.get('coAno') or r.get('year') or r.get('ano')
        month = r.get('coMes') or r.get('month') or r.get('mes')
        country = r.get('noPais') or r.get('noCountry') or r.get('country') or 'N/A'
        country_code = r.get('coPais') or r.get('coCountry') or ''
        state = r.get('sgUfNcm') or r.get('state') or r.get('uf') or 'N/A'

        value_usd = r.get('metricFOB') or r.get('vlFob') or 0
        weight_kg = r.get('metricKG') or r.get('kgLiquido') or 0

        try:
            value_usd = float(value_usd) if value_usd else 0
            weight_kg = float(weight_kg) if weight_kg else 0
        except (ValueError, TypeError):
            value_usd = 0
            weight_kg = 0

        weight_mt = weight_kg / 1000 if weight_kg else 0
        price_usd_mt = value_usd / weight_mt if weight_mt > 0 else 0

        processed.append({
            'ano': year,
            'mes': month,
            'periodo': f"{year}-{str(month).zfill(2)}" if year and month else '',
            'produto': r.get('produto', ''),
            'pais_destino': country,
            'codigo_pais': country_code,
            'estado_origem': state,
            'valor_fob_usd': round(value_usd, 2),
            'peso_kg': round(weight_kg, 2),
            'peso_toneladas': round(weight_mt, 2),
            'preco_usd_tonelada': round(price_usd_mt, 2)
        })

    return processed

def save_to_csv(records: list, filename: str):
    """Salva registros em CSV"""

    if not records:
        print("Nenhum registro para salvar")
        return

    filepath = OUTPUT_DIR / filename

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    print(f"\nArquivo salvo: {filepath}")

def save_to_json(records: list, filename: str):
    """Salva registros em JSON"""

    filepath = OUTPUT_DIR / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Arquivo salvo: {filepath}")

def print_summary(records: list):
    """Imprime resumo dos dados"""

    if not records:
        print("\nNenhum dado encontrado")
        return

    print("\n" + "=" * 60)
    print("RESUMO - Exportações de Soja Brasil 2025")
    print("=" * 60)

    # Totais por produto
    totals_by_product = {}
    for r in records:
        product = r['produto']
        if product not in totals_by_product:
            totals_by_product[product] = {'mt': 0, 'usd': 0}
        totals_by_product[product]['mt'] += r['peso_toneladas']
        totals_by_product[product]['usd'] += r['valor_fob_usd']

    print("\nPor Produto:")
    for product, totals in totals_by_product.items():
        mmt = totals['mt'] / 1_000_000
        billion_usd = totals['usd'] / 1_000_000_000
        print(f"  {product}: {mmt:.2f} MMT | US$ {billion_usd:.2f} bi")

    # Totais por país (top 10)
    totals_by_country = {}
    for r in records:
        country = r['pais_destino']
        if country not in totals_by_country:
            totals_by_country[country] = 0
        totals_by_country[country] += r['peso_toneladas']

    top_countries = sorted(totals_by_country.items(), key=lambda x: x[1], reverse=True)[:10]

    print("\nTop 10 Destinos:")
    for country, mt in top_countries:
        mmt = mt / 1_000_000
        print(f"  {country}: {mmt:.2f} MMT")

    # Total geral
    total_mt = sum(r['peso_toneladas'] for r in records)
    total_usd = sum(r['valor_fob_usd'] for r in records)

    print(f"\nTOTAL GERAL:")
    print(f"  Volume: {total_mt/1_000_000:.2f} MMT")
    print(f"  Valor: US$ {total_usd/1_000_000_000:.2f} bilhões")
    print(f"  Preço médio: US$ {total_usd/total_mt:.2f}/tonelada" if total_mt > 0 else "")


def main():
    """Função principal"""

    print("COMEXSTAT - Exportações de Soja do Brasil 2025")
    print("Fonte: Ministério do Desenvolvimento, Indústria e Comércio")
    print()

    # Baixar dados
    raw_records = fetch_soybean_exports(2025)

    if not raw_records:
        print("\nNenhum dado retornado pela API.")
        print("Possíveis motivos:")
        print("  - Dados de 2025 ainda não disponíveis")
        print("  - Problema de conexão com a API")
        return

    # Processar
    processed = process_records(raw_records)

    # Salvar
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_to_csv(processed, f"soja_exportacao_2025_{timestamp}.csv")
    save_to_json(processed, f"soja_exportacao_2025_{timestamp}.json")

    # Resumo
    print_summary(processed)


if __name__ == "__main__":
    main()
