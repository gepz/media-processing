# %%
import sys
from dataclasses import dataclass

from tap import Tap

from media_processing.prompt import triple_quote


@dataclass(frozen=True)
class BaseArgs:
    input_path: str
    output_dir: str
    output_filename: str
    example_source_path: str
    example_overview_slide_path: str


class MainArgs(Tap, BaseArgs):
    input_path: str  # Path to input file
    output_dir: str  # Directory for output files
    output_filename: str = "output.md"  # Name of output file
    example_source_path: str  # Path to example source text
    example_overview_slide_path: str  # Path to example slide format


g_main_args = BaseArgs(
    input_path="test/fixture/scientific_article_markdown_2.md",
    example_source_path="test/fixture/scientific_article_markdown_1.md",
    example_overview_slide_path="test/fixture/markdown_to_slideshow/scientific_article_1_overview_slide.md",
    output_dir="test/output",
    output_filename="output.md",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    g_main_args = MainArgs().parse_args()


import asyncio
import os
import re
from collections.abc import Iterable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Self, cast

from llama_index.core import SimpleDirectoryReader
from llama_index.core.llms import LLM, ChatMessage, ChatResponse, MessageRole
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
from llama_index.llms.openrouter import OpenRouter
from llama_index.utils.workflow import (
    draw_all_possible_flows,
    draw_most_recent_execution,
)
from rapidfuzz import fuzz

import media_processing.slidesshow.markdown_slide as ms
import media_processing.slidesshow.slide_response as sr
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


g_article = ResearchArticle.from_sections(
    sections_from_documents(
        SimpleDirectoryReader(input_files=[g_main_args.input_path]).load_data()
    )
)
g_example_article = ResearchArticle.from_sections(
    sections_from_documents(
        SimpleDirectoryReader(input_files=[g_main_args.example_source_path]).load_data()
    )
)


# %%
ms.MarkdownSlide.parser.parse("""---
valid-front-matter: true
---
""")


# %%
def source_context_prompt(text: str) -> str:
    return f"I have the following academic text:\n{triple_quote(text)}"


def get_response_content(res: ChatResponse):
    for choice in cast(Any, res.raw).choices:
        if hasattr(choice, "error"):
            raise ValueError(f"Error: {choice.error}")
    if res.message.content is None:
        raise ValueError("message is None")
    return res.message.content


def conversion_example_prompt(example_text: str, example_slide: str) -> str:
    return (
        f"{source_context_prompt(example_text)}\n"
        "For reference, here's how it was converted into slide format:\n"
        f"{triple_quote(example_slide)}"
    )


def overview_request_prompt(example_text: str, example_slide: str, text: str) -> str:
    return (
        f"{conversion_example_prompt(
            example_text=example_text, example_slide=example_slide
        )}\n"
        + "Please convert the following academic text into a concise, high-level overview using a similar format. The slide content should be brief, and the speaker notes should reference the slide content without adding introductory or concluding remarks. Stop output after the JSON.\n"
        f"{triple_quote(text)}"
    )


def expand_slice(s: slice, length: int) -> range:
    return range(length)[s]


def merge_slice_ranges(slices: Iterable[slice], length: int) -> list[int]:
    return [*dict.fromkeys(i for s in slices for i in expand_slice(s, length))]


g_splitter = SentenceSplitter()
g_api_key = os.environ["OPENROUTER_API_KEY"]
g_llm_smart = OpenRouter(
    max_tokens=1920,
    context_window=16384,
    model="neversleep/llama-3.1-lumimaid-70b",
    # api_base="https://openrouter.ai/api/v1",
    # api_key=api_key,
    # api_version="v1",
    temperature=0.08,
)

g_llm_smartest = OpenRouter(
    max_tokens=1920,
    context_window=16384,
    model="anthropic/claude-3.5-sonnet",
    api_base="https://openrouter.ai/api/v1",
    api_key=g_api_key,
    api_version="v1",
    temperature=0.08,
    additional_kwargs={
        "extra_body": {"provider": {"order": ["Anthropic"], "allow_fallbacks": False}}
    },
)


with open(g_main_args.example_overview_slide_path, encoding="utf-8") as g_f:
    g_example_slide = g_f.read()

g_system_prompt = ChatMessage(
    role=MessageRole.SYSTEM,
    content="Write the next reply in the conversation. Use markdown for formatting when appropriate. Be concise yet helpful. Offer direct answers when possible. Ask questions if needed. Explain complex concepts with brief examples. Avoid repetition and strive to add value with each response.",
)


def next_slide(
    llm: LLM,
    prior_chat_context: Iterable[ChatMessage],
    existing_slides: Sequence[ms.MarkdownSlide],
    source: Iterable[Section],
) -> sr.SlideResponse:
    source_context = source_context_prompt(markdown_from_sections(source))
    next_slide_prompt = """Write the single next slide. The slide content should be brief. The speaker notes should reference the slide content, not the slide itself, without adding introductory or concluding remarks. At the end of the speaker notes, write down:
1. The start and end of the range of text referenced (in JSON format)
2. A boolean indicating if this is basically the last available meaningful text to reference

JSON Format:
{
    "start": "Start of a sentence...",
    "end": "...end of a sentence.",
    "isComplete": true/false
}
Stop output after the JSON.
Following the text in chronological order. Do not skip any part."""

    chat_context = [
        *prior_chat_context,
        ChatMessage(role=MessageRole.USER, content=source_context),
        *(
            [
                ChatMessage(
                    role=MessageRole.USER,
                    content=ms.slides_to_context_prompt(
                        [
                            existing_slides[i]
                            for i in merge_slice_ranges(
                                [slice(0, 2), slice(-2, None)], len(existing_slides)
                            )
                        ]
                    ),
                )
            ]
            if len(existing_slides) > 0
            else []
        ),
        ChatMessage(role=MessageRole.USER, content=next_slide_prompt),
    ]

    return sr.SlideResponse.from_markdown(get_response_content(llm.chat(chat_context)))


g_opening_sections = g_article.get_primary_opening_sections()
g_overview_request = ChatMessage(
    role=MessageRole.USER,
    content=overview_request_prompt(
        markdown_from_sections(g_example_article.get_primary_opening_sections()),
        g_example_slide,
        markdown_from_sections(g_opening_sections),
    ),
)
g_prior_chat_context: list[ChatMessage] = [g_system_prompt, g_overview_request]
g_overview_slide_response = sr.SlideResponse.from_markdown(
    get_response_content(g_llm_smartest.chat(g_prior_chat_context))
)
g_prior_chat_context.append(
    ChatMessage(
        role=MessageRole.ASSISTANT,
        content=g_overview_slide_response.slide.to_markdown(),
    )
)
g_next_section_index = next(
    i
    for i, s in enumerate(g_article.primary_sections)
    if s.matches_type(CommonPrimarySectionType.INTRODUCTION)
)
g_source_sections = get_sections_until_threshold(
    g_article.primary_sections[g_next_section_index:], 2000, 750
)
g_existing_slides: list[ms.MarkdownSlide] = []
g_last_level1_title: str | None = None

while g_next_section_index < len(g_article.primary_sections):
    print(g_next_section_index)
    for g_section in g_source_sections:
        if g_section.level == 1 and g_last_level1_title != g_section.title:
            g_last_level1_title = g_section.title
            g_existing_slides.append(
                ms.MarkdownSlide.from_markdown(f"# {g_section.title}")
            )

    g_next_slide = next_slide(
        llm=g_llm_smartest,
        prior_chat_context=g_prior_chat_context,
        existing_slides=g_existing_slides,
        source=g_source_sections,
    )
    g_existing_slides.append(g_next_slide.slide)

    if g_next_slide.reference_status is None:
        raise ValueError("LLM did not respnod with reference status Json")
    if g_next_slide.reference_status.isComplete:
        g_next_section_index += len(g_source_sections)
        g_source_sections = get_sections_until_threshold(
            g_article.primary_sections[g_next_section_index:], 2000, 750
        )


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
        response = await g_llm_smartest.achat([message])
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


g_slides: list[str] = []
g_workflow = SlideShowWorkflow(timeout=60)
draw_all_possible_flows(g_workflow)


async def main(args: BaseArgs):
    global g_slides
    g_slides = await g_workflow.run(sections="primary_sections")
    draw_most_recent_execution(g_workflow)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    full_text = f"\n{"-" * 10}\n".join(x for x in g_slides)

    with open(output_dir / args.output_filename, "w", encoding="utf-8") as f:
        f.write(full_text)


# %%
if __name__ == "__main__":
    try:
        g_loop = asyncio.get_running_loop()
        await main(g_main_args)  # type: ignore  # noqa: F704
    except RuntimeError:
        asyncio.run(main(g_main_args))

# %%
