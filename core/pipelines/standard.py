import dspy
from core.pipelines.registry import register_pipeline


# -------------------------------------------------------------------------
# 1. Security Audit Pipeline
# -------------------------------------------------------------------------
class SecurityAuditSignature(dspy.Signature):
    """Audit source code for security vulnerabilities, secrets, and risk scoring."""

    code = dspy.InputField(desc="Source code to analyze")
    language = dspy.InputField(desc="Programming language (e.g., python, javascript)")
    vulnerabilities = dspy.OutputField(desc="List of detected security vulnerabilities or CWEs")
    risk_level = dspy.OutputField(desc="Overall risk rating (LOW, MEDIUM, HIGH, CRITICAL)")
    fix_recommendation = dspy.OutputField(desc="Recommended remediation steps")


@register_pipeline(
    name="security_audit",
    description="Audit source code for security vulnerabilities (SQLi, XSS, secret leaks) with risk scoring",
    inputs=["code", "language"],
    outputs=["vulnerabilities", "risk_level", "fix_recommendation"],
    tools=["ast_scanner"],
    guardrails=["code_injection_check", "secret_leak_check"],
    category="code",
    version="1.0.0",
)
class SecurityAuditPipeline(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.auditor = dspy.ChainOfThought(SecurityAuditSignature)

    def forward(self, code: str, language: str = "python") -> dspy.Prediction:
        return self.auditor(code=code, language=language)


# -------------------------------------------------------------------------
# 2. Code Lint Pipeline
# -------------------------------------------------------------------------
class CodeLintSignature(dspy.Signature):
    """Evaluate code against style guidelines, formatting, and PEP 8 standards."""

    code = dspy.InputField(desc="Source code to lint")
    rules = dspy.InputField(desc="Linting rules or style conventions to check against")
    lint_issues = dspy.OutputField(desc="Identified code style and formatting issues")
    style_score = dspy.OutputField(desc="Style quality score from 0 to 100")
    clean_code = dspy.OutputField(desc="Cleaned or reformatted code snippet")


@register_pipeline(
    name="code_lint",
    description="Evaluate code against style guidelines, formatting rules, and PEP 8 standards",
    inputs=["code", "rules"],
    outputs=["lint_issues", "style_score", "clean_code"],
    tools=["ruff_linter"],
    guardrails=["syntax_validation"],
    category="code",
    version="1.0.0",
)
class CodeLintPipeline(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.linter = dspy.ChainOfThought(CodeLintSignature)

    def forward(self, code: str, rules: str = "PEP 8") -> dspy.Prediction:
        return self.linter(code=code, rules=rules)


# -------------------------------------------------------------------------
# 3. Code Fix Pipeline
# -------------------------------------------------------------------------
class CodeFixSignature(dspy.Signature):
    """Generate repair code and a unified diff patch to resolve an issue."""

    code = dspy.InputField(desc="Original code containing errors or issues")
    issue_description = dspy.InputField(desc="Description of the bug or vulnerability to fix")
    fixed_code = dspy.OutputField(desc="Complete corrected source code")
    diff_patch = dspy.OutputField(desc="Unified diff representing the code modifications")
    explanation = dspy.OutputField(desc="Technical explanation of the applied resolution")


@register_pipeline(
    name="code_fix",
    description="Generate bug fixes, unified diff patches, and explanation for code issues",
    inputs=["code", "issue_description"],
    outputs=["fixed_code", "diff_patch", "explanation"],
    tools=["diff_engine", "ast_sanitizer"],
    guardrails=["ast_verification", "patch_sanitizer"],
    category="code",
    version="1.0.0",
)
class CodeFixPipeline(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.fixer = dspy.ChainOfThought(CodeFixSignature)

    def forward(self, code: str, issue_description: str) -> dspy.Prediction:
        return self.fixer(code=code, issue_description=issue_description)


# -------------------------------------------------------------------------
# 4. Email Draft Pipeline
# -------------------------------------------------------------------------
class EmailDraftSignature(dspy.Signature):
    """Draft professional email correspondence based on brief and tone requirements."""

    brief = dspy.InputField(desc="Key points, objective, or brief for the email")
    recipient = dspy.InputField(desc="Recipient name, role, or relationship context")
    tone = dspy.InputField(desc="Desired communication tone (e.g. formal, concise, warm)")
    subject = dspy.OutputField(desc="Engaging, clear email subject line")
    body = dspy.OutputField(desc="Complete formatted email body copy")
    call_to_action = dspy.OutputField(desc="Clear call-to-action or next step for the recipient")


@register_pipeline(
    name="email_draft",
    description="Draft professional email correspondence with tailored tone, subject line, and call-to-action",
    inputs=["brief", "recipient", "tone"],
    outputs=["subject", "body", "call_to_action"],
    tools=[],
    guardrails=["profanity_filter", "pii_redaction"],
    category="business",
    version="1.0.0",
)
class EmailDraftPipeline(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.drafter = dspy.ChainOfThought(EmailDraftSignature)

    def forward(self, brief: str, recipient: str, tone: str = "professional") -> dspy.Prediction:
        return self.drafter(brief=brief, recipient=recipient, tone=tone)


# -------------------------------------------------------------------------
# 5. Finance Extract Pipeline
# -------------------------------------------------------------------------
class FinanceExtractSignature(dspy.Signature):
    """Extract structured transactions, amounts, vendors, and taxes from financial documents."""

    document_text = dspy.InputField(desc="Receipt, invoice, or financial statement text")
    currency = dspy.InputField(desc="Currency symbol or ISO code (e.g. USD, EUR)")
    transactions = dspy.OutputField(desc="Structured list of line items with description and price")
    total_amount = dspy.OutputField(desc="Total calculated monetary amount")
    vendor = dspy.OutputField(desc="Identified merchant, company, or service provider name")
    tax = dspy.OutputField(desc="Identified tax or fee portion")


@register_pipeline(
    name="finance_extract",
    description="Extract structured financial transactions, vendors, amounts, and tax data from documents",
    inputs=["document_text", "currency"],
    outputs=["transactions", "total_amount", "vendor", "tax"],
    tools=["ocr_parser"],
    guardrails=["currency_format_check", "audit_log"],
    category="finance",
    version="1.0.0",
)
class FinanceExtractPipeline(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.extractor = dspy.ChainOfThought(FinanceExtractSignature)

    def forward(self, document_text: str, currency: str = "USD") -> dspy.Prediction:
        return self.extractor(document_text=document_text, currency=currency)


# -------------------------------------------------------------------------
# 6. Chapter Write Pipeline
# -------------------------------------------------------------------------
class ChapterWriteSignature(dspy.Signature):
    """Generate creative story chapters and narrative prose from outline and character arcs."""

    outline = dspy.InputField(desc="Plot beats and chapter outline")
    characters = dspy.InputField(desc="Characters active in this chapter and their motivations")
    setting = dspy.InputField(desc="World, scene environment, and atmospheric backdrop")
    target_word_count = dspy.InputField(desc="Approximate desired word count or pacing")
    chapter_title = dspy.OutputField(desc="Evocative chapter title")
    prose = dspy.OutputField(desc="Complete chapter narrative prose")
    scene_summary = dspy.OutputField(desc="Concise summary of state changes and narrative progress")


@register_pipeline(
    name="chapter_write",
    description="Generate creative fiction or non-fiction chapters from outlines, character arcs, and settings",
    inputs=["outline", "characters", "setting", "target_word_count"],
    outputs=["chapter_title", "prose", "scene_summary"],
    tools=[],
    guardrails=["content_safety_check"],
    category="creative",
    version="1.0.0",
)
class ChapterWritePipeline(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.writer = dspy.ChainOfThought(ChapterWriteSignature)

    def forward(
        self,
        outline: str,
        characters: str,
        setting: str,
        target_word_count: str = "1500",
    ) -> dspy.Prediction:
        return self.writer(
            outline=outline,
            characters=characters,
            setting=setting,
            target_word_count=target_word_count,
        )
