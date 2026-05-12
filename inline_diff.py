"""
Inline YAML Color Coding for Streamlit
Highlights matching/mismatching lines directly in YAML output
"""
import yaml
import streamlit as st
from typing import Dict, List, Tuple


def normalize_yaml_line(line: str) -> str:
    """
    Normalize YAML line by removing unnecessary quotes for comparison.
    Keeps semantic meaning while ignoring formatting differences.
    """
    stripped = line.strip()
    
    # Handle key: "value" -> key: value
    if ':' in stripped:
        key_part, value_part = stripped.split(':', 1)
        value_part = value_part.strip()
        
        # Remove quotes if they're wrapping the entire value
        if value_part.startswith('"') and value_part.endswith('"'):
            value_part = value_part[1:-1]
        elif value_part.startswith("'") and value_part.endswith("'"):
            value_part = value_part[1:-1]
        
        # Reconstruct with same indentation
        indent = len(line) - len(line.lstrip())
        return ' ' * indent + f"{key_part}: {value_part}"
    
    return line


def colorize_yaml_output(actual_data: Dict, expected_data: Dict = None) -> str:
    """
    Generate HTML with single-column color-coded YAML.
    Shows only ACTUAL output with background colors based on semantic comparison.
    
    Green = matches expected
    Red = differs from expected
    
    Args:
        actual_data: The actual EDMM output
        expected_data: The expected EDMM (optional, for comparison)
    
    Returns:
        HTML string with color-coded YAML
    """
    # Convert to YAML strings
    actual_yaml = yaml.dump(actual_data, sort_keys=False, default_flow_style=False)
    actual_lines = actual_yaml.splitlines()
    
    if expected_data is None:
        # No comparison, just show plain
        html = '<div style="font-family: \'Courier New\', monospace; white-space: pre; background: #f8f9fa; padding: 16px; border-radius: 4px; line-height: 1.6;">'
        for line in actual_lines:
            html += f'{line}\n'
        html += '</div>'
        return html
    
    # With comparison - use semantic comparison to identify different fields
    from edmm_semantic_compare import calculate_semantic_stats
    stats = calculate_semantic_stats(expected_data, actual_data)
    
    # Build set of paths that have differences
    diff_paths = set()
    for diff in stats.get('differences', []):
        # Parse path from diff string (format: "path: expected X, got Y")
        if ':' in diff:
            path = diff.split(':')[0].strip()
            diff_paths.add(path)
    
    # Also do normalized line-based comparison for visual highlighting
    expected_yaml = yaml.dump(expected_data, sort_keys=False, default_flow_style=False)
    expected_lines = expected_yaml.splitlines()
    
    # Normalize both for comparison (remove quotes)
    expected_normalized = [normalize_yaml_line(line) for line in expected_lines]
    actual_normalized = [normalize_yaml_line(line) for line in actual_lines]
    
    import difflib
    matcher = difflib.SequenceMatcher(None, expected_normalized, actual_normalized)
    
    # Build color-coded HTML (single column)
    html = '<div style="font-family: \'Courier New\', monospace; white-space: pre; padding: 12px; border-radius: 4px; line-height: 1.8; border: 1px solid #ddd;">'
    
    line_status = {}  # Track which lines match/differ
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for idx in range(j1, j2):
                line_status[idx] = 'match'
        elif tag == 'replace':
            for idx in range(j1, j2):
                line_status[idx] = 'mismatch'
        elif tag == 'insert':
            for idx in range(j1, j2):
                line_status[idx] = 'extra'
    
    # Render actual YAML with colors
    for idx, line in enumerate(actual_lines):
        status = line_status.get(idx, 'unknown')
        escaped_line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        if status == 'match':
            # Green background - matches expected
            html += f'<div style="background-color: #d4edda; color: #155724; padding: 2px 6px; margin: 1px 0;">{escaped_line if escaped_line else " "}</div>\n'
        elif status == 'mismatch':
            # Red background - differs from expected
            html += f'<div style="background-color: #f8d7da; color: #721c24; padding: 2px 6px; margin: 1px 0;">{escaped_line if escaped_line else " "}</div>\n'
        elif status == 'extra':
            # Yellow background - extra line not in expected
            html += f'<div style="background-color: #fff3cd; color: #856404; padding: 2px 6px; margin: 1px 0;">{escaped_line if escaped_line else " "}</div>\n'
        else:
            # Default (shouldn't happen)
            html += f'<div style="background-color: #ffffff; padding: 2px 6px; margin: 1px 0;">{escaped_line if escaped_line else " "}</div>\n'
    
    html += '</div>'
    return html


def render_inline_diff_stats(actual_data: Dict, expected_data: Dict) -> Dict:
    """
    Calculate and display statistics for EDMM semantic diff.
    Uses EDMM-aware comparison to eliminate false positives.
    
    Returns:
        Dict with stats
    """
    from edmm_semantic_compare import calculate_semantic_stats
    
    # Semantic comparison
    stats = calculate_semantic_stats(expected_data, actual_data)
    
    # Display stats with semantic values
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        similarity_pct = stats['similarity'] * 100
        st.metric("Similarity", f"{similarity_pct:.1f}%")
    
    with col2:
        st.metric("Matching Fields", stats['matching_count'])
    
    with col3:
        st.metric("Mismatches", stats['mismatch_count'])
    
    with col4:
        is_perfect = "✅ Perfect" if stats['is_match'] else "⚠️ Has Diffs"
        st.metric("Status", is_perfect)
    
    # Show detailed differences if any
    if stats['mismatch_count'] > 0 and stats['mismatch_count'] <= 50:
        with st.expander(f"📋 View {stats['mismatch_count']} Differences", expanded=False):
            for diff in stats['differences'][:50]:  # Limit to 50
                st.code(diff, language="text")
    elif stats['mismatch_count'] > 50:
        st.warning(f"⚠️ Too many differences ({stats['mismatch_count']}) to display. Check expected file.")
    
    return stats
