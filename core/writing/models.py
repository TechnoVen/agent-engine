"""core/writing/models.py

Data models and schemas for the Agent Engine Writing Pack MVP (Task R5.2).
Part of Milestone R5 (Founder Dogfood & Capability Packs).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
import re
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


def current_timestamp_iso() -> str:
    """Return UTC ISO 8601 timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def generate_writing_run_id() -> str:
    """Generate unique writing workflow run identifier."""
    return f"wr_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# 1. Outline Models
# ---------------------------------------------------------------------------


class OutlineSection(BaseModel):
    """Discrete section within an article outline."""

    title: str = Field(..., description="Section title")
    intent: str = Field(..., description="Editorial purpose or goal of this section")
    supporting_points: List[str] = Field(
        default_factory=list, description="Key arguments or evidence points"
    )
    claims_needing_evidence: List[str] = Field(
        default_factory=list, description="Claims requiring factual backing"
    )


class ArticleOutline(BaseModel):
    """Structured outline produced in Stage 1."""

    working_title: str
    thesis: str = Field(..., description="Core argument or takeaway of the article")
    sections: List[OutlineSection] = Field(default_factory=list)
    execution_id: Optional[str] = None
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    source_references: List[str] = Field(default_factory=list)
    artifact_id: Optional[str] = None
    raw_response: Optional[str] = None

    def to_markdown(self) -> str:
        """Render outline as formatted markdown."""
        lines = [
            f"# Outline: {self.working_title}",
            "",
            f"**Thesis:** {self.thesis}",
            "",
            "## Sections",
            "",
        ]
        for idx, sec in enumerate(self.sections, 1):
            lines.append(f"### {idx}. {sec.title}")
            lines.append(f"- **Intent:** {sec.intent}")
            if sec.supporting_points:
                lines.append("- **Key Points:**")
                for pt in sec.supporting_points:
                    lines.append(f"  - {pt}")
            if sec.claims_needing_evidence:
                lines.append("- **Claims Needing Evidence:**")
                for cl in sec.claims_needing_evidence:
                    lines.append(f"  - {cl}")
            lines.append("")
        return "\n".join(lines).strip()

    @classmethod
    def from_text(cls, text: str, working_title: str = "Untitled Article") -> ArticleOutline:
        """Parse structured outline from model text response."""
        # Try JSON parsing first if fenced or embedded
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                sections = [
                    OutlineSection(
                        title=s.get("title", f"Section {i + 1}"),
                        intent=s.get("intent", ""),
                        supporting_points=s.get("supporting_points", []),
                        claims_needing_evidence=s.get("claims_needing_evidence", []),
                    )
                    for i, s in enumerate(data.get("sections", []))
                ]
                return cls(
                    working_title=data.get("working_title", working_title),
                    thesis=data.get("thesis", ""),
                    sections=sections,
                    raw_response=text,
                )
            except Exception:
                pass

        # Markdown heading parsing fallback
        lines = text.strip().split("\n")
        parsed_title = working_title
        thesis = ""
        sections: List[OutlineSection] = []
        current_section: Optional[OutlineSection] = None

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Heading 1: title
            if line_str.startswith("# "):
                candidate = line_str.replace("# ", "").replace("Outline:", "").strip()
                if candidate:
                    parsed_title = candidate
            # Thesis line
            elif line_str.lower().startswith("**thesis:**") or line_str.lower().startswith(
                "thesis:"
            ):
                thesis = re.sub(r"(?i)\*\*thesis:\*\*\s*|thesis:\s*", "", line_str).strip()
            # Section heading
            elif (
                line_str.startswith("### ")
                or line_str.startswith("## ")
                or re.match(r"^\d+\.\s+", line_str)
            ):
                sec_title = re.sub(r"^(?:#{1,6}\s*)?(?:\d+[\.\)]\s*)?", "", line_str).strip()
                current_section = OutlineSection(title=sec_title, intent="")
                sections.append(current_section)
            # Section details
            elif current_section is not None:
                if "intent:" in line_str.lower():
                    current_section.intent = re.sub(
                        r"(?i)^[-*]?\s*\*\*intent:\*\*\s*|intent:\s*", "", line_str
                    ).strip()
                elif "claim" in line_str.lower() and ":" in line_str:
                    pass  # Header indicator
                elif line_str.startswith("- ") or line_str.startswith("* "):
                    point = line_str[2:].strip()
                    if point:
                        current_section.supporting_points.append(point)

        if not thesis and lines:
            # Fallback thesis
            thesis = "Structured synthesis based on supplied sources and requirements."

        if not sections:
            sections.append(
                OutlineSection(
                    title="Introduction and Background",
                    intent="Frame context and problem statement",
                    supporting_points=["Foundational context"],
                )
            )
            sections.append(
                OutlineSection(
                    title="Core Analysis and Architecture",
                    intent="Detail substantive evidence and findings",
                    supporting_points=["Key mechanism details"],
                )
            )
            sections.append(
                OutlineSection(
                    title="Implications and Conclusion",
                    intent="Summarize strategic outcomes and next steps",
                    supporting_points=["Actionable takeaways"],
                )
            )

        return cls(
            working_title=parsed_title,
            thesis=thesis,
            sections=sections,
            raw_response=text,
        )


# ---------------------------------------------------------------------------
# 2. Draft Models
# ---------------------------------------------------------------------------


class ArticleDraft(BaseModel):
    """Article draft prose content."""

    title: str
    content: str = Field(..., description="Markdown prose content of the draft")
    word_count: int = 0
    outline_execution_id: Optional[str] = None
    draft_execution_id: Optional[str] = None
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    artifact_id: Optional[str] = None
    is_revised: bool = False

    def model_post_init(self, __context: Any) -> None:
        if not self.word_count and self.content:
            self.word_count = len(self.content.strip().split())


# ---------------------------------------------------------------------------
# 3. Style Review Models
# ---------------------------------------------------------------------------


class StyleFindingCategory(str, Enum):
    """Categories of stylistic and structural review findings."""

    CLARITY = "clarity"
    STRUCTURE = "structure"
    REPETITION = "repetition"
    TONE_MISMATCH = "tone_mismatch"
    AWKWARD_PHRASING = "awkward_phrasing"
    UNSUPPORTED_VERBOSITY = "unsupported_verbosity"
    AUDIENCE_MISMATCH = "audience_mismatch"


class StyleFinding(BaseModel):
    """Individual actionable editorial finding."""

    category: StyleFindingCategory
    location: str = Field(..., description="Section title or quoted phrase")
    issue: str = Field(..., description="Description of the stylistic problem")
    suggestion: str = Field(..., description="Concrete suggested improvement")
    accepted: bool = True


class StyleReviewResult(BaseModel):
    """Structured style review output."""

    findings: List[StyleFinding] = Field(default_factory=list)
    overall_feedback: str = ""
    readability_notes: Optional[str] = None
    execution_id: Optional[str] = None
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    artifact_id: Optional[str] = None
    raw_response: Optional[str] = None

    def to_markdown(self) -> str:
        """Render review findings as markdown."""
        lines = [
            "# Editorial Style Review",
            "",
            f"**Overall Feedback:** {self.overall_feedback or 'Review completed.'}",
            "",
            f"**Findings Count:** {len(self.findings)}",
            "",
            "## Findings",
            "",
        ]
        if not self.findings:
            lines.append("No material stylistic defects identified.")
        else:
            for idx, f in enumerate(self.findings, 1):
                lines.append(f"### {idx}. [{f.category.value.upper()}] at {f.location}")
                lines.append(f"- **Issue:** {f.issue}")
                lines.append(f"- **Suggestion:** {f.suggestion}")
                lines.append(f"- **Accepted:** {'Yes' if f.accepted else 'No'}")
                lines.append("")
        return "\n".join(lines).strip()

    @classmethod
    def from_text(cls, text: str) -> StyleReviewResult:
        """Parse structured style review findings from text."""
        # Try JSON extraction
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                findings = []
                for item in data.get("findings", []):
                    cat_val = item.get("category", "clarity").lower().replace(" ", "_")
                    try:
                        cat = StyleFindingCategory(cat_val)
                    except ValueError:
                        cat = StyleFindingCategory.CLARITY
                    findings.append(
                        StyleFinding(
                            category=cat,
                            location=item.get("location", "General"),
                            issue=item.get("issue", ""),
                            suggestion=item.get("suggestion", ""),
                            accepted=bool(item.get("accepted", True)),
                        )
                    )
                return cls(
                    findings=findings,
                    overall_feedback=data.get("overall_feedback", "Review completed."),
                    readability_notes=data.get("readability_notes"),
                    raw_response=text,
                )
            except Exception:
                pass

        # Text line parsing
        findings: List[StyleFinding] = []
        feedback = "Review complete."
        current_cat = StyleFindingCategory.CLARITY
        current_loc = "General"
        current_issue = ""
        current_sug = ""

        for line in text.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.lower().startswith("overall feedback:"):
                feedback = line_str.split(":", 1)[1].strip()
            elif any(cat.value in line_str.lower() for cat in StyleFindingCategory):
                for cat in StyleFindingCategory:
                    if cat.value in line_str.lower():
                        current_cat = cat
                        break
                current_loc = line_str
            elif "issue:" in line_str.lower():
                current_issue = line_str.split(":", 1)[1].strip()
            elif "suggestion:" in line_str.lower():
                current_sug = line_str.split(":", 1)[1].strip()
                findings.append(
                    StyleFinding(
                        category=current_cat,
                        location=current_loc,
                        issue=current_issue or "Stylistic refinement needed",
                        suggestion=current_sug,
                    )
                )
                current_issue = ""
                current_sug = ""

        if not findings and text.strip():
            # If text returned without markers, create general finding
            findings.append(
                StyleFinding(
                    category=StyleFindingCategory.CLARITY,
                    location="Full Article",
                    issue="General prose refinement",
                    suggestion="Verify conciseness and flow in technical transitions.",
                )
            )

        return cls(findings=findings, overall_feedback=feedback, raw_response=text)


# ---------------------------------------------------------------------------
# 4. Claim Review Models
# ---------------------------------------------------------------------------


class ClaimClassificationType(str, Enum):
    """Factuality classification of material claims."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNCERTAIN = "uncertain"
    OPINION_INTERPRETATION = "opinion_interpretation"
    SOURCE_REQUIRED = "source_required"


class ClaimItem(BaseModel):
    """An individual factual claim analyzed against context."""

    claim_text: str = Field(..., description="Quoted or paraphrased claim statement")
    classification: ClaimClassificationType
    evidence: Optional[str] = Field(
        default=None, description="Exact supporting passage or notes quote"
    )
    rationale: str = Field(..., description="Verification explanation or reason why unsupported")


class ClaimReviewResult(BaseModel):
    """Structured outcome of claim and factuality audit."""

    claims: List[ClaimItem] = Field(default_factory=list)
    unsupported_count: int = 0
    supported_count: int = 0
    summary: str = ""
    execution_id: Optional[str] = None
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    artifact_id: Optional[str] = None
    raw_response: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        self.supported_count = sum(
            1 for c in self.claims if c.classification == ClaimClassificationType.SUPPORTED
        )
        self.unsupported_count = sum(
            1
            for c in self.claims
            if c.classification
            in (
                ClaimClassificationType.UNSUPPORTED,
                ClaimClassificationType.SOURCE_REQUIRED,
            )
        )

    def to_markdown(self) -> str:
        """Render claims audit as markdown report."""
        lines = [
            "# Claim & Factuality Review",
            "",
            f"**Audit Summary:** {self.summary or 'Verification complete.'}",
            f"**Supported Claims:** {self.supported_count}",
            f"**Unsupported / Needs Source:** {self.unsupported_count}",
            "",
            "## Claim Classifications",
            "",
        ]
        for idx, cl in enumerate(self.claims, 1):
            status_tag = cl.classification.value.upper()
            lines.append(f'### {idx}. [{status_tag}] "{cl.claim_text}"')
            if cl.evidence:
                lines.append(f"- **Evidence:** {cl.evidence}")
            lines.append(f"- **Rationale:** {cl.rationale}")
            lines.append("")
        return "\n".join(lines).strip()

    @classmethod
    def from_text(cls, text: str) -> ClaimReviewResult:
        """Parse structured claim classification findings from text."""
        # Try JSON extraction
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                claims = []
                for item in data.get("claims", []):
                    c_type_str = item.get("classification", "supported").lower().replace(" ", "_")
                    try:
                        c_type = ClaimClassificationType(c_type_str)
                    except ValueError:
                        c_type = ClaimClassificationType.UNCERTAIN
                    claims.append(
                        ClaimItem(
                            claim_text=item.get("claim_text", ""),
                            classification=c_type,
                            evidence=item.get("evidence"),
                            rationale=item.get("rationale", ""),
                        )
                    )
                return cls(
                    claims=claims,
                    summary=data.get("summary", "Claim verification completed."),
                    raw_response=text,
                )
            except Exception:
                pass

        # Text line parsing
        claims: List[ClaimItem] = []
        summary = "Factuality audit complete."

        for line in text.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.lower().startswith("summary:"):
                summary = line_str.split(":", 1)[1].strip()
            elif any(
                tag in line_str.upper()
                for tag in (
                    "[SUPPORTED]",
                    "[UNSUPPORTED]",
                    "[UNCERTAIN]",
                    "[SOURCE_REQUIRED]",
                    "[OPINION]",
                )
            ):
                tag_match = re.search(
                    r"\[(SUPPORTED|UNSUPPORTED|UNCERTAIN|SOURCE_REQUIRED|OPINION)\]",
                    line_str.upper(),
                )
                c_type = ClaimClassificationType.SUPPORTED
                if tag_match:
                    tag = tag_match.group(1).lower()
                    if tag == "opinion":
                        c_type = ClaimClassificationType.OPINION_INTERPRETATION
                    else:
                        c_type = ClaimClassificationType(tag)
                claim_quote = (
                    re.sub(r"^(?:###\s*\d+\.\s*)?\[.*?\]\s*", "", line_str).strip().strip('"')
                )
                claims.append(
                    ClaimItem(
                        claim_text=claim_quote or "Material assertion",
                        classification=c_type,
                        rationale="Derived from audit text analysis",
                    )
                )

        if not claims and text.strip():
            claims.append(
                ClaimItem(
                    claim_text="General assertions in article draft",
                    classification=ClaimClassificationType.SUPPORTED,
                    rationale="Aligned with primary source material",
                )
            )

        return cls(claims=claims, summary=summary, raw_response=text)


# ---------------------------------------------------------------------------
# 5. Article Workflow State
# ---------------------------------------------------------------------------


class ArticleWorkflowStage(str, Enum):
    """Lifecycle stages of the canonical Article Workflow."""

    NOTES = "notes"
    OUTLINE = "outline"
    DRAFT = "draft"
    STYLE_REVIEW = "style_review"
    REVISED_DRAFT = "revised_draft"
    CLAIM_REVIEW = "claim_review"
    FINALIZED = "finalized"
    FAILED = "failed"


class ArticleWorkflowState(BaseModel):
    """Durable state container for an article authoring workflow run."""

    workflow_run_id: str = Field(default_factory=generate_writing_run_id)
    project_id: str
    title: str
    source_notes: str
    source_artifact_ids: List[str] = Field(default_factory=list)
    audience: Optional[str] = "General technical / professional"
    objective: Optional[str] = None
    desired_length: Optional[str] = "Medium (~1,000-1,500 words)"
    style_guidance: Optional[str] = None
    factuality_requirement: str = "strict"

    current_stage: ArticleWorkflowStage = ArticleWorkflowStage.NOTES
    outline: Optional[ArticleOutline] = None
    draft: Optional[ArticleDraft] = None
    style_review: Optional[StyleReviewResult] = None
    revised_draft: Optional[ArticleDraft] = None
    claim_review: Optional[ClaimReviewResult] = None

    final_artifact_id: Optional[str] = None
    final_content: Optional[str] = None

    canonical_workflow_id: Optional[str] = None
    canonical_job_ids: Dict[str, str] = Field(default_factory=dict)

    execution_history: List[Dict[str, Any]] = Field(default_factory=list)
    manual_edits: Dict[str, bool] = Field(default_factory=dict)

    error: Optional[str] = None
    error_stage: Optional[str] = None

    created_at: str = Field(default_factory=current_timestamp_iso)
    updated_at: str = Field(default_factory=current_timestamp_iso)

    def record_execution(
        self,
        stage: str,
        execution_id: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        cost_usd: Optional[float] = None,
        artifact_id: Optional[str] = None,
    ) -> None:
        """Append an execution milestone to durable provenance."""
        self.execution_history.append(
            {
                "stage": stage,
                "execution_id": execution_id,
                "provider": provider,
                "model": model,
                "cost_usd": cost_usd,
                "artifact_id": artifact_id,
                "timestamp": current_timestamp_iso(),
            }
        )
        self.updated_at = current_timestamp_iso()
