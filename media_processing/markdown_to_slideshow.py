# %%
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from tap import Tap


@dataclass(frozen=True)
class BaseArgs:
    input_path: str
    example_source_path: str
    example_overview_slide_path: str
    output_dir: str
    output_filename: str


class MainArgs(Tap, BaseArgs):
    input_path: str  # Path to input file
    output_dir: str  # Directory for output files
    output_filename: str = "output.md"  # Name of output file
    example_source_path: str  # Path to example source text
    example_overview_slide_path: str  # Path to example slide format


main_args = BaseArgs(
    input_path="test/fixture/scientific_article_markdown_2.md",
    example_source_path="test/fixture/scientific_article_markdown_1.md",
    example_overview_slide_path="test/fixture/markdown_to_slideshow/scientific_article_1_overview_slide.md",
    output_dir="test/output",
    output_filename="output.md",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    main_args = MainArgs().parse_args()


import asyncio
import os
from pathlib import Path
from typing import Sequence

from chonkie import SDPMChunker
from llama_index.core import SimpleDirectoryReader
from llama_index.core.chat_engine import SimpleChatEngine
from llama_index.core.chat_engine.types import AgentChatResponse
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document
from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)
from llama_index.llms.openai_like import OpenAILike
from llama_index.llms.openrouter import OpenRouter
from llama_index.utils.workflow import (
    draw_all_possible_flows,
    draw_most_recent_execution,
)
from rapidfuzz import fuzz

from media_processing import event_logging

event_logging.start()


# %%
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
    def from_text(cls, text: str) -> "Section":
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

    def matches_type(self, type: SectionType) -> bool:
        return (
            fuzz.partial_ratio(type.lower(), self.title.lower() if self.title else "")
            >= 80
        )


def sections_from_documents(docs: Sequence[Document]) -> "list[Section]":
    return [
        Section.from_text(cleaned)
        for doc in docs
        for cleaned in [
            re.sub(r"\n{3,}", "\n\n", re.sub("\r\n", "\n", doc.text.strip()))
        ]
        if len(cleaned) > 0
    ]


def markdown_from_sections(sections: "Iterable[Section]") -> str:
    return "\n\n".join(f"# {s.title}\n\n{s.content}" for s in sections)


@dataclass(frozen=True)
class ResearchArticle:
    primary_sections: list[Section]
    supportive_sections: list[Section]

    @classmethod
    def from_sections(cls, sections: Iterable[Section]) -> "ResearchArticle":
        primary = []
        supportive = []

        for section in sections:
            (
                supportive
                if any(section.matches_type(type) for type in SupportiveSectionType)
                else primary
            ).append(section)

        return cls(primary_sections=primary, supportive_sections=supportive)

    def get_primary_opening_sections(self) -> Iterable[Section]:
        for section in self.primary_sections:
            yield section
            if section.matches_type(CommonPrimarySectionType.INTRODUCTION):
                break


def get_sections_until_threshold(
    all_sections: Sequence[Section], min_chars: int, level_1_lookahead_chars: int
) -> list[Section]:
    sections = []
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


article = ResearchArticle.from_sections(
    sections_from_documents(
        SimpleDirectoryReader(input_files=[main_args.input_path]).load_data()
    )
)
example_article = ResearchArticle.from_sections(
    sections_from_documents(
        SimpleDirectoryReader(input_files=[main_args.example_source_path]).load_data()
    )
)


# %%
def triple_quote(content: str) -> str:
    return f'"""\n{content}\n"""'


def overview_request_prompt(example_text: str, example_slide: str, text: str) -> str:
    return (
        "I have the following academic text:\n"
        f"{triple_quote(example_text)}\n"
        "For reference, here's how it was converted into slide format:\n"
        f"{triple_quote(example_slide)}\n"
        "Please convert the following academic text into a concise, high-level overview using a similar format. The slide content should be brief, and the speaker notes should reference the slide content without adding introductory or concluding remarks.\n"
        f"{triple_quote(text)}\n"
    )


def source_context_prompt(text: str) -> str:
    return f"I have the following academic text:\n{triple_quote(text)}"


def slide_context_prompt(current_slides: str) -> str:
    return f"These are the current slides:\n{triple_quote(current_slides)}"


splitter = SentenceSplitter()
api_key = os.environ["OPENROUTER_API_KEY"]
llm = OpenRouter(
    max_tokens=1920,
    context_window=16384,
    model="meta-llama/llama-3.1-8b-instruct",
    # api_base="https://openrouter.ai/api/v1",
    # api_key=api_key,
    # api_version="v1",
)

llm_smart = OpenRouter(
    max_tokens=1920,
    context_window=16384,
    model="neversleep/llama-3.1-lumimaid-70b",
    # api_base="https://openrouter.ai/api/v1",
    # api_key=api_key,
    # api_version="v1",
)

llm_smartest = OpenAILike(
    max_tokens=1920,
    context_window=16384,
    model="anthropic/claude-3.5-sonnet",
    api_base="https://openrouter.ai/api/v1",
    api_key=api_key,
    api_version="v1",
    temperature=0.08,
)

system_prompt = ChatMessage(
    role=MessageRole.SYSTEM,
    content="Write the next reply in the conversation. Use markdown for formatting when appropriate. Be concise yet helpful. Offer direct answers when possible. Ask questions if needed. Explain complex concepts with brief examples. Avoid repetition and strive to add value with each response.",
)
with open(main_args.example_overview_slide_path, encoding="utf-8") as f:
    example_slide = f.read()

overview_request = ChatMessage(
    role=MessageRole.USER,
    content=overview_request_prompt(
        markdown_from_sections(example_article.get_primary_opening_sections()),
        example_slide,
        markdown_from_sections(article.get_primary_opening_sections()),
    ),
)
chat_context = [system_prompt, overview_request]
overview_response = llm_smartest.chat(chat_context)
next_slide_prompt = """
Write the next slide. The slide content should be brief. The speaker notes should reference the slide content, not the slide itself, without adding introductory or concluding remarks. At the end of the speaker notes, write down:
1. The start and end of the range of text referenced (in JSON format)
2. A boolean indicating if this is the last available text to reference

Format:
{
    "start": "...",
    "end": "...",
    "isComplete": true/false
}
Following the text in chronological order. Do not skip any part.
"""
next_section_index = [
    i
    for i, s in enumerate(article.primary_sections)
    if s.matches_type(CommonPrimarySectionType.INTRODUCTION)
][0]
get_sections_until_threshold(article.primary_sections[next_section_index:], 2000, 750)

source_context = source_context_prompt("")
slide_context = slide_context_prompt("")


# %%
class SlideCreateEvent(Event):
    index: int
    section: Section


class SlideCreatedEvent(Event):
    index: int
    content: str


class SlideShowWorkflow(Workflow):
    @step
    async def start(self, ctx: Context, ev: StartEvent) -> SlideCreateEvent | None:
        await ctx.set("slide_count", len(ev.sections))
        for i, section in enumerate(ev.sections):
            section: Section
            interval = 1 / 30
            await asyncio.sleep(interval)
            ctx.send_event(SlideCreateEvent(index=i, section=section))

    @step
    async def make_slide(self, ev: SlideCreateEvent) -> SlideCreatedEvent:
        print("make slide")
        message = ChatMessage(
            role=MessageRole.USER,
            content="For the following text, give a slide page title, describe it in a short bullet points"
            f', and write the corresponding speaker note: """{ev.section.content}"""',
        )
        print(message)
        response = await llm.achat([message])
        print(f'{ev.index}:\n"""{response}"""')
        return SlideCreatedEvent(index=ev.index, content=str(response.message.content))

    @step
    async def collect_slides(
        self, ctx: Context, ev: SlideCreatedEvent
    ) -> StopEvent | None:
        print("slide made")
        events = ctx.collect_events(
            ev, [SlideCreatedEvent] * await ctx.get("slide_count")
        )
        if events is None:
            return None
        slides_dict = {
            x.index: str(x.content) for x in events if isinstance(x, SlideCreatedEvent)
        }
        slides = []
        for i in range(max(slides_dict.keys())):
            slides.append(slides_dict[i])
        return StopEvent(result=slides)


slides: list[str] = []
workflow = SlideShowWorkflow(timeout=60)
# draw_all_possible_flows(workflow)


async def main(args: BaseArgs):
    global slides
    slides = await workflow.run(sections=primary_sections)
    # draw_most_recent_execution(workflow)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    full_text = f"\n{"-" * 10}\n".join(x for x in slides)

    with open(output_dir / args.output_filename, "w", encoding="utf-8") as f:
        f.write(full_text)


# %%
if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
        await main(main_args)  # type: ignore  # noqa: F704
    except RuntimeError:
        asyncio.run(main(main_args))

# %%
