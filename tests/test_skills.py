from pathlib import Path

import pytest
import yaml

from credito.skills import load_catalog, make_load_skill_tool

SKILLS = Path(__file__).resolve().parent.parent / "skills"


def test_catalogo_lista_as_duas_skills():
    catalog = load_catalog(SKILLS)
    assert catalog.startswith("- avaliar-portabilidade: ")
    assert "\n- plano-de-quitacao: " in catalog


def test_load_skill_devolve_as_instrucoes():
    tool = make_load_skill_tool(SKILLS)
    assert tool.name == "load_skill"
    assert "credito_save_plan" in tool.invoke({"name": "plano-de-quitacao"})


def test_load_skill_inexistente_vira_erro():
    text = make_load_skill_tool(SKILLS).invoke({"name": "investir"})
    assert text.startswith("erro:")
    assert "plano-de-quitacao" in text


@pytest.mark.parametrize("skill", sorted(SKILLS.glob("*/SKILL.md")), ids=lambda p: p.parent.name)
def test_frontmatter_da_skill(skill):
    front = yaml.safe_load(skill.read_text().split("---")[1])
    assert set(front) == {"name", "description"}
    assert front["name"] == skill.parent.name
    assert "Use quando" in front["description"]
