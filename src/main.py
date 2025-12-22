"""
main.py - CI/CD Root Cause Analyzer Entry Point

Usage:
    python -m src.main <owner/repo>
    python -m src.main Yasshu55/Test-repo
    
Or import and use programmatically:
    from src.main import analyze_repository
    result = analyze_repository("owner/repo")
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.graph.workflow import run_analysis
from src.graph.state import GraphState, WorkflowPhase


def analyze_repository(repo_name: str, output_dir: str = "output") -> GraphState:
    """
    Analyze a GitHub repository for CI/CD failures.
    
    Args:
        repo_name: Repository in "owner/repo" format
        output_dir: Directory for output files
        
    Returns:
        Final GraphState with debugging_brief
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    final_state = run_analysis(repo_name)
    
    if final_state.debugging_brief:
        brief = final_state.debugging_brief
        
        md_path = output_path / "debugging_brief.md"
        md_path.write_text(brief.to_markdown(), encoding='utf-8')
        
        json_path = output_path / "debugging_brief.json"
        json_path.write_text(brief.model_dump_json(indent=2), encoding='utf-8')
        
        print_summary(final_state, md_path)
    else:
        print_failure(final_state)
    
    return final_state


def print_summary(state: GraphState, output_path: Path):
    """Print analysis summary."""
    brief = state.debugging_brief
    
    print("\n" + "="*60)
    print("ANALYSIS COMPLETE")
    print("="*60)
    
    print(f"\nTitle: {brief.title}")
    print(f"Severity: {brief.severity.upper()}")
    print(f"Confidence: {brief.confidence_score:.0%}")
    
    print(f"\nRoot Cause:")
    print(f"  {brief.root_cause_summary[:100]}...")
    
    print(f"\nFix Suggestions:")
    for fix in brief.fix_suggestions:
        print(f"  {fix.priority}. {fix.title} ({fix.confidence:.0%})")
    
    if brief.relevant_links:
        print(f"\nHelpful Links:")
        for link in brief.relevant_links[:3]:
            print(f"  - {link}")
    
    print(f"\nOutput saved to: {output_path}")
    print("="*60)


def print_failure(state: GraphState):
    """Print failure information."""
    print("\n" + "="*60)
    print("ANALYSIS FAILED")
    print("="*60)
    
    print(f"\nPhase: {state.current_phase.value}")
    print(f"Error: {state.error_message}")
    
    if state.messages:
        print("\nLog:")
        for msg in state.messages:
            print(f"  - {msg}")
    
    print("="*60)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="CI/CD Root Cause Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m src.main Yasshu55/Test-repo
    python -m src.main owner/repo --output ./results
        """
    )
    
    parser.add_argument(
        "repository",
        help="GitHub repository in 'owner/repo' format"
    )
    
    parser.add_argument(
        "--output", "-o",
        default="output",
        help="Output directory (default: output)"
    )
    
    args = parser.parse_args()
    
    # Validate repository format
    if "/" not in args.repository:
        print("Error: Repository must be in 'owner/repo' format")
        sys.exit(1)
    
    try:
        result = analyze_repository(args.repository, args.output)
        
        if result.current_phase == WorkflowPhase.COMPLETED:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nAnalysis cancelled.")
        sys.exit(130)
    except Exception as e:
        print(f"\nFatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()