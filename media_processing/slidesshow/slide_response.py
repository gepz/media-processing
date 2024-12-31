# %%
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import chain
from typing import ClassVar, Self

import regex
from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_it.tree import SyntaxTreeNode
from mdformat.plugins import PARSER_EXTENSIONS
from mdformat.renderer import MDRenderer
from more_itertools import intersperse
from pydantic import BaseModel

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


class SlideReferenceStatus(BaseModel):
    start: str
    end: str
    isComplete: bool

    @classmethod
    def from_note(cls, note: Note) -> Self:
        return cls.model_validate_json(
            next(
                c
                for c in reversed(note.to_segments())
                if isinstance(c, JsonObjectString)
            )
        )


def ensure_types(node_types: Iterable[str], node: SyntaxTreeNode):
    if all(node.type != n for n in node_types):
        raise ValueError(
            f"Unexpected node type {node.type}, expected one of {[*node_types]}"
        )

    return node


@dataclass(frozen=True)
class SlideResponse:
    title: Title
    main_contents: Sequence[MainContent]
    note: Note
    reference_status: SlideReferenceStatus
    parser: ClassVar[MarkdownIt] = MarkdownIt()

    @classmethod
    def from_markdown(cls, markdown: str) -> Self:
        tree = SyntaxTreeNode(cls.parser.parse(markdown))
        stripped_children = tree.children[
            1 if tree.children[0].tag == "hr" else 0 : -1
            if tree.children[-1].tag == "hr"
            else None
        ]
        note = Note(node=ensure_types(["html_block"], stripped_children[-1]))
        if note.node.content[:4] != "<!--":
            raise ValueError("Unexpected non-comment element for note")
        return cls(
            title=Title(node=ensure_types(["heading"], stripped_children[0])),
            main_contents=[
                MainContent(node=ensure_types(["paragraph", "bullet_list"], c))
                for c in stripped_children[1:-1]
            ],
            note=note,
            reference_status=SlideReferenceStatus.from_note(note),
        )

    @classmethod
    def render_tokens(cls, tokens: Iterable[Token]) -> str:
        return MDRenderer(parser=cls.parser).render(
            [*tokens], {"parser_extension": [PARSER_EXTENSIONS["simple_breaks"]]}, {}
        )

    def to_tokens(self) -> list[Token]:
        return [
            token
            for node in [
                self.title.node,
                *[c.node for c in self.main_contents],
                self.note.node,
            ]
            for token in node.to_tokens()
        ]

    def to_markdown(self) -> str:
        return self.render_tokens(self.to_tokens())


# %%
def slides_to_context_prompt(slides: Iterable[SlideResponse]) -> str:
    return f"These are the current slides:\n{triple_quote(SlideResponse.render_tokens(chain(
        *intersperse(SlideResponse.parser.parse("---"), [s.to_tokens() for s in slides])
    )))}"
