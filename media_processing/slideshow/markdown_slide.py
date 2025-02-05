# %%
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# %%
from itertools import chain
from typing import ClassVar, Self

import regex
from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_it.tree import SyntaxTreeNode
from mdformat.plugins import PARSER_EXTENSIONS
from mdformat.renderer import MDRenderer
from mdit_py_plugins.front_matter import front_matter_plugin
from more_itertools import intersperse

from media_processing.prompt import triple_quote


class JsonObjectString(str):
    pass


@dataclass(frozen=True)
class ContentNode:
    node: SyntaxTreeNode

    def to_segments(self) -> Sequence[str | JsonObjectString]:
        content: list[str | JsonObjectString] = []
        for node in self.node.walk():
            stripped = node.content.strip()
            json_object_pattern = r"{(?:[^{}]|(?R))*}"
            last_end = 0

            for match in regex.finditer(json_object_pattern, stripped):
                substr = stripped[last_end : match.start()]
                if len(substr) > 0:
                    content.append(substr)
                content.append(JsonObjectString(match.group()))
                last_end = match.end()

            if last_end < len(stripped):
                content.append(stripped[last_end:].strip())

        return content


@dataclass(frozen=True)
class MainContent(ContentNode):
    pass


@dataclass(frozen=True)
class Note(ContentNode):
    pass


@dataclass(frozen=True)
class Title(ContentNode):
    pass


@dataclass(frozen=True)
class FrontMatter(ContentNode):
    pass


def ensure_types(node_types: Iterable[str], node: SyntaxTreeNode):
    if all(node.type != n for n in node_types):
        raise ValueError(
            f"Unexpected node type {node.type}, expected one of {[*node_types]}"
        )

    return node


@dataclass(frozen=True)
class MarkdownSlide:
    title: Title
    main_contents: Sequence[MainContent]
    note: Note | None
    front_matter: FrontMatter | None

    parser: ClassVar[MarkdownIt] = MarkdownIt().use(front_matter_plugin)

    @classmethod
    def from_markdown(cls, markdown: str) -> Self:
        tree = SyntaxTreeNode(cls.parser.parse(f"---\n{markdown.strip("\n\r-")}"))
        first_node, second_node, *rest_nodes = tree
        expected_first = ensure_types(["front_matter", "hr"], first_node)
        front_matter = (
            FrontMatter(expected_first)
            if expected_first.type == "front_matter"
            else None
        )

        title = Title(node=ensure_types(["heading"], second_node))
        main_contents: Sequence[MainContent] = []
        note: Note | None = None
        for i, node in enumerate(rest_nodes):
            match node.type:
                case "paragraph" | "bullet_list" | "ordered_list":
                    main_contents.append(MainContent(node))
                case "html_block" if note is None:
                    if node.content[:4] == "<!--":
                        note = Note(node=node)
                        break
                    else:
                        raise ValueError("Unexpected non-comment html for note")
                case type:
                    raise ValueError(f"Unexpected node type {type} @ rest_nodes[{i}]")

        return cls(
            title=title,
            main_contents=main_contents,
            note=note,
            front_matter=front_matter,
        )

    @classmethod
    def render_tokens(cls, tokens: Iterable[Token]) -> str:
        return MDRenderer(parser=cls.parser).render(
            [*tokens],
            {
                "parser_extension": [
                    PARSER_EXTENSIONS["simple_breaks"],
                    PARSER_EXTENSIONS["frontmatter"],
                ]
            },
            {},
        )

    def to_tokens(self) -> list[Token]:
        nodes: list[SyntaxTreeNode] = []
        if self.front_matter is not None:
            nodes.append(self.front_matter.node)
        nodes.append(self.title.node)
        nodes += [c.node for c in self.main_contents]
        if self.note is not None:
            nodes.append(self.note.node)

        return [token for node in nodes for token in node.to_tokens()]

    def to_markdown(self) -> str:
        return self.render_tokens(self.to_tokens())


def slides_to_context_prompt(slides: Iterable[MarkdownSlide]) -> str:
    return f"These are the current slides:\n{triple_quote(MarkdownSlide.render_tokens(chain(
        *intersperse(MarkdownSlide.parser.parse("---"), [s.to_tokens() for s in slides])
    )))}"
