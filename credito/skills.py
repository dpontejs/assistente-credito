"""Skills carregadas sob demanda: catálogo no system prompt e ferramenta load_skill (padrão do nb13)."""

from __future__ import annotations

from pathlib import Path

import yaml
from langchain_core.tools import BaseTool, tool


def _skills(skills_dir: Path) -> list[dict]:
    """Lê o frontmatter de cada skills/<nome>/SKILL.md."""
    paths = sorted(Path(skills_dir).glob("*/SKILL.md"))
    return [yaml.safe_load(path.read_text().split("---")[1]) for path in paths]


def load_catalog(skills_dir: Path) -> str:
    """Monta o catálogo 'nome: descrição' que vai no system prompt."""
    return "\n".join(f"- {skill['name']}: {skill['description']}" for skill in _skills(skills_dir))


def make_load_skill_tool(skills_dir: Path) -> BaseTool:
    """Cria a ferramenta que devolve as instruções completas de uma skill."""
    skills_dir = Path(skills_dir)

    @tool
    def load_skill(name: str) -> str:
        """Carrega as instruções completas de uma skill pelo nome, antes de executar a tarefa."""
        path = skills_dir / name / "SKILL.md"
        if not path.exists():
            names = ", ".join(skill["name"] for skill in _skills(skills_dir))
            return f"erro: skill {name} não existe; disponíveis: {names}"
        return path.read_text().split("---", 2)[2].strip()

    return load_skill
