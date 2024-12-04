# %%
import re
import sys
from dataclasses import dataclass

from tap import Tap


@dataclass(frozen=True)
class BaseArgs:
    in_path: str
    out_dir: str
    out_file: str


class MainArgs(Tap, BaseArgs):
    in_path: str  # Path to input file
    out_dir: str  # Directory for output files
    out_file: str = "output.md"  # Name of output file


main_args = BaseArgs(
    in_path="test/fixture/scientific_article_example.md",
    out_dir="test/output",
    out_file="output.md",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    main_args = MainArgs().parse_args()


import asyncio
from pathlib import Path
from typing import Sequence

from chonkie import SDPMChunker
from llama_index.core import SimpleDirectoryReader
from llama_index.core.chat_engine import SimpleChatEngine
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
from llama_index.embeddings.voyageai import VoyageEmbedding
from llama_index.llms.openrouter import OpenRouter
from llama_index.utils.workflow import (
    draw_all_possible_flows,
    draw_most_recent_execution,
)
from rapidfuzz import fuzz

from media_processing import event_logging

event_logging.start()


# %%
@dataclass(frozen=True)
class Section:
    level: int
    title: str | None
    content: str

    @classmethod
    def from_text(cls, text: str) -> "Section":
        lines = text.split("\n\n", 1)
        title = lines[0]
        content = lines[1] if len(lines) > 1 else ""

        match title.split():
            case []:
                level, clean_title = 1, title
            case [first, *rest] if any(char.isdigit() for char in first):
                level, clean_title = first.count(".") + 1, " ".join(rest)
            case _:
                level, clean_title = 1, title.strip()

        return cls(level=level, title=clean_title, content=content)

    @classmethod
    def from_documents(cls, docs: Sequence[Document]) -> "list[Section]":
        texts = [
            cleaned
            for doc in docs
            for cleaned in [
                re.sub(r"\n{3,}", "\n\n", re.sub("\r\n", "\n", doc.text.strip()))
            ]
            if len(cleaned) > 0
        ]
        return [Section.from_text(text) for text in texts]


@dataclass(frozen=True)
class ResearchArticle:
    primary_sections: list[Section]
    supportive_sections: list[Section]

    @classmethod
    def from_sections(cls, sections: list[Section]) -> "ResearchArticle":
        SUPPORTIVE_MATERIAL_KEYWORDS = [
            "ccs concepts",
            "keywords",
            "references",
            "acknowledgments",
        ]

        primary = []
        supportive = []

        for section in sections:
            if any(
                fuzz.partial_ratio(
                    keyword.lower(), section.title.lower() if section.title else ""
                )
                >= 80
                for keyword in SUPPORTIVE_MATERIAL_KEYWORDS
            ):
                supportive.append(section)
            else:
                primary.append(section)

        return cls(primary_sections=primary, supportive_sections=supportive)


article = ResearchArticle.from_sections(
    Section.from_documents(
        SimpleDirectoryReader(input_files=[main_args.in_path]).load_data()
    )
)
example_article = ResearchArticle.from_sections(
    Section.from_documents(
        SimpleDirectoryReader(
            input_files=[
                "test/fixture/markdown_to_slideshow/source_scientific_article_example.md"
            ]
        ).load_data()
    )
)


# %%
def triple_quote(content: str) -> str:
    return f'"""\n{content}\n"""'


def create_conversion_prompt(example_text: str, example_slide: str, text: str) -> str:
    return (
        "I have the following academic text:\n"
        f"{triple_quote(example_text)}\n"
        "For reference, here's how it was converted into slide format:\n"
        f"{triple_quote(example_slide)}\n"
        "Please convert the following academic text into a concise, high-level overview using a similar format. The slide content should be brief, and the speaker notes should reference the slide content without adding introductory or concluding remarks.\n"
        f"{triple_quote(text)}\n"
    )


splitter = SentenceSplitter()
llm = OpenRouter(
    max_tokens=1920,
    context_window=16384,
    model="meta-llama/llama-3.1-8b-instruct",
)

llm_smart = OpenRouter(
    max_tokens=1920,
    context_window=16384,
    model="neversleep/llama-3.1-lumimaid-70b",
)

llm_smartest = OpenRouter(
    max_tokens=1920,
    context_window=16384,
    model="anthropic/claude-3.5-sonnet",
)


overview_request = ChatMessage(
    role=MessageRole.USER,
    content=create_conversion_prompt(
        "\n\n".join(
            f"# {s.title}\n\n{s.content}" for s in example_article.primary_sections[:2]
        ),
        """
# Overview

- Investigates "similarity effect" in VR environments
  - People are more influenced by similar others
- Examines impact of avatar appearance similarity on:
  - User comfort
  - Perceived persuasiveness
- Combine quantitative and qualitative data from 25 participants

<!--
This study explores how the "similarity effect" - our tendency to be influenced by those who resemble us - manifests in VR communication. It specifically examines how varying degrees of avatar similarity affect users' comfort and perception of others' persuasiveness. The research uses a mixed-methods approach, combining quantitative and qualitative data from 25 participants interacting with avatars of three similarity levels. This work may help understanding social dynamics in VR and has implications for designing effective VR communication platforms.
-->
    """,
        "\n\n".join(
            f"# {s.title}\n\n{s.content}" for s in article.primary_sections[:2]
        ),
    ),
)
chat_engine = SimpleChatEngine.from_defaults(
    llm=llm_smartest,
    system_prompt="Write the next reply in the conversation. Use markdown for formatting when appropriate. Be concise yet helpful. Offer direct answers when possible. Ask questions if needed. Explain complex concepts with brief examples. Avoid repetition and strive to add value with each response.",
)
overview_response = chat_engine.chat(overview_request)
print(overview_response.message.content)
slide_1_request = ChatMessage(
    role=MessageRole.USER,
    content="Continue to write the next slide.",
)
slide_1_response = chat_engine.chat(slide_1_request)
print(slide_1_response.message.content)


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
    output_path = Path(args.out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    full_text = f"\n{"-" * 10}\n".join(x for x in slides)

    with open(output_path / args.out_file, "w", encoding="utf-8") as f:
        f.write(full_text)


# %%
if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
        await main(main_args)  # type: ignore  # noqa: F704
    except RuntimeError:
        asyncio.run(main(main_args))

# %%
