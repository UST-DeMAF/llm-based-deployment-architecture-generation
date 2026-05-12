"""
Section-based diff rendering for EDMM evaluation.
Shows statistics and differences for each EDMM section separately.
"""

import streamlit as st
from typing import Dict, Any


def render_section_based_stats(actual_data: Dict, expected_data: Dict) -> Dict[str, Any]:
    """
    Display EDMM comparison results section-by-section.
    
    Sections:
    - component_types
    - relation_types
    - components
    - artifacts (from components)
    - relations (from components)
    - properties
    
    Returns:
        Results dict from compare_by_sections
    """
    from edmm_semantic_compare import compare_by_sections
    
    results = compare_by_sections(expected_data, actual_data)
    
    # Overall similarity at top
    overall_sim = results.get('overall_similarity', 0) * 100
    st.metric("📊 Overall Similarity", f"{overall_sim:.1f}%", 
              delta=None if overall_sim >= 80 else f"{overall_sim - 100:.1f}%")
              
    # --- THESIS METRICS (ADVANCED) ---
    adv = results.get('advanced_metrics', {})
    if adv:
        with st.expander("🎓 Thesis Evaluation (Advanced Metrics)", expanded=True):
            st.markdown("Metrics for semantic and topological accuracy.")
            
            # Row 1: Graph & Components
            c1, c2, c3 = st.columns(3)
            with c1:
                ged = adv.get('graph_edit_distance', 0)
                st.metric("Graph Edit Distance", f"{ged:.1f}", help="Lower is better. Measures topological difference.", delta=-ged if ged > 0 else "Perfect")
            with c2:
                recall = adv.get('component_recall', 0) * 100
                st.metric("Component Recall", f"{recall:.1f}%", help="% of expected components found")
            with c3:
                attr = adv.get('attribute_score', 0) * 100
                st.metric("Attribute Accuracy", f"{attr:.1f}%", help="Correctness of properties")
                
            # Row 2: Relations
            st.markdown("---")
            st.markdown("**Relation Analysis**")
            r1, r2, r3 = st.columns(3)
            with r1:
                prec = adv.get('relation_precision', 0) * 100
                st.metric("Rel Precision", f"{prec:.1f}%", help="Correctness of generated relations")
            with r2:
                rec = adv.get('relation_recall', 0) * 100
                st.metric("Rel Recall", f"{rec:.1f}%", help="Coverage of expected relations")
            with r3:
                f1 = adv.get('relation_f1', 0) * 100
                st.metric("Rel F1-Score", f"{f1:.1f}%", help="Harmonic mean of precision/recall")

    
    st.markdown("---")
    st.markdown("### Section-by-Section Analysis")
    
    # Define sections with icons and labels
    sections = [
        ('component_types', '📦', 'Component Types'),
        ('relation_types', '🔗', 'Relation Types'),
        ('components', '🧩', 'Components'),
        ('artifacts', '📄', 'Artifacts (from components)'),
        ('relations', '↔️', 'Relations (from components)'),
        ('properties', '⚙️', 'Properties (global)')
    ]
    
    for section_key, icon, label in sections:
        if section_key not in results:
            continue
        
        stats = results[section_key]
        similarity_pct = stats['similarity'] * 100
        
        # Expander color hint based on similarity
        if stats['mismatch_count'] == 0:
            status_emoji = "✅"
        elif stats['mismatch_count'] <= 3:
            status_emoji = "⚠️"
        else:
            status_emoji = "❌"
        
        # Expandable section
        expander_label = f"{icon} {label} - {similarity_pct:.1f}% {status_emoji}"
        
        # Auto-expand if has errors
        with st.expander(expander_label, expanded=(stats['mismatch_count'] > 0)):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("✅ Matches", stats['matching_count'])
            with col2:
                st.metric("❌ Mismatches", stats['mismatch_count'])
            with col3:
                st.metric("📊 Total Fields", stats['total_fields'])
            
            # Show differences if any
            if stats['mismatch_count'] > 0 and stats['differences']:
                st.markdown("#### Differences:")
                for diff in stats['differences']:
                    st.code(diff, language="text")
            elif stats['mismatch_count'] == 0:
                st.success("✅ Perfect match!")
    
    # Add component-level chunked analysis if available
    if 'component_chunks' in results:
        st.markdown("---")
        render_component_chunks(results['component_chunks'])
    
    return results


def render_component_chunks(chunk_results: Dict[str, Any]):
    """
    Render component-by-component analysis with sub-section drilldown.
    
    UI Structure:
    - Overall component stats (total, matched, mismatched, missing, unexpected)
    - Per-component expandable section:
      - Component status and overall similarity
      - Sub-section metrics (4 columns: type, properties, artifacts, relations)
      - Differences per sub-section (if any)
    
    Components with issues are auto-expanded and sorted first.
    """
    st.markdown("### 🧩 Component-by-Component Analysis")
    
    # Overall stats
    total = chunk_results.get('total_components', 0)
    matched = chunk_results.get('matched_count', 0)
    mismatched = chunk_results.get('mismatched_count', 0)
    missing = chunk_results.get('missing_count', 0)
    unexpected = chunk_results.get('unexpected_count', 0)
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("📦 Total", total)
    with col2:
        st.metric("✅ Matched", matched)
    with col3:
        st.metric("⚠️ Mismatched", mismatched)
    with col4:
        st.metric("❌ Missing", missing)
    with col5:
        st.metric("⚠️ Unexpected", unexpected)
    
    st.markdown("---")
    
    # Component details
    components = chunk_results.get('components', {})
    
    if not components:
        st.info("No components to compare")
        return
    
    # Sort components: issues first (by similarity), then matched
    sorted_comps = sorted(
        components.items(),
        key=lambda x: (x[1]['similarity'], x[0])  # Lower similarity first, then alphabetically
    )
    
    for comp_name, comp_data in sorted_comps:
        similarity_pct = comp_data['similarity'] * 100
        status = comp_data.get('status', 'unknown')
        
        # Status emoji and label
        if status == 'missing':
            emoji = "❌"
            label = f"{emoji} **{comp_name}** - MISSING"
        elif status == 'unexpected':
            emoji = "⚠️"
            label = f"{emoji} **{comp_name}** - UNEXPECTED"
        elif similarity_pct == 100:
            emoji = "✅"
            label = f"{emoji} **{comp_name}** - {similarity_pct:.0f}%"
        elif similarity_pct >= 75:
            emoji = "⚠️"
            label = f"{emoji} **{comp_name}** - {similarity_pct:.0f}%"
        else:
            emoji = "❌"
            label = f"{emoji} **{comp_name}** - {similarity_pct:.0f}%"
        
        # Auto-expand if has issues
        auto_expand = (similarity_pct < 100)
        
        with st.expander(label, expanded=auto_expand):
            
            # If missing or unexpected, show message only
            if status in ['missing', 'unexpected']:
                message = comp_data.get('message', 'Status issue')
                if status == 'missing':
                    st.error(f"❌ {message}")
                else:
                    st.warning(f"⚠️ {message}")
                continue
            
            # Sub-section breakdown
            sub_sections = comp_data.get('sub_sections', {})
            
            if not sub_sections:
                st.info("No sub-section data available")
                continue
            
            # Display sub-section metrics in 4 columns
            st.markdown("**Sub-Section Analysis:**")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                type_data = sub_sections.get('type', {})
                type_sim = type_data.get('similarity', 0) * 100
                delta_emoji = "✅" if type_sim == 100 else ("⚠️" if type_sim >= 50 else "❌")
                st.metric("Type", f"{type_sim:.0f}%", delta=delta_emoji)
            
            with col2:
                prop_data = sub_sections.get('properties', {})
                prop_sim = prop_data.get('similarity', 0) * 100
                delta_emoji = "✅" if prop_sim == 100 else ("⚠️" if prop_sim >= 50 else "❌")
                st.metric("Properties", f"{prop_sim:.0f}%", delta=delta_emoji)
            
            with col3:
                art_data = sub_sections.get('artifacts', {})
                art_sim = art_data.get('similarity', 0) * 100
                delta_emoji = "✅" if art_sim == 100 else ("⚠️" if art_sim >= 50 else "❌")
                st.metric("Artifacts", f"{art_sim:.0f}%", delta=delta_emoji)
            
            with col4:
                rel_data = sub_sections.get('relations', {})
                rel_sim = rel_data.get('similarity', 0) * 100
                delta_emoji = "✅" if rel_sim == 100 else ("⚠️" if rel_sim >= 50 else "❌")
                st.metric("Relations", f"{rel_sim:.0f}%", delta=delta_emoji)
            
            st.markdown("---")
            
            # Show differences for each sub-section
            for sub_key in ['type', 'properties', 'artifacts', 'relations']:
                sub_data = sub_sections.get(sub_key, {})
                diffs = sub_data.get('differences', [])
                sim = sub_data.get('similarity', 1.0) * 100
                
                if diffs and len(diffs) > 0:
                    st.markdown(f"**{sub_key.title()} Differences ({sim:.0f}%):**")
                    for diff in diffs:
                        st.code(diff, language="text")
