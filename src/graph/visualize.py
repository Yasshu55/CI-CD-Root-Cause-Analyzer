"""
visualize.py - Visualize the LangGraph workflow

Methods:
1. Mermaid diagram (paste into mermaid.live or GitHub)
2. ASCII representation
3. PNG export (requires additional dependencies)
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.graph.workflow import create_workflow


def visualize_graph():
    """Generate visualizations of the workflow graph."""
    
    print("\n" + "="*60)
    print("LANGGRAPH WORKFLOW VISUALIZATION")
    print("="*60)
    
    # Create the compiled workflow
    workflow = create_workflow()
    
    # Get the graph object
    graph = workflow.get_graph()
    
    # ----- Method 1: Mermaid Diagram -----
    print("\n[1] MERMAID DIAGRAM")
    print("-"*40)
    print("Copy this to https://mermaid.live or GitHub markdown:\n")
    
    mermaid_code = graph.draw_mermaid()
    print(mermaid_code)
    
    # Save mermaid to file
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    
    mermaid_path = output_dir / "workflow_supervisor_diagram.mmd"
    mermaid_path.write_text(mermaid_code, encoding='utf-8')
    print(f"\nSaved to: {mermaid_path}")
    
    # ----- Method 2: ASCII -----
    print("\n" + "="*60)
    print("[2] ASCII REPRESENTATION")
    print("-"*40)
    
    # Print nodes and edges manually
    print("\nNodes:")
    for node in graph.nodes:
        print(f"  - {node}")
    
    print("\nEdges:")
    for edge in graph.edges:
        print(f"  {edge[0]} -> {edge[1]}")
    
    # ----- Method 3: PNG Export -----
    print("\n" + "="*60)
    print("[3] PNG EXPORT")
    print("-"*40)
    
    try:
        png_path = output_dir / "workflow_supervisor_diagram.png"
        png_data = graph.draw_mermaid_png()
        png_path.write_bytes(png_data)
        print(f"Saved to: {png_path}")
    except Exception as e:
        print(f"PNG export failed: {e}")
        print("To enable PNG export, install: pip install grandalf")
    
    print("\n" + "="*60)
    print("Visualization complete!")
    print("="*60)


if __name__ == "__main__":
    visualize_graph()