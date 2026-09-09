import os
import sys
import argparse
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from core.router import ModelRouter, get_language_model
from core.engine import LowCodeAgent, NodeConfig, AgentPipeline
from core.memory import AgentMemory, RAGModule
from server.watcher import start_watcher, get_staged_patches, apply_staged_patch, reject_staged_patch

console = Console()

def cmd_status():
    """Display system and provider health status."""
    router = ModelRouter()
    status = router.get_status()
    
    console.print(Panel.fit("[bold cyan]Agent Engine Core Telemetry & Status[/bold cyan]", border_style="cyan"))

    table = Table(title="System & LLM Router Health", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan")
    table.add_column("Configured Value / State", style="yellow")
    table.add_column("Status", style="bold green")

    # Local Ollama
    ollama_state = "Online (Active)" if status["ollama_live"] else "Offline / Not Running"
    ollama_color = "[green]" if status["ollama_live"] else "[red]"
    table.add_row("Ollama Local Daemon", "http://localhost:11434", f"{ollama_color}{ollama_state}")

    # Local llama.cpp
    llamacpp_state = "Online (Active)" if status["llamacpp_live"] else "Offline / Not Running"
    llamacpp_color = "[green]" if status["llamacpp_live"] else "[red]"
    table.add_row("llama.cpp / vLLM Server", "http://localhost:8080/v1", f"{llamacpp_color}{llamacpp_state}")

    # Cloud Keys
    table.add_row("Gemini API Key", "Configured" if status["has_gemini_key"] else "Not Set", "[green]Ready" if status["has_gemini_key"] else "[dim]Unset")
    table.add_row("OpenAI API Key", "Configured" if status["has_openai_key"] else "Not Set", "[green]Ready" if status["has_openai_key"] else "[dim]Unset")
    table.add_row("Anthropic API Key", "Configured" if status["has_anthropic_key"] else "Not Set", "[green]Ready" if status["has_anthropic_key"] else "[dim]Unset")
    table.add_row("Groq API Key", "Configured" if status["has_groq_key"] else "Not Set", "[green]Ready" if status["has_groq_key"] else "[dim]Unset")

    # Routing preference
    table.add_row("Primary Provider", status["primary_provider"], "[blue]Configured")
    table.add_row("Fallback Provider", status["fallback_provider"], "[blue]Configured")

    # ChromaDB
    try:
        mem = AgentMemory()
        doc_count = mem.count()
        table.add_row("ChromaDB Memory", f"{doc_count} documents indexed", "[green]Ready")
    except Exception as e:
        table.add_row("ChromaDB Memory", f"Error: {e}", "[red]Failed")

    # Sentry Staged Patches
    try:
        staged_count = len(get_staged_patches())
        table.add_row("Sentry Staged Patches", f"{staged_count} pending reviews", "[green]Clean" if staged_count == 0 else "[yellow]Pending Review")
    except Exception:
        table.add_row("Sentry Staged Patches", "Database Ready", "[green]Ready")

    console.print(table)

def cmd_demo():
    """Run an end-to-end dynamic agent blueprint demo."""
    console.print("[bold green]Compiling dynamic agent blueprint...[/bold green]")
    
    blueprint = NodeConfig(
        name="SupportTicketClassifier",
        description="Analyze incoming technical issue and categorize urgency, root cause domain, and suggested action.",
        inputs={"ticket": "The raw customer support issue text"},
        outputs={
            "urgency": "Urgency rating (Low, Medium, High, Critical)",
            "domain": "Affected domain (Database, Auth, Frontend, Backend, Network)",
            "suggested_action": "Initial remediation advice for the engineering team"
        },
        reasoning_type="cot"
    )

    agent = LowCodeAgent(blueprint)
    console.print(f"[bold cyan]Successfully compiled:[/bold cyan] {agent}")
    
    router = ModelRouter()
    lm, label = router.initialize_and_configure()
    console.print(f"[bold yellow]Configured Model:[/bold yellow] {label}")

    console.print("\n[bold]Testing signature structure and validation:[/bold]")
    sig = agent.signature
    for field_name, field_def in sig.fields.items():
        console.print(f" - Field: [bold green]{field_name}[/bold green] ({type(field_def).__name__}) -> {field_def.json_schema_extra.get('desc')}")

def cmd_rag_demo():
    """Demonstrate RAG Vector Memory Ingestion & Querying."""
    console.print("[bold cyan]Initializing ChromaDB RAG Vector Store...[/bold cyan]")
    mem = AgentMemory()
    
    sample_docs = [
        "Agent Engine supports dynamic signature generation via DSPy.",
        "Local inference can run Gemma 4B models on AMD Ryzen CPUs using Ollama or llama.cpp.",
        "Model Context Protocol (MCP) connects local AI agents to VS Code, Cursor, and Goose AI.",
        "Streamlit dashboard runs on port 8501 for real-time telemetry and file watcher control."
    ]
    
    console.print(f"Ingesting {len(sample_docs)} sample system knowledge items...")
    mem.add_documents(sample_docs)
    console.print(f"[bold green]Total indexed memory count:[/bold green] {mem.count()}")

    query = "How does local inference run on Ryzen CPUs?"
    console.print(f"\n[bold yellow]Searching memory for:[/bold yellow] '{query}'")
    passages = mem.retrieve_passages(query, n_results=2)
    for idx, p in enumerate(passages, 1):
        console.print(f" [bold cyan]Passage {idx}:[/bold cyan] {p}")

def main():
    parser = argparse.ArgumentParser(description="Agent Engine CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    subparsers.add_parser("status", help="Display system status and provider health")
    subparsers.add_parser("demo", help="Run dynamic blueprint compilation demo")
    subparsers.add_parser("rag-demo", help="Test ChromaDB RAG memory ingestion and retrieval")
    
    subparsers.add_parser("mcp", help="Start the FastMCP stdio server for VS Code / Goose / Cursor")
    subparsers.add_parser("dashboard", help="Start the Streamlit Control Center on port 8501")
    
    # Watcher commands
    watch_p = subparsers.add_parser("watch", help="Start the Code Sentry / File-Watcher daemon")
    watch_p.add_argument("--dir", default="/home/nadir/agent_engine", help="Directory path to monitor")
    watch_p.add_argument("--auto-apply", action="store_true", help="Automatically write patches to disk on detection")
    
    list_p = subparsers.add_parser("staged", help="List all pending staged patches")
    apply_p = subparsers.add_parser("apply", help="Apply a staged patch by ID")
    apply_p.add_argument("patch_id", type=int, help="ID of patch to apply")
    reject_p = subparsers.add_parser("reject", help="Reject a staged patch by ID")
    reject_p.add_argument("patch_id", type=int, help="ID of patch to reject")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "mcp":
        from server.mcp_server import mcp as mcp_instance
        router = ModelRouter()
        router.initialize_and_configure()
        mcp_instance.run()
    elif args.command == "dashboard":
        import subprocess
        console.print("[bold cyan]🚀 Launching Streamlit Control Center on http://localhost:8501...[/bold cyan]")
        subprocess.run([
            sys.executable, "-m", "streamlit", "run",
            "/home/nadir/agent_engine/server/dashboard.py",
            "--server.port", "8501",
            "--server.headless", "true"
        ])
    elif args.command == "demo":
        cmd_demo()
    elif args.command == "rag-demo":
        cmd_rag_demo()
    elif args.command == "watch":
        start_watcher(watch_dir=args.dir, auto_apply=args.auto_apply)
    elif args.command == "staged":
        patches = get_staged_patches()
        if not patches:
            console.print("[bold green]✨ No pending staged patches in database.[/bold green]")
            return
        table = Table(title="Pending Staged Patches", header_style="bold magenta")
        table.add_column("ID", style="cyan")
        table.add_column("File", style="yellow")
        table.add_column("Type", style="bold")
        table.add_column("Risk", style="red")
        table.add_column("Timestamp", style="dim")
        for p in patches:
            table.add_row(str(p["id"]), os.path.basename(p["file_path"]), p["patch_type"], p["risk_level"] or "N/A", p["timestamp"])
        console.print(table)
    elif args.command == "apply":
        success = apply_staged_patch(args.patch_id)
        if success:
            console.print(f"[bold green]Successfully applied patch #{args.patch_id}![/bold green]")
        else:
            console.print(f"[bold red]Failed to find or apply patch #{args.patch_id}[/bold red]")
    elif args.command == "reject":
        success = reject_staged_patch(args.patch_id)
        if success:
            console.print(f"[bold yellow]Marked patch #{args.patch_id} as rejected.[/bold yellow]")
        else:
            console.print(f"[bold red]Failed to find patch #{args.patch_id}[/bold red]")
    else:
        cmd_status()

if __name__ == "__main__":
    main()
