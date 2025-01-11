import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from llama_index.core.schema import Document
from rapidfuzz import fuzz


class SectionType(StrEnum):
    pass


class CommonPrimarySectionType(SectionType):
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"


class SupportiveSectionType(SectionType):
    CCS_CONCEPTS = "ccs concepts"
    KEYWORDS = "keywords"
    REFERENCES = "references"
    ACKNOWLEDGMENTS = "acknowledgments"


@dataclass(frozen=True)
class Section:
    level: int
    title: str | None
    content: str

    @classmethod
    def from_text(cls, text: str) -> Self:
        match text.split("\n\n", 1):
            case [title, content]:
                pass
            case [title]:
                content = ""
                pass
            case _:
                raise ValueError("Unexpected section text format.")
        match title.split():
            case []:
                level, clean_title = 1, title
            case [first, *rest] if any(char.isdigit() for char in first):
                level, clean_title = first.count(".") + 1, " ".join(rest)
            case _:
                level, clean_title = 1, title.strip()
        return cls(level=level, title=clean_title, content=content)

    def matches_type(self, section_type: SectionType) -> bool:
        return (
            fuzz.partial_ratio(
                section_type.lower(), self.title.lower() if self.title else ""
            )
            >= 80
        )

    def to_markdown(self) -> str:
        return f"# {self.title}\n\n{self.content}"


def sections_from_documents(docs: Iterable[Document]) -> "list[Section]":
    return [
        Section.from_text(cleaned)
        for doc in docs
        for cleaned in [
            re.sub(r"\n{3,}", "\n\n", re.sub("\r\n", "\n", doc.text.strip()))
        ]
        if len(cleaned) > 0
    ]


def markdown_from_sections(sections: Iterable[Section]) -> str:
    return "\n\n".join(s.to_markdown() for s in sections)


@dataclass(frozen=True)
class ResearchArticle:
    primary_sections: Sequence[Section]
    supportive_sections: Sequence[Section]

    @classmethod
    def from_sections(cls, sections: Iterable[Section]) -> Self:
        primary = []
        supportive = []

        for section in sections:
            (
                supportive
                if any(section.matches_type(t) for t in SupportiveSectionType)
                else primary
            ).append(section)

        return cls(primary_sections=primary, supportive_sections=supportive)

    def get_primary_opening_sections(self) -> list[Section]:
        sections: list[Section] = []
        for section in self.primary_sections:
            sections.append(section)
            if section.matches_type(CommonPrimarySectionType.INTRODUCTION):
                break

        return sections


def get_sections_until_threshold(
    all_sections: Sequence[Section], min_chars: int, level_1_lookahead_chars: int
) -> list[Section]:
    sections: Sequence[Section] = []
    total_chars = 0
    for section in all_sections:
        if (section.level == 1 and len(sections) > 0) or total_chars >= min_chars:
            break
        sections.append(section)
        total_chars += len(section.title or "") + len(section.content)

    rest_sections = all_sections[len(sections) :]
    chars_until_level1 = 0
    for i, next_section in enumerate(rest_sections):
        if chars_until_level1 > level_1_lookahead_chars:
            break
        if next_section.level == 1:
            sections += rest_sections[:i]
            break
        chars_until_level1 += len(next_section.title or "") + len(next_section.content)
    return sections
