"""core/workflows/swarm.py

Swarm Multi-Agent Parallel Execution Subsystem for Agent Engine.
Part of Phase 7 (Task 7.4 - Milestone M5).

Adheres to:
- ADR-012: Layered Workflows (parallel micro-agents execution).
- ADR-013: Zero non-free dependencies, 100% open-source local-first.
- ADR-015: 90/9/1 Cost routing discipline.
- docs/GUI.md Screen 4: Multi-Agent Parallel Execution.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("agent_engine.workflows.swarm")


class SwarmAgentSpec(BaseModel):
    """Specification of an agent participating in a multi-agent swarm."""

    id: str = Field(default_factory=lambda: f"agent_{uuid.uuid4().hex[:6]}")
    name: str
    role: str
    model_tier: str = "instant"
    system_prompt: str = ""
    estimated_cost_usd: float = 0.001


class SwarmCase(BaseModel):
    """Pre-configured featured multi-agent swarm team template."""

    id: str
    title: str
    tagline: str
    description: str
    agents: List[SwarmAgentSpec]
    default_prompt: str


class SwarmAgentProgress(BaseModel):
    """Execution status and live progress strip outcome for an individual agent."""

    agent_id: str
    agent_name: str
    role: str
    model_tier: str
    status: str = "completed"  # pending, running, completed, failed
    progress_percent: int = 100
    output: str = ""
    cost_usd: float = 0.0
    execution_time_ms: float = 0.0
    error: Optional[str] = None


class SwarmRunResult(BaseModel):
    """Aggregated outcome of a parallel multi-agent swarm run."""

    swarm_id: str
    prompt: str
    model_tier: str
    status: str = "completed"  # completed, partial_failure, failed
    agent_results: List[SwarmAgentProgress] = Field(default_factory=list)
    aggregated_output: str = ""
    total_cost_usd: float = 0.0
    total_time_ms: float = 0.0
    created_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )


FEATURED_SWARM_CASES: List[SwarmCase] = [
    SwarmCase(
        id="build_deploy_api",
        title="Build & deploy an API",
        tagline="4 agents: architect, coder, tester, deployer",
        description="Architect schemas, write endpoint handlers, generate test suites, and draft deployment configs.",
        default_prompt="Design and build a high-performance REST API for user profile and token management with caching.",
        agents=[
            SwarmAgentSpec(
                id="architect",
                name="Architect",
                role="API Architecture & Data Contracts",
                model_tier="instant",
                system_prompt="Design the high level API contract, data structures, and response schemas.",
                estimated_cost_usd=0.001,
            ),
            SwarmAgentSpec(
                id="coder",
                name="Coder",
                role="Backend Endpoint Implementation",
                model_tier="instant",
                system_prompt="Write production-ready, clean Python/FastAPI endpoint routes and logic.",
                estimated_cost_usd=0.0015,
            ),
            SwarmAgentSpec(
                id="tester",
                name="Tester",
                role="Pytest & Integration Validation",
                model_tier="instant",
                system_prompt="Generate comprehensive pytest unit and edge-case test functions.",
                estimated_cost_usd=0.0008,
            ),
            SwarmAgentSpec(
                id="deployer",
                name="Deployer",
                role="Docker & Service Deployment Manifest",
                model_tier="instant",
                system_prompt="Generate Dockerfile, compose file, and healthcheck configurations.",
                estimated_cost_usd=0.0007,
            ),
        ],
    ),
    SwarmCase(
        id="deep_code_review",
        title="Deep code review",
        tagline="3 agents: security, lint, fix",
        description="Comprehensive multi-perspective audit covering security boundaries, code cleanliness, and fix generation.",
        default_prompt="Perform deep security audit and linter analysis on authentication and session storage modules.",
        agents=[
            SwarmAgentSpec(
                id="security",
                name="Security Auditor",
                role="Security Boundaries & Vulnerability Scanner",
                model_tier="instant",
                system_prompt="Audit source code for OWASP vulnerabilities, injection vectors, and auth leaks.",
                estimated_cost_usd=0.0015,
            ),
            SwarmAgentSpec(
                id="lint",
                name="Linter & Style",
                role="Code Quality & Performance Auditor",
                model_tier="instant",
                system_prompt="Inspect complexity, type hints, error handling, and performance bottlenecks.",
                estimated_cost_usd=0.0008,
            ),
            SwarmAgentSpec(
                id="fix",
                name="Remediation Engineer",
                role="Automated Staged Patch Generator",
                model_tier="instant",
                system_prompt="Generate concrete unified diff patches addressing detected issues.",
                estimated_cost_usd=0.0012,
            ),
        ],
    ),
    SwarmCase(
        id="market_research",
        title="Market research report",
        tagline="4 agents: search, analyst, writer, editor",
        description="Autonomous research team conducting market landscape analysis, trend forecasting, and executive drafting.",
        default_prompt="Analyze local-first AI developer tooling landscape, open-weights trends, and privacy compliance needs.",
        agents=[
            SwarmAgentSpec(
                id="search",
                name="Researcher",
                role="Information Gathering & Source Indexing",
                model_tier="instant",
                system_prompt="Aggregate domain signals, market players, open-source adoption, and benchmarks.",
                estimated_cost_usd=0.001,
            ),
            SwarmAgentSpec(
                id="analyst",
                name="Market Analyst",
                role="Quantitative & Strategic Analysis",
                model_tier="instant",
                system_prompt="Identify cost economics, switching costs, and developer retention metrics.",
                estimated_cost_usd=0.001,
            ),
            SwarmAgentSpec(
                id="writer",
                name="Report Drafter",
                role="Comprehensive Section Drafter",
                model_tier="instant",
                system_prompt="Synthesize findings into structured, readable report sections with citations.",
                estimated_cost_usd=0.0012,
            ),
            SwarmAgentSpec(
                id="editor",
                name="Executive Editor",
                role="Fact-Check & Executive Synthesis",
                model_tier="instant",
                system_prompt="Refine executive summary, verify consistency, and format key takeaways.",
                estimated_cost_usd=0.0008,
            ),
        ],
    ),
]


class SwarmCoordinator:
    """Orchestrates parallel multi-agent swarm dispatch, partial fault tolerance, and output merging."""

    def __init__(self, cases: Optional[List[SwarmCase]] = None):
        self.cases = cases or FEATURED_SWARM_CASES

    def list_cases(self) -> List[SwarmCase]:
        """Return available pre-configured swarm team cases."""
        return self.cases

    def get_case(self, case_id: str) -> Optional[SwarmCase]:
        """Get case template by ID."""
        return next((c for c in self.cases if c.id == case_id), None)

    def estimate_cost(
        self,
        agents: List[SwarmAgentSpec],
        model_tier: str = "instant",
    ) -> float:
        """Calculate total estimated swarm execution cost across all participating agents."""
        multiplier = 2.5 if model_tier in ("swarm-high", "k3", "reasoning") else 1.0
        total = sum(a.estimated_cost_usd for a in agents) * multiplier
        return round(total, 4)

    async def _execute_single_agent(
        self,
        agent: SwarmAgentSpec,
        prompt: str,
        model_tier: str,
    ) -> SwarmAgentProgress:
        """Execute a single agent within the swarm with timing, cost attribution, and fault isolation."""
        start = time.perf_counter()
        multiplier = 2.5 if model_tier in ("swarm-high", "k3", "reasoning") else 1.0
        cost = round(agent.estimated_cost_usd * multiplier, 4)

        try:
            # Simulate micro-agent task processing
            await asyncio.sleep(0.05)

            # Generate structured response with role context
            output = (
                f"### {agent.name} Output\n\n"
                f"**Role:** {agent.role}\n"
                f"**Analysis on:** *{prompt}*\n\n"
                f"- Evaluated core requirements and constraints.\n"
                f"- Formulated concrete recommendations for {agent.name.lower()} scope.\n"
                f"- Execution delivered on model tier `{model_tier}`."
            )
            elapsed = (time.perf_counter() - start) * 1000

            return SwarmAgentProgress(
                agent_id=agent.id,
                agent_name=agent.name,
                role=agent.role,
                model_tier=model_tier,
                status="completed",
                progress_percent=100,
                output=output,
                cost_usd=cost,
                execution_time_ms=round(elapsed, 2),
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("Swarm agent '%s' encountered error: %s", agent.name, e)
            return SwarmAgentProgress(
                agent_id=agent.id,
                agent_name=agent.name,
                role=agent.role,
                model_tier=model_tier,
                status="failed",
                progress_percent=0,
                output="",
                cost_usd=0.0,
                execution_time_ms=round(elapsed, 2),
                error=str(e),
            )

    async def run_swarm(
        self,
        prompt: str,
        agents: Optional[List[SwarmAgentSpec]] = None,
        case_id: Optional[str] = None,
        model_tier: str = "instant",
    ) -> SwarmRunResult:
        """Dispatch task to swarm in parallel, handle partial failures, and synthesize output."""
        start_all = time.perf_counter()
        swarm_id = f"swarm_{uuid.uuid4().hex[:8]}"

        # Resolve agent roster
        target_agents: List[SwarmAgentSpec] = []
        if agents:
            target_agents = agents
        elif case_id:
            c = self.get_case(case_id)
            if c:
                target_agents = c.agents
        if not target_agents:
            target_agents = self.cases[0].agents

        # Dispatch all agents concurrently
        tasks = [self._execute_single_agent(agent, prompt, model_tier) for agent in target_agents]
        agent_outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results: List[SwarmAgentProgress] = []
        for i, outcome in enumerate(agent_outcomes):
            if isinstance(outcome, Exception):
                spec = target_agents[i]
                processed_results.append(
                    SwarmAgentProgress(
                        agent_id=spec.id,
                        agent_name=spec.name,
                        role=spec.role,
                        model_tier=model_tier,
                        status="failed",
                        progress_percent=0,
                        output="",
                        cost_usd=0.0,
                        error=str(outcome),
                    )
                )
            else:
                processed_results.append(outcome)

        # Determine overall swarm status
        success_count = sum(1 for r in processed_results if r.status == "completed")
        if success_count == len(processed_results):
            overall_status = "completed"
        elif success_count > 0:
            overall_status = "partial_failure"
        else:
            overall_status = "failed"

        total_cost = sum(r.cost_usd for r in processed_results)
        total_time = (time.perf_counter() - start_all) * 1000

        # Synthesize aggregated output with attribution
        aggregated_sections: List[str] = [
            f"# 🐝 Swarm Execution Synthesis\n\n"
            f"**Task Prompt:** {prompt}\n\n"
            f"**Model Tier:** `{model_tier}` | **Status:** `{overall_status}` | "
            f"**Total Cost:** `${total_cost:.4f}` | **Execution Time:** `{total_time:.1f}ms`\n\n"
            f"---"
        ]

        for res in processed_results:
            if res.status == "completed":
                aggregated_sections.append(
                    f"\n## 👤 {res.agent_name} ({res.role})\n"
                    f"*Tier: {res.model_tier} | Cost: ${res.cost_usd:.4f} | Time: {res.execution_time_ms:.1f}ms*\n\n"
                    f"{res.output}\n"
                )
            else:
                aggregated_sections.append(
                    f"\n## ⚠️ {res.agent_name} ({res.role}) — Failed\n"
                    f"Error: {res.error or 'Unknown error occurred.'}\n"
                )

        aggregated_output = "\n".join(aggregated_sections)

        return SwarmRunResult(
            swarm_id=swarm_id,
            prompt=prompt,
            model_tier=model_tier,
            status=overall_status,
            agent_results=processed_results,
            aggregated_output=aggregated_output,
            total_cost_usd=round(total_cost, 4),
            total_time_ms=round(total_time, 2),
        )
