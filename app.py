"""
app.py - Simple Web Dashboard for CI/CD Analyzer
Run: streamlit run app.py
"""

import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from src.graph.workflow import run_analysis
from src.graph.state import GraphState

st.set_page_config(
    page_title="CI/CD Root Cause Analyzer",
    page_icon="🔧",
    layout="wide"
)

st.title("CI/CD Root Cause Analyzer")
st.markdown("Analyze failed GitHub Actions builds using AI agents")

# Input
repo_name = st.text_input(
    "GitHub Repository",
    placeholder="owner/repo",
    value="Yasshu55/Test-repo"
)

if st.button("Analyze", type="primary"):
    if "/" not in repo_name:
        st.error("Enter repository as owner/repo")
    else:
        with st.spinner("Analyzing... (this takes ~30 seconds)"):
            try:
                result = run_analysis(repo_name)
                
                if result.debugging_brief:
                    brief = result.debugging_brief
                    
                    # Header
                    st.success("Analysis Complete!")
                    
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Severity", brief.severity.upper())
                    col2.metric("Confidence", f"{brief.confidence_score:.0%}")
                    col3.metric("Fixes Found", len(brief.fix_suggestions))
                    
                    # Error Info
                    st.subheader("Error")
                    st.code(f"{brief.error_type}: {brief.error_message}")
                    
                    # Root Cause
                    st.subheader("Root Cause")
                    st.write(brief.root_cause_summary)
                    
                    # Fix Suggestions
                    st.subheader("Fix Suggestions")
                    for fix in brief.fix_suggestions:
                        with st.expander(f"Fix #{fix.priority}: {fix.title} ({fix.confidence:.0%})"):
                            st.write(fix.description)
                            if fix.implementation_steps:
                                st.markdown("**Steps:**")
                                for i, step in enumerate(fix.implementation_steps, 1):
                                    st.markdown(f"{i}. {step}")
                            if fix.code_example:
                                st.code(fix.code_example)
                    
                    # Links
                    if brief.relevant_links:
                        st.subheader("Helpful Links")
                        for link in brief.relevant_links:
                            st.markdown(f"- {link}")
                    
                    # Download
                    st.download_button(
                        "Download Report (Markdown)",
                        brief.to_markdown(),
                        file_name="debugging_brief.md",
                        mime="text/markdown"
                    )
                else:
                    st.warning("No debugging brief generated")
                    if result.error_message:
                        st.error(result.error_message)
                        
            except Exception as e:
                st.error(f"Error: {e}")

with st.sidebar:
    st.header("About")
    st.markdown("""
    This tool uses AI agents to:
    1. Fetch failed build logs
    2. Parse and extract errors
    3. Analyze root cause
    4. Research solutions
    5. Generate fix suggestions
    
    **Tech Stack:**
    - LangGraph (Supervisor Pattern)
    - Claude 3.5 Sonnet
    - Tavily Search
    - PyGithub
    """)