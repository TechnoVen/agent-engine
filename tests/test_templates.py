import json

from core.engine import LowCodeAgent, NodeConfig
from core.templates import SkillTemplate, TemplateManager, load_template_agent
from server.mcp_server import execute_skill_template, list_skill_templates
from skills.dspy_template_skill import list_available_skills


def test_skill_template_model_and_json():
    """Verify that SkillTemplate models serialize and deserialize correctly."""
    template = SkillTemplate(
        id="test_summarizer",
        name="Test Summarizer",
        description="Summarize any text input concisely.",
        category="Test",
        tags=["test", "summary"],
        inputs={"text": "Input raw text"},
        outputs={"summary": "Concise summary output"},
        reasoning_type="cot",
        sample_inputs={"text": "Hello world from test."},
    )

    json_str = template.to_json()
    assert "test_summarizer" in json_str
    assert "Concise summary output" in json_str

    loaded = SkillTemplate(**json.loads(json_str))
    assert loaded.id == "test_summarizer"
    assert loaded.name == "Test Summarizer"
    assert loaded.inputs["text"] == "Input raw text"


def test_skill_template_to_node_config():
    """Verify conversion between SkillTemplate and NodeConfig."""
    template = SkillTemplate(
        id="sql_gen",
        name="SQL Generator",
        description="Convert question to SQL.",
        inputs=["question", "schema"],
        outputs=["sql"],
        reasoning_type="predict",
    )

    node_config = template.to_node_config()
    assert isinstance(node_config, NodeConfig)
    assert node_config.name == "SQL Generator"
    assert node_config.reasoning_type == "predict"
    assert "question" in node_config.inputs
    assert "sql" in node_config.outputs

    # Test reverse conversion
    reconstructed = SkillTemplate.from_node_config(node_config, template_id="sql_gen_2")
    assert reconstructed.id == "sql_gen_2"
    assert reconstructed.name == "SQL Generator"


def test_template_to_signature_and_agent():
    """Verify that SkillTemplate dynamically constructs dspy.Signature and LowCodeAgent."""
    template = SkillTemplate(
        id="sentiment_analyzer",
        name="SentimentAnalyzer",
        description="Classify text sentiment.",
        inputs={"sentence": "Input sentence"},
        outputs={"sentiment": "Positive, Negative, or Neutral"},
        reasoning_type="cot",
    )

    sig = template.to_signature()
    assert hasattr(sig, "fields")
    assert "sentence" in sig.fields
    assert "sentiment" in sig.fields

    agent = template.create_agent()
    assert isinstance(agent, LowCodeAgent)
    assert repr(agent).startswith("<LowCodeAgent")


def test_discover_prebuilt_templates():
    """Verify that TemplateManager discovers the 3 pre-built templates in configs/templates/."""
    templates = TemplateManager.list_templates()
    template_ids = {t.id for t in templates}

    assert "summarize_meeting_notes" in template_ids
    assert "weekly_report_jira_notion" in template_ids
    assert "generate_sql_from_nl" in template_ids

    meeting_tmpl = TemplateManager.get_template("summarize_meeting_notes")
    assert meeting_tmpl is not None
    assert meeting_tmpl.category == "Productivity"
    assert "meeting_notes" in meeting_tmpl.inputs
    assert "executive_summary" in meeting_tmpl.outputs

    sql_tmpl = TemplateManager.get_template("generate_sql_from_nl")
    assert sql_tmpl is not None
    assert sql_tmpl.category == "Data"
    assert "natural_language_query" in sql_tmpl.inputs

    weekly_tmpl = TemplateManager.get_template("weekly_report_jira_notion")
    assert weekly_tmpl is not None
    assert weekly_tmpl.category == "Engineering"
    assert "completed_issues" in weekly_tmpl.inputs


def test_template_crud_in_temp_dir(tmp_path):
    """Verify saving, loading, and deleting templates in custom directory."""
    temp_dir = tmp_path / "custom_templates"
    temp_dir.mkdir()

    tmpl = SkillTemplate(
        id="email_drafter",
        name="Email Drafter",
        description="Draft professional email replies.",
        inputs=["incoming_email", "intent"],
        outputs=["reply_draft"],
        category="Communication",
    )

    saved_file = TemplateManager.save_template(tmpl, dir_path=temp_dir)
    assert saved_file.exists()
    assert saved_file.name == "email_drafter.json"

    loaded = TemplateManager.get_template("email_drafter", dir_path=temp_dir)
    assert loaded is not None
    assert loaded.name == "Email Drafter"

    # Test list
    all_tmpls = TemplateManager.list_templates(dir_path=temp_dir)
    assert len(all_tmpls) == 1

    # Test delete
    deleted = TemplateManager.delete_template("email_drafter", dir_path=temp_dir)
    assert deleted is True
    assert not saved_file.exists()
    assert TemplateManager.get_template("email_drafter", dir_path=temp_dir) is None


def test_load_template_agent_helper():
    """Verify load_template_agent loads a functional LowCodeAgent."""
    agent = load_template_agent("summarize_meeting_notes")
    assert isinstance(agent, LowCodeAgent)
    assert agent.config.name == "Summarize Meeting Notes"


def test_openclaw_skill_catalog():
    """Verify list_available_skills for OpenClaw omnichannel routing."""
    skills = list_available_skills()
    skill_ids = [s["id"] for s in skills]
    assert "summarize_meeting_notes" in skill_ids
    assert "weekly_report_jira_notion" in skill_ids
    assert "generate_sql_from_nl" in skill_ids


def test_mcp_template_tools():
    """Verify FastMCP tools list_skill_templates and execute_skill_template."""
    tools_list_json = list_skill_templates()
    parsed = json.loads(tools_list_json)
    assert isinstance(parsed, list)
    ids = [item["id"] for item in parsed]
    assert "summarize_meeting_notes" in ids
    assert "generate_sql_from_nl" in ids

    # Test invalid template execution returns clear error message
    err_res = execute_skill_template("non_existent_skill_template_id")
    assert "was not found" in err_res
