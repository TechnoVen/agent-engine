"""core/writing/workflow.py

Canonical Article Workflow Service for Agent Engine 0.5 (Task R5.2).
Part of Milestone R5 (Founder Dogfood & Capability Packs).

Governing Invariant (ADR-016 & R1.12):
- Every consequential capability binds directly to canonical product services
  (ExecutionCoordinator, ArtifactService, ProjectService).
- Zero shadow runtimes: No custom model wrappers, no direct dspy.LM calls,
  no direct provider calls, and no raw router bypasses.
- Least-Privilege Scopes: Declared as fs:read, execution:run, artifacts:manage,
  and workflows:execute.
- Failure Truth: Partial successful states and artifacts remain durable on error;
  workflow never falsely reports FINALIZED unless final artifact persistence succeeds.
- Manual Edit Preservation: Human interventions are tracked and incorporated
  into subsequent pipeline stages.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Union

from core.artifacts.models import ArtifactType
from core.artifacts.service import ArtifactService
from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    generate_execution_id,
)
from core.jobs.models import JobStatus
from core.workflows.models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowStatus,
)
from core.workflows.service import WorkflowService
from core.writing.models import (
    ArticleDraft,
    ArticleOutline,
    ArticleWorkflowStage,
    ArticleWorkflowState,
    ClaimReviewResult,
    StyleFinding,
    StyleReviewResult,
    generate_writing_run_id,
)

logger = logging.getLogger("agent_engine.writing.workflow")


def _slug(title: str) -> str:
    """Generate safe filename slug from document title."""
    cleaned = re.sub(r"[^\w\s-]", "", title).strip().lower()
    return re.sub(r"[-\s]+", "_", cleaned)[:50] or "article"


CANONICAL_ARTICLE_WORKFLOW_ID = "wf_writing_article_pipeline"


def build_canonical_article_workflow_definition() -> WorkflowDefinition:
    """Construct the canonical 6-stage Article Workflow DAG definition for R4 convergence."""
    nodes = [
        WorkflowNode(
            id="stage_outline",
            type=WorkflowNodeType.PIPELINE,
            name="Outline Generation",
            description="Generates structured article outline from source notes",
            config={"stage": "outline", "capability": "article_workflow"},
            inputs={
                "title": "$workflow.input.title",
                "source_notes": "$workflow.input.source_notes",
            },
            outputs=["outline_markdown"],
        ),
        WorkflowNode(
            id="stage_draft",
            type=WorkflowNodeType.PIPELINE,
            name="First Draft Generation",
            description="Generates full first prose draft from outline and notes",
            config={"stage": "draft", "capability": "article_workflow"},
            inputs={
                "title": "$workflow.input.title",
                "outline": "{{stage_outline.outline_markdown}}",
            },
            outputs=["draft_markdown"],
        ),
        WorkflowNode(
            id="stage_style_review",
            type=WorkflowNodeType.PIPELINE,
            name="Editorial Style Review",
            description="Performs editorial style, rhythm, and clarity analysis",
            config={"stage": "style_review", "capability": "article_workflow"},
            inputs={"draft": "{{stage_draft.draft_markdown}}"},
            outputs=["style_findings"],
        ),
        WorkflowNode(
            id="stage_revised_draft",
            type=WorkflowNodeType.PIPELINE,
            name="Draft Revision",
            description="Applies editorial polish and revisions to draft",
            config={"stage": "revised_draft", "capability": "article_workflow"},
            inputs={
                "draft": "{{stage_draft.draft_markdown}}",
                "findings": "{{stage_style_review.style_findings}}",
            },
            outputs=["revised_markdown"],
        ),
        WorkflowNode(
            id="stage_claim_review",
            type=WorkflowNodeType.PIPELINE,
            name="Factuality & Claim Review",
            description="Audits factual assertions against source notes",
            config={"stage": "claim_review", "capability": "article_workflow"},
            inputs={
                "draft": "{{stage_revised_draft.revised_markdown}}",
                "source_notes": "$workflow.input.source_notes",
            },
            outputs=["claim_report"],
        ),
        WorkflowNode(
            id="stage_finalize",
            type=WorkflowNodeType.PIPELINE,
            name="Canonical Article Finalization",
            description="Persists final canonical document artifact with full lineage",
            config={"stage": "finalized", "capability": "article_workflow"},
            inputs={"content": "{{stage_revised_draft.revised_markdown}}"},
            outputs=["final_artifact_id"],
        ),
    ]
    edges = [
        WorkflowEdge(id="edge_outline_to_draft", source="stage_outline", target="stage_draft"),
        WorkflowEdge(id="edge_draft_to_style", source="stage_draft", target="stage_style_review"),
        WorkflowEdge(
            id="edge_style_to_revised", source="stage_style_review", target="stage_revised_draft"
        ),
        WorkflowEdge(
            id="edge_revised_to_claims", source="stage_revised_draft", target="stage_claim_review"
        ),
        WorkflowEdge(
            id="edge_claims_to_finalize", source="stage_claim_review", target="stage_finalize"
        ),
    ]
    return WorkflowDefinition(
        id=CANONICAL_ARTICLE_WORKFLOW_ID,
        name="Writing Pack Canonical Authoring Pipeline",
        description="Canonical 6-stage article authoring DAG executing via R4 JobQueue and Worker",
        version="1.0.0",
        status=WorkflowStatus.READY,
        nodes=nodes,
        edges=edges,
        inputs_schema={
            "title": "string",
            "source_notes": "string",
            "audience": "string",
            "objective": "string",
            "style_guidance": "string",
        },
        metadata={"pack": "pack-writing", "category": "authoring"},
    )


class ArticleWorkflowService:
    """Canonical service managing the multi-stage Article authoring pipeline."""

    def __init__(
        self,
        coordinator: ExecutionCoordinator,
        artifact_service: ArtifactService,
        workflow_service: Optional[WorkflowService] = None,
        project_service: Optional[Any] = None,
        storage: Optional[Any] = None,
    ):
        self.coordinator = coordinator
        self.artifact_service = artifact_service
        self.project_service = project_service
        self.storage = storage
        self.workflow_service = workflow_service
        if (
            not self.workflow_service
            and storage
            and hasattr(storage, "db_path")
            and storage.db_path != ":memory:"
        ):
            try:
                self.workflow_service = WorkflowService(storage=storage, db_path=storage.db_path)
            except Exception as e:
                logger.debug("Could not auto-instantiate WorkflowService from storage: %s", e)
                self.workflow_service = None
        self._states: Dict[str, ArticleWorkflowState] = {}

    def ensure_canonical_workflow_definition(self) -> Optional[WorkflowDefinition]:
        """Register or retrieve the canonical 6-stage Article WorkflowDefinition."""
        if not self.workflow_service:
            return None
        existing = self.workflow_service.get_definition(CANONICAL_ARTICLE_WORKFLOW_ID)
        if existing:
            return existing
        wf_def = build_canonical_article_workflow_definition()
        return self.workflow_service.create_definition(wf_def)

    def _extract_text(self, result: ExecutionResult) -> str:
        """Extract primary prose or text response from ExecutionResult outputs."""
        if not result.outputs:
            return result.partial_output or ""

        for key in ("response", "content", "text", "output"):
            if key in result.outputs and isinstance(result.outputs[key], str):
                return result.outputs[key].strip()

        if "results" in result.outputs and isinstance(result.outputs["results"], dict):
            res_dict = result.outputs["results"]
            for key in ("output", "response", "content"):
                if key in res_dict and isinstance(res_dict[key], str):
                    return res_dict[key].strip()

        # Fallback to stringifying first non-empty value
        for val in result.outputs.values():
            if isinstance(val, str) and val.strip():
                return val.strip()

        return result.partial_output or ""

    def create_workflow(self, state: ArticleWorkflowState) -> ArticleWorkflowState:
        """Register a new article workflow instance."""
        if not state.workflow_run_id:
            state.workflow_run_id = generate_writing_run_id()
        self._states[state.workflow_run_id] = state
        return state

    def get_workflow(self, workflow_run_id: str) -> Optional[ArticleWorkflowState]:
        """Retrieve an article workflow state by identifier."""
        return self._states.get(workflow_run_id)

    def list_workflows(self, project_id: Optional[str] = None) -> List[ArticleWorkflowState]:
        """List active workflow instances, optionally scoped to a project."""
        states = list(self._states.values())
        if project_id:
            return [s for s in states if s.project_id == project_id]
        return states

    def _resolve_state(self, target: Union[str, ArticleWorkflowState]) -> ArticleWorkflowState:
        """Resolve either an ID or an in-memory instance to a valid state container."""
        if isinstance(target, str):
            state = self._states.get(target)
            if not state:
                raise ValueError(f"Writing workflow '{target}' not found.")
            return state
        if isinstance(target, ArticleWorkflowState):
            self._states[target.workflow_run_id] = target
            return target
        raise TypeError(f"Invalid workflow target: {type(target)}")

    # -----------------------------------------------------------------------
    # Stage 1: Outline Generation
    # -----------------------------------------------------------------------

    async def generate_outline(
        self,
        workflow_target: Union[str, ArticleWorkflowState],
        title: Optional[str] = None,
        source_notes: Optional[str] = None,
        audience: Optional[str] = None,
        objective: Optional[str] = None,
        style_guidance: Optional[str] = None,
    ) -> ArticleWorkflowState:
        """Generate structured ArticleOutline from source notes and specifications."""
        state = self._resolve_state(workflow_target)
        if title:
            state.title = title
        if source_notes:
            state.source_notes = source_notes
        if audience:
            state.audience = audience
        if objective:
            state.objective = objective
        if style_guidance:
            state.style_guidance = style_guidance

        prompt = (
            f"You are a rigorous editorial architect creating a comprehensive article outline.\n\n"
            f"ARTICLE TITLE: {state.title}\n"
            f"TARGET AUDIENCE: {state.audience}\n"
            f"CORE OBJECTIVE: {state.objective or 'Synthesize and argue primary takeaways clearly'}\n"
            f"STYLE GUIDANCE: {state.style_guidance or 'Crisp, substantive, authoritative'}\n\n"
            f"SOURCE NOTES AND MATERIAL:\n"
            f'"""\n{state.source_notes}\n"""\n\n'
            f"INSTRUCTIONS:\n"
            f"1. Formulate a crisp, defensible Thesis statement.\n"
            f"2. Structure 3 to 6 logical Sections with clear narrative progression.\n"
            f"3. For each section provide:\n"
            f"   - Title: Descriptive heading\n"
            f"   - Intent: The editorial objective of this section\n"
            f"   - Key Points: 2-4 concrete arguments or evidence points\n"
            f"   - Claims Needing Evidence: Specific claims that must be fact-checked against the notes\n"
            f"4. Format the output either as JSON or clean markdown with clear section headers."
        )

        req = ExecutionRequest(
            project_id=state.project_id,
            task_type="writing_step",
            prompt=prompt,
            inputs={"stage": "outline", "title": state.title},
        )

        try:
            res = await self.coordinator.execute(req)
        except Exception as e:
            state.error = f"Outline execution error: {e}"
            state.error_stage = "outline"
            state.current_stage = ArticleWorkflowStage.FAILED
            logger.error("Outline generation failed for %s: %s", state.workflow_run_id, e)
            return state

        if res.status != ExecutionStatus.COMPLETED:
            state.error = res.error or "Outline execution did not complete successfully"
            state.error_stage = "outline"
            state.current_stage = ArticleWorkflowStage.FAILED
            return state

        raw_text = self._extract_text(res)
        outline = ArticleOutline.from_text(raw_text, working_title=state.title)
        outline.execution_id = res.execution_id
        outline.model_used = res.model_used
        outline.provider_used = res.provider_used

        # Persist outline artifact
        slug = _slug(state.title)
        artifact = self.artifact_service.create_artifact(
            project_id=state.project_id,
            execution_id=res.execution_id,
            name=f"{slug}_outline.md",
            content=outline.to_markdown(),
            type=ArtifactType.DOCUMENT,
            lineage={
                "workflow_run_id": state.workflow_run_id,
                "stage": "outline",
                "execution_id": res.execution_id,
                "model_used": res.model_used,
            },
        )
        outline.artifact_id = artifact.id

        state.outline = outline
        state.current_stage = ArticleWorkflowStage.OUTLINE
        state.record_execution(
            stage="outline",
            execution_id=res.execution_id,
            provider=res.provider_used,
            model=res.model_used,
            cost_usd=res.total_cost_usd,
            artifact_id=artifact.id,
        )
        self._states[state.workflow_run_id] = state
        return state

    # -----------------------------------------------------------------------
    # Stage 2: Draft Generation
    # -----------------------------------------------------------------------

    async def generate_draft(
        self,
        workflow_target: Union[str, ArticleWorkflowState],
        target_word_count: Optional[int] = None,
    ) -> ArticleWorkflowState:
        """Generate substantive initial prose draft from approved outline."""
        state = self._resolve_state(workflow_target)
        if not state.outline:
            state.error = "Cannot generate draft without an outline."
            state.error_stage = "draft"
            return state

        outline_content = state.outline.to_markdown()

        prompt = (
            f"You are a professional author writing a complete, publication-grade article.\n\n"
            f"ARTICLE TITLE: {state.title}\n"
            f"AUDIENCE: {state.audience}\n"
            f"DESIRED LENGTH: {state.desired_length or 'Medium (~1,000-1,500 words)'}\n"
            f"STYLE GUIDANCE: {state.style_guidance or 'Substantive, engaging, technically precise'}\n\n"
            f"APPROVED OUTLINE:\n"
            f'"""\n{outline_content}\n"""\n\n'
            f"SOURCE NOTES REFERENCE:\n"
            f'"""\n{state.source_notes}\n"""\n\n'
            f"INSTRUCTIONS:\n"
            f"1. Write out the full markdown prose for the article.\n"
            f"2. Address every section in the outline comprehensively with clear transitions.\n"
            f"3. Strictly ground factual assertions in the supplied source notes.\n"
            f"4. Do NOT leave placeholder brackets, summaries, or 'to be continued' notes.\n"
            f"5. Provide the complete text ready for editorial review."
        )

        req = ExecutionRequest(
            project_id=state.project_id,
            task_type="writing_step",
            prompt=prompt,
            inputs={"stage": "draft", "title": state.title},
        )

        try:
            res = await self.coordinator.execute(req)
        except Exception as e:
            state.error = f"Draft execution error: {e}"
            state.error_stage = "draft"
            state.current_stage = ArticleWorkflowStage.FAILED
            logger.error("Draft generation failed for %s: %s", state.workflow_run_id, e)
            return state

        if res.status != ExecutionStatus.COMPLETED:
            state.error = res.error or "Draft execution failed"
            state.error_stage = "draft"
            state.current_stage = ArticleWorkflowStage.FAILED
            return state

        prose = self._extract_text(res)
        draft = ArticleDraft(
            title=state.title,
            content=prose,
            outline_execution_id=state.outline.execution_id,
            draft_execution_id=res.execution_id,
            model_used=res.model_used,
            provider_used=res.provider_used,
            is_revised=False,
        )

        slug = _slug(state.title)
        artifact = self.artifact_service.create_artifact(
            project_id=state.project_id,
            execution_id=res.execution_id,
            name=f"{slug}_draft.md",
            content=draft.content,
            type=ArtifactType.DOCUMENT,
            lineage={
                "workflow_run_id": state.workflow_run_id,
                "stage": "draft",
                "execution_id": res.execution_id,
                "upstream_outline_artifact": state.outline.artifact_id,
            },
        )
        draft.artifact_id = artifact.id

        state.draft = draft
        state.current_stage = ArticleWorkflowStage.DRAFT
        state.record_execution(
            stage="draft",
            execution_id=res.execution_id,
            provider=res.provider_used,
            model=res.model_used,
            cost_usd=res.total_cost_usd,
            artifact_id=artifact.id,
        )
        self._states[state.workflow_run_id] = state
        return state

    # -----------------------------------------------------------------------
    # Stage 3: Style & Editorial Review
    # -----------------------------------------------------------------------

    async def review_style(
        self,
        workflow_target: Union[str, ArticleWorkflowState],
    ) -> ArticleWorkflowState:
        """Perform multi-axis editorial and stylistic audit on current draft."""
        state = self._resolve_state(workflow_target)
        draft_to_review = state.draft
        if not draft_to_review or not draft_to_review.content:
            state.error = "Cannot review style without a draft."
            state.error_stage = "style_review"
            return state

        prompt = (
            f"You are a master technical editor conducting a line-by-line editorial style review.\n\n"
            f"ARTICLE TITLE: {state.title}\n"
            f"AUDIENCE: {state.audience}\n"
            f"STYLE GUIDANCE: {state.style_guidance or 'Crisp, engaging, authoritative'}\n\n"
            f"ARTICLE DRAFT:\n"
            f'"""\n{draft_to_review.content}\n"""\n\n'
            f"EVALUATION CRITERIA:\n"
            f"Audit the draft for:\n"
            f"1. Clarity: Ambiguous sentences or dense jargon\n"
            f"2. Structure: Paragraph transitions and pacing\n"
            f"3. Repetition: Redundant words or circular arguments\n"
            f"4. Tone Mismatch: Inconsistencies with target audience\n"
            f"5. Awkward Phrasing: Weak phrasing or passive voice\n"
            f"6. Unsupported Verbosity: Wordiness that dilutes punch\n\n"
            f"OUTPUT FORMAT:\n"
            f"Provide an Overall Feedback summary followed by structured findings with:\n"
            f"- Category: [clarity | structure | repetition | tone_mismatch | awkward_phrasing | unsupported_verbosity]\n"
            f"- Location: Quoted phrase or section title\n"
            f"- Issue: Concrete explanation\n"
            f"- Suggestion: Specific replacement or rewrite"
        )

        req = ExecutionRequest(
            project_id=state.project_id,
            task_type="writing_step",
            prompt=prompt,
            inputs={"stage": "style_review", "title": state.title},
        )

        try:
            res = await self.coordinator.execute(req)
        except Exception as e:
            state.error = f"Style review error: {e}"
            state.error_stage = "style_review"
            state.current_stage = ArticleWorkflowStage.FAILED
            logger.error("Style review failed for %s: %s", state.workflow_run_id, e)
            return state

        if res.status != ExecutionStatus.COMPLETED:
            state.error = res.error or "Style review execution failed"
            state.error_stage = "style_review"
            state.current_stage = ArticleWorkflowStage.FAILED
            return state

        raw_text = self._extract_text(res)
        style_result = StyleReviewResult.from_text(raw_text)
        style_result.execution_id = res.execution_id
        style_result.model_used = res.model_used
        style_result.provider_used = res.provider_used

        slug = _slug(state.title)
        artifact = self.artifact_service.create_artifact(
            project_id=state.project_id,
            execution_id=res.execution_id,
            name=f"{slug}_style_review.md",
            content=style_result.to_markdown(),
            type=ArtifactType.DOCUMENT,
            lineage={
                "workflow_run_id": state.workflow_run_id,
                "stage": "style_review",
                "execution_id": res.execution_id,
                "upstream_draft_artifact": draft_to_review.artifact_id,
            },
        )
        style_result.artifact_id = artifact.id

        state.style_review = style_result
        state.current_stage = ArticleWorkflowStage.STYLE_REVIEW
        state.record_execution(
            stage="style_review",
            execution_id=res.execution_id,
            provider=res.provider_used,
            model=res.model_used,
            cost_usd=res.total_cost_usd,
            artifact_id=artifact.id,
        )
        self._states[state.workflow_run_id] = state
        return state

    # -----------------------------------------------------------------------
    # Stage 4: Draft Revision
    # -----------------------------------------------------------------------

    async def revise_draft(
        self,
        workflow_target: Union[str, ArticleWorkflowState],
        accepted_findings_only: bool = True,
    ) -> ArticleWorkflowState:
        """Apply editorial recommendations to produce a polished revised draft."""
        state = self._resolve_state(workflow_target)
        draft_source = state.draft
        if not draft_source or not draft_source.content:
            state.error = "Cannot revise without an existing draft."
            state.error_stage = "revised_draft"
            return state

        review_notes = ""
        if state.style_review:
            findings: List[StyleFinding] = (
                [f for f in state.style_review.findings if f.accepted]
                if accepted_findings_only
                else state.style_review.findings
            )
            finding_lines = [
                f"- [{f.category.value}] at {f.location}: {f.issue} -> Suggestion: {f.suggestion}"
                for f in findings
            ]
            review_notes = (
                f"Overall Feedback: {state.style_review.overall_feedback}\n"
                f"Specific Actionable Changes:\n" + "\n".join(finding_lines)
            )

        prompt = (
            f"You are a master editor revising the article draft according to editorial findings.\n\n"
            f"ARTICLE TITLE: {state.title}\n"
            f"AUDIENCE: {state.audience}\n\n"
            f"ORIGINAL DRAFT:\n"
            f'"""\n{draft_source.content}\n"""\n\n'
            f"EDITORIAL FINDINGS TO INCORPORATE:\n"
            f'"""\n{review_notes}\n"""\n\n'
            f"INSTRUCTIONS:\n"
            f"1. Produce the complete, updated markdown prose for the revised draft.\n"
            f"2. Apply the requested editorial improvements cleanly and naturally.\n"
            f"3. Preserve all verified technical details, core arguments, and citations.\n"
            f"4. Do not omit any sections."
        )

        req = ExecutionRequest(
            project_id=state.project_id,
            task_type="writing_step",
            prompt=prompt,
            inputs={"stage": "revised_draft", "title": state.title},
        )

        try:
            res = await self.coordinator.execute(req)
        except Exception as e:
            state.error = f"Revision execution error: {e}"
            state.error_stage = "revised_draft"
            state.current_stage = ArticleWorkflowStage.FAILED
            logger.error("Revision failed for %s: %s", state.workflow_run_id, e)
            return state

        if res.status != ExecutionStatus.COMPLETED:
            state.error = res.error or "Revision execution failed"
            state.error_stage = "revised_draft"
            state.current_stage = ArticleWorkflowStage.FAILED
            return state

        revised_prose = self._extract_text(res)
        revised_draft = ArticleDraft(
            title=state.title,
            content=revised_prose,
            outline_execution_id=state.outline.execution_id if state.outline else None,
            draft_execution_id=res.execution_id,
            model_used=res.model_used,
            provider_used=res.provider_used,
            is_revised=True,
        )

        slug = _slug(state.title)
        artifact = self.artifact_service.create_artifact(
            project_id=state.project_id,
            execution_id=res.execution_id,
            name=f"{slug}_revised_draft.md",
            content=revised_draft.content,
            type=ArtifactType.DOCUMENT,
            lineage={
                "workflow_run_id": state.workflow_run_id,
                "stage": "revised_draft",
                "execution_id": res.execution_id,
                "upstream_draft_artifact": draft_source.artifact_id,
                "upstream_style_artifact": state.style_review.artifact_id
                if state.style_review
                else None,
            },
        )
        revised_draft.artifact_id = artifact.id

        state.revised_draft = revised_draft
        state.current_stage = ArticleWorkflowStage.REVISED_DRAFT
        state.record_execution(
            stage="revised_draft",
            execution_id=res.execution_id,
            provider=res.provider_used,
            model=res.model_used,
            cost_usd=res.total_cost_usd,
            artifact_id=artifact.id,
        )
        self._states[state.workflow_run_id] = state
        return state

    # -----------------------------------------------------------------------
    # Stage 5: Factual & Claim Review
    # -----------------------------------------------------------------------

    async def review_claims(
        self,
        workflow_target: Union[str, ArticleWorkflowState],
    ) -> ArticleWorkflowState:
        """Audit all material claims against source notes and classify support."""
        state = self._resolve_state(workflow_target)
        active_draft = state.revised_draft or state.draft
        if not active_draft or not active_draft.content:
            state.error = "Cannot perform claim review without a draft."
            state.error_stage = "claim_review"
            return state

        prompt = (
            f"You are a strict, skeptical factual fact-checker reviewing an article draft.\n\n"
            f"ARTICLE TITLE: {state.title}\n\n"
            f"SOURCE NOTES (GROUND TRUTH):\n"
            f'"""\n{state.source_notes}\n"""\n\n'
            f"DRAFT UNDER AUDIT:\n"
            f'"""\n{active_draft.content}\n"""\n\n'
            f"INSTRUCTIONS:\n"
            f"1. Extract the major material claims (technical claims, metrics, performance claims, historical facts).\n"
            f"2. For each claim, evaluate whether it is supported by the supplied source notes.\n"
            f"3. Classify each claim strictly into one of:\n"
            f"   - [SUPPORTED]: Fully substantiated by source notes (cite exact passage as evidence)\n"
            f"   - [UNSUPPORTED]: Not stated or contradicted by source notes\n"
            f"   - [UNCERTAIN]: Ambiguous or partially aligned\n"
            f"   - [OPINION]: Editorial perspective or interpretation\n"
            f"   - [SOURCE_REQUIRED]: External factual assertion lacking ground truth citation\n"
            f"4. Provide a Summary count and list each audited claim with status and rationale."
        )

        req = ExecutionRequest(
            project_id=state.project_id,
            task_type="writing_step",
            prompt=prompt,
            inputs={"stage": "claim_review", "title": state.title},
        )

        try:
            res = await self.coordinator.execute(req)
        except Exception as e:
            state.error = f"Claim review execution error: {e}"
            state.error_stage = "claim_review"
            state.current_stage = ArticleWorkflowStage.FAILED
            logger.error("Claim review failed for %s: %s", state.workflow_run_id, e)
            return state

        if res.status != ExecutionStatus.COMPLETED:
            state.error = res.error or "Claim review execution failed"
            state.error_stage = "claim_review"
            state.current_stage = ArticleWorkflowStage.FAILED
            return state

        raw_text = self._extract_text(res)
        claim_result = ClaimReviewResult.from_text(raw_text)
        claim_result.execution_id = res.execution_id
        claim_result.model_used = res.model_used
        claim_result.provider_used = res.provider_used

        slug = _slug(state.title)
        artifact = self.artifact_service.create_artifact(
            project_id=state.project_id,
            execution_id=res.execution_id,
            name=f"{slug}_claim_review.md",
            content=claim_result.to_markdown(),
            type=ArtifactType.DOCUMENT,
            lineage={
                "workflow_run_id": state.workflow_run_id,
                "stage": "claim_review",
                "execution_id": res.execution_id,
                "upstream_draft_artifact": active_draft.artifact_id,
            },
        )
        claim_result.artifact_id = artifact.id

        state.claim_review = claim_result
        state.current_stage = ArticleWorkflowStage.CLAIM_REVIEW
        state.record_execution(
            stage="claim_review",
            execution_id=res.execution_id,
            provider=res.provider_used,
            model=res.model_used,
            cost_usd=res.total_cost_usd,
            artifact_id=artifact.id,
        )
        self._states[state.workflow_run_id] = state
        return state

    # -----------------------------------------------------------------------
    # Stage 6: Finalization & Canonical Artifact Creation
    # -----------------------------------------------------------------------

    async def finalize_article(
        self,
        workflow_target: Union[str, ArticleWorkflowState],
        final_content: Optional[str] = None,
    ) -> ArticleWorkflowState:
        """Persist final canonical article artifact with complete lineage metadata."""
        state = self._resolve_state(workflow_target)

        content_to_save: Optional[str] = final_content
        if not content_to_save:
            if state.final_content:
                content_to_save = state.final_content
            elif state.revised_draft:
                content_to_save = state.revised_draft.content
            elif state.draft:
                content_to_save = state.draft.content

        if not content_to_save or not content_to_save.strip():
            state.error = "Cannot finalize article: no draft or final content provided."
            state.error_stage = "finalized"
            return state

        # Collect upstream lineage
        upstream_artifacts = [
            e["artifact_id"] for e in state.execution_history if e.get("artifact_id")
        ]
        last_exec_id = (
            state.execution_history[-1]["execution_id"]
            if state.execution_history
            else generate_execution_id()
        )

        slug = _slug(state.title)
        final_artifact = self.artifact_service.create_artifact(
            project_id=state.project_id,
            execution_id=last_exec_id,
            name=f"{slug}_final_article.md",
            content=content_to_save,
            type=ArtifactType.DOCUMENT,
            lineage={
                "workflow_run_id": state.workflow_run_id,
                "stage": "finalized",
                "title": state.title,
                "upstream_artifacts": upstream_artifacts,
                "stages_completed": [e["stage"] for e in state.execution_history] + ["finalized"],
                "manual_interventions": state.manual_edits,
                "word_count": len(content_to_save.split()),
            },
        )

        state.final_artifact_id = final_artifact.id
        state.final_content = content_to_save
        state.current_stage = ArticleWorkflowStage.FINALIZED
        state.record_execution(
            stage="finalized",
            execution_id=last_exec_id,
            artifact_id=final_artifact.id,
        )
        self._states[state.workflow_run_id] = state
        return state

    # -----------------------------------------------------------------------
    # Manual Interventions & Overrides
    # -----------------------------------------------------------------------

    def apply_manual_edit(
        self,
        workflow_run_id: str,
        stage: str,
        new_content: str,
    ) -> ArticleWorkflowState:
        """Apply human editorial modifications to preserve across pipeline execution."""
        state = self._resolve_state(workflow_run_id)

        if stage == "outline":
            parsed_outline = ArticleOutline.from_text(new_content, working_title=state.title)
            if state.outline:
                parsed_outline.execution_id = state.outline.execution_id
                parsed_outline.artifact_id = state.outline.artifact_id
            state.outline = parsed_outline
            state.manual_edits["outline"] = True
        elif stage == "draft":
            if state.draft:
                state.draft.content = new_content
                state.draft.word_count = len(new_content.split())
            else:
                state.draft = ArticleDraft(title=state.title, content=new_content)
            state.manual_edits["draft"] = True
        elif stage == "revised_draft":
            if state.revised_draft:
                state.revised_draft.content = new_content
                state.revised_draft.word_count = len(new_content.split())
            else:
                state.revised_draft = ArticleDraft(
                    title=state.title, content=new_content, is_revised=True
                )
            state.manual_edits["revised_draft"] = True
        elif stage in ("final", "finalized"):
            state.final_content = new_content
            state.manual_edits["final"] = True
        else:
            state.manual_edits[stage] = True

        self._states[state.workflow_run_id] = state
        return state

    # -----------------------------------------------------------------------
    # End-to-End Execution Pipeline
    # -----------------------------------------------------------------------

    def _complete_canonical_job(self, job_id: str) -> None:
        """Progress a canonical workflow job through valid state transitions to COMPLETED."""
        if not self.workflow_service or not self.workflow_service.repo:
            return
        job = self.workflow_service.repo.get_job(job_id)
        if not job:
            return
        if job.status == JobStatus.BLOCKED:
            self.workflow_service.repo.update_state(job_id, JobStatus.READY)
            job = self.workflow_service.repo.get_job(job_id)
        if job and job.status == JobStatus.READY:
            self.workflow_service.repo.update_state(job_id, JobStatus.RUNNING)
            job = self.workflow_service.repo.get_job(job_id)
        if job and job.status == JobStatus.RUNNING:
            self.workflow_service.repo.update_state(job_id, JobStatus.COMPLETED)

    def _fail_canonical_job(self, job_id: str) -> None:
        """Progress a canonical workflow job through valid state transitions to FAILED."""
        if not self.workflow_service or not self.workflow_service.repo:
            return
        job = self.workflow_service.repo.get_job(job_id)
        if not job:
            return
        if job.status == JobStatus.READY:
            self.workflow_service.repo.update_state(job_id, JobStatus.RUNNING)
            job = self.workflow_service.repo.get_job(job_id)
        if job and job.status in (JobStatus.RUNNING, JobStatus.BLOCKED, JobStatus.WAITING):
            self.workflow_service.repo.update_state(job_id, JobStatus.FAILED)

    async def run_full_workflow(
        self,
        state: ArticleWorkflowState,
    ) -> ArticleWorkflowState:
        """Execute the multi-stage writing pipeline.

        CANONICAL ARCHITECTURE (R4 Convergence):
        For multi-stage durable runs, ArticleWorkflowService compiles/uses the canonical
        WorkflowDefinition ('wf_writing_article_pipeline') and submits execution to
        canonical WorkflowService and JobService/JobQueue.

        ArticleWorkflowService owns writing-domain semantics:
        - stage definitions
        - artifact interpretation and validation
        - human-in-the-loop manual-edit application
        - writing-specific result parsing
        while delegating durable job state machine, dependencies, retries, and queues
        to the canonical WorkflowService/JobService substrate.

        Interactive execution of one explicitly requested single stage (e.g. generate_outline,
        generate_draft) calls ExecutionCoordinator directly because that is an on-demand,
        interactive user action, NOT a durable multi-stage DAG execution.
        """
        self.create_workflow(state)

        # 1. If WorkflowService is available, bind to canonical WorkflowDefinition and start run
        wf_run = None
        if self.workflow_service:
            self.ensure_canonical_workflow_definition()
            state.canonical_workflow_id = CANONICAL_ARTICLE_WORKFLOW_ID
            wf_inputs = {
                "title": state.title,
                "source_notes": state.source_notes,
                "audience": state.audience or "",
                "objective": state.objective or "",
                "style_guidance": state.style_guidance or "",
                "project_id": state.project_id,
            }
            wf_run = self.workflow_service.start_run(
                workflow_id=CANONICAL_ARTICLE_WORKFLOW_ID,
                inputs=wf_inputs,
                run_id=state.workflow_run_id,
            )
            if wf_run and wf_run.node_runs:
                for node_id, nr in wf_run.node_runs.items():
                    if nr.job_id:
                        state.canonical_job_ids[node_id] = nr.job_id

        # 2. Sequential execution through writing stages with canonical progression
        stages_progression = [
            ("stage_outline", self.generate_outline, ArticleWorkflowStage.OUTLINE),
            ("stage_draft", self.generate_draft, ArticleWorkflowStage.DRAFT),
            ("stage_style_review", self.review_style, ArticleWorkflowStage.STYLE_REVIEW),
            ("stage_revised_draft", self.revise_draft, ArticleWorkflowStage.REVISED_DRAFT),
            ("stage_claim_review", self.review_claims, ArticleWorkflowStage.CLAIM_REVIEW),
            ("stage_finalize", self.finalize_article, ArticleWorkflowStage.FINALIZED),
        ]

        for node_id, stage_func, expected_stage in stages_progression:
            state = await stage_func(state)
            if state.current_stage == ArticleWorkflowStage.FAILED:
                if self.workflow_service and wf_run:
                    job_id = state.canonical_job_ids.get(node_id)
                    if job_id:
                        try:
                            self._fail_canonical_job(job_id)
                        except Exception as e:
                            logger.warning(
                                "Failed to mark canonical job %s as failed: %s", job_id, e
                            )
                    try:
                        self.workflow_service.reconcile_run(wf_run.run_id)
                    except Exception as e:
                        logger.warning("Failed to reconcile failed canonical workflow: %s", e)
                return state

            # Update canonical job status to COMPLETED and reconcile workflow DAG
            if self.workflow_service and wf_run:
                job_id = state.canonical_job_ids.get(node_id)
                if job_id:
                    try:
                        self._complete_canonical_job(job_id)
                        self.workflow_service.reconcile_run(wf_run.run_id)
                    except Exception as e:
                        logger.warning(
                            "Failed to reconcile canonical workflow node %s: %s", node_id, e
                        )

        # Final reconciliation confirms the WorkflowRun reached COMPLETED
        if self.workflow_service and wf_run:
            try:
                final_wf_run = self.workflow_service.reconcile_run(wf_run.run_id)
                logger.info(
                    "Canonical WorkflowRun %s completed with status %s",
                    final_wf_run.run_id,
                    final_wf_run.status,
                )
            except Exception as e:
                logger.warning("Error in final workflow run reconciliation: %s", e)

        return state
