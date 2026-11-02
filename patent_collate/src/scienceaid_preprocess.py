#!/usr/bin/env python3
"""
Analyze Patent XML Structure and Extract Tables

This script:
1. Parses USPTO patent XML (WIPO ST.36 format)
2. Identifies table elements
3. Extracts context (preceding 5 paragraphs)
4. Saves structured output for LLM processing

Usage:
    python 01_analyze_patent_xml.py --patent US20170035798A1

Input:
    - data/XML_patents/{patent_number}.XML

Output:
    - data/processed/table_analysis/{patent_number}_analysis.json
"""

import xml.etree.ElementTree as ET
import argparse
import json
import re
from pathlib import Path
from typing import List, Dict


class PatentXMLAnalyzer:
    """Analyze USPTO patent XML and extract tables with context"""

    def __init__(self, xml_path: Path, verbose: bool = True):
        self.xml_path = xml_path
        self.verbose = verbose
        self.tree = None
        self.root = None

    def log(self, message: str):
        """Log message if verbose mode is enabled"""
        if self.verbose:
            print(message)

    def parse(self):
        """Parse XML file (with fallback for HTML entity issues)"""
        self.log(f"Parsing: {self.xml_path}")

        # Try normal parsing first
        try:
            self.tree = ET.parse(self.xml_path)
            self.root = self.tree.getroot()
            self.log(f"✓ Parsed successfully (Root: {self.root.tag})")
            return
        except ET.ParseError as e:
            # Check if error is due to undefined HTML entities
            if 'undefined entity' in str(e):
                self.log(f"⚠ Standard parsing failed due to HTML entities, applying preprocessing...")
            else:
                raise

        # Fallback: Read and preprocess HTML entities
        with open(self.xml_path, 'r', encoding='utf-8') as f:
            xml_content = f.read()

        # Replace HTML entities with numeric character references
        import html
        import re

        # Additional entity mappings for special characters not in html.unescape
        # (MathML, Greek letters, etc.)
        special_entities = {
            '&mgr;': '&#956;',    # Greek small letter mu (μ)
            '&agr;': '&#945;',    # Greek small letter alpha (α)
            '&bgr;': '&#946;',    # Greek small letter beta (β)
            '&ggr;': '&#947;',    # Greek small letter gamma (γ)
            '&dgr;': '&#948;',    # Greek small letter delta (δ)
            '&egr;': '&#949;',    # Greek small letter epsilon (ε)
            '&boxH;': '&#9472;',  # Box drawing horizontal
            '&verbar;': '&#124;', # Vertical bar |
        }

        def replace_html_entities(match):
            entity = match.group(0)
            # Keep XML standard entities as-is
            if entity in ('&lt;', '&gt;', '&amp;', '&quot;', '&apos;'):
                return entity
            # Check special entities first
            if entity in special_entities:
                return special_entities[entity]
            # Try standard HTML unescape
            try:
                unescaped = html.unescape(entity)
                if unescaped != entity:  # Successfully unescaped
                    return ''.join(f'&#{ord(c)};' for c in unescaped)
                # If not unescaped, return as-is (will fail if truly undefined)
                return entity
            except:
                return entity

        xml_content = re.sub(r'&[a-zA-Z0-9]+;', replace_html_entities, xml_content)

        # Parse preprocessed content
        self.root = ET.fromstring(xml_content)
        self.tree = ET.ElementTree(self.root)
        self.log(f"✓ Parsed successfully with HTML entity preprocessing (Root: {self.root.tag})")

    def find_tables(self) -> List[ET.Element]:
        """Find all table elements in XML"""
        tables = self.root.findall('.//table')
        self.log(f"✓ Found {len(tables)} tables")
        return tables

    def extract_table_xml(self, table: ET.Element) -> str:
        """Extract table as XML string"""
        return ET.tostring(table, encoding='unicode', method='xml')

    def _contains_table(self, element: ET.Element) -> bool:
        """Check if element contains a table"""
        return element.find('.//table') is not None or element.find('.//tables') is not None

    def find_preceding_paragraphs(self, table: ET.Element, n: int = 5) -> List[str]:
        """
        Find n paragraphs preceding the table (excluding paragraphs that contain tables)

        Supports both old and new patent XML formats:
        - Old format (US20040138164A1): <paragraph> tags
        - New format (US20220226361A1): <p> tags
        """
        # Try to find description section
        description = self.root.find('.//description')
        if description is None:
            # Try alternative: subdoc-description for old format
            description = self.root.find('.//subdoc-description')

        if description is None:
            return []

        # Find paragraphs - try both <p> and <paragraph> tags
        all_paragraphs = description.findall('.//p')
        if not all_paragraphs:
            # Old format uses <paragraph> instead of <p>
            all_paragraphs = description.findall('.//paragraph')

        if not all_paragraphs:
            return []

        # Find table position in paragraphs
        table_position = None
        for i, p in enumerate(all_paragraphs):
            if table in list(p.iter()):
                table_position = i
                break

        if table_position is None:
            return []

        # Get preceding paragraphs that do NOT contain tables (text-only paragraphs)
        preceding_text_paragraphs = []
        for p in all_paragraphs[:table_position]:
            if not self._contains_table(p):
                text = ''.join(p.itertext()).strip()
                if text:
                    preceding_text_paragraphs.append(text)

        # Return last n text-only paragraphs
        return preceding_text_paragraphs[-n:] if len(preceding_text_paragraphs) >= n else preceding_text_paragraphs

    def analyze_table_structure(self, table: ET.Element) -> Dict:
        """Analyze table structure"""
        rows = table.findall('.//row')

        analysis = {
            'num_rows': len(rows),
            'num_entries': len(table.findall('.//entry')),
            'has_header': False,
            'sample_content': []
        }

        # Check for header
        if rows:
            first_row = rows[0]
            entries = first_row.findall('.//entry')
            if entries:
                analysis['has_header'] = True
                analysis['header_text'] = [
                    ''.join(e.itertext()).strip() for e in entries
                ]

        # Extract sample content (first 3 rows)
        for row in rows[:3]:
            entries = row.findall('.//entry')
            row_text = [''.join(e.itertext()).strip() for e in entries]
            analysis['sample_content'].append(row_text)

        return analysis

    def is_aso_candidate(self, table: ET.Element) -> bool:
        """ASOテーブル候補か簡易判定（ATCG 8文字以上のパターン）"""
        text = ''.join(table.itertext())
        text_no_space = re.sub(r'\s+', '', text)
        atcg_pattern = re.compile(r'[ATCGUatcgu]{8,}')
        return bool(atcg_pattern.search(text_no_space))

    def process_patent(self, output_dir: Path) -> Dict:
        """Process entire patent and extract tables with context"""
        self.parse()

        tables = self.find_tables()

        results = {
            'patent_number': self.xml_path.stem.split('-')[0],
            'xml_file': str(self.xml_path),
            'num_tables': len(tables),
            'tables': []
        }

        # Process each table
        for i, table in enumerate(tables, 1):
            self.log(f"\n--- Table {i}/{len(tables)} ---")

            is_candidate = self.is_aso_candidate(table)
            table_data = {
                'table_id': i,
                'table_xml': self.extract_table_xml(table),
                'structure': self.analyze_table_structure(table),
                'preceding_paragraphs': self.find_preceding_paragraphs(table, n=5),
                'is_aso_candidate': is_candidate,
            }

            self.log(f"  Structure: {table_data['structure']['num_rows']} rows, "
                     f"{table_data['structure']['num_entries']} entries")
            self.log(f"  ASO candidate: {is_candidate}")
            self.log(f"  Preceding context: {len(table_data['preceding_paragraphs'])} paragraphs")

            results['tables'].append(table_data)

        # Save results
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{results['patent_number']}_analysis.json"

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        self.log(f"\n✓ Saved: {output_file}")

        return results


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(description='Analyze patent XML and extract tables')
    parser.add_argument('--patent', type=str, required=True,
                        help='Patent number (e.g., US20170035798A1)')
    parser.add_argument('--verbose', action='store_true', default=True,
                        help='Enable verbose output (default: True)')
    parser.add_argument('--quiet', action='store_true',
                        help='Disable verbose output')

    args = parser.parse_args()

    # Setup paths
    base_dir = Path(__file__).parent.parent
    xml_dir = base_dir / 'data' / 'raw' / 'patents'
    output_dir = base_dir / 'data' / 'processed' / 'table_analysis'

    # Find XML file
    xml_files = list(xml_dir.glob(f"{args.patent}*.XML"))
    if not xml_files:
        print(f"✗ XML file not found for {args.patent}")
        print(f"  Searched in: {xml_dir}")
        return

    # Filter out sub-documents (S00001, S00002, etc.) and select main document
    main_xml_files = [f for f in xml_files if '-S' not in f.name]

    if main_xml_files:
        xml_file = main_xml_files[0]
    else:
        # Fallback to any XML if no main document found
        xml_file = xml_files[0]

    verbose = args.verbose and not args.quiet

    if verbose:
        print(f"Found {len(xml_files)} XML files")
        print(f"Using: {xml_file}")

    # Analyze
    analyzer = PatentXMLAnalyzer(xml_file, verbose=verbose)
    results = analyzer.process_patent(output_dir)

    # Summary
    if verbose:
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        print(f"Patent: {results['patent_number']}")
        print(f"Tables found: {results['num_tables']}")
        output_file = output_dir / f"{results['patent_number']}_analysis.json"
        print(f"Output: {output_file}")

        if results['num_tables'] > 0:
            print("\nNext step: Review extracted tables and prepare for LLM processing")


if __name__ == '__main__':
    main()
