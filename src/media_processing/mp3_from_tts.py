# %%
import sys
from dataclasses import dataclass

from tap import Tap


@dataclass(frozen=True)
class BaseArgs:
    in_path: str
    out_path: str
    model: str
    voice: str
    speed: float
    base_url: str | None


def validate_mp3_suffix(path: str) -> str:
    if not path.lower().endswith(".mp3"):
        raise ValueError(f"Output path must have .mp3 suffix, got: {path}")
    return path


class MainArgs(Tap):
    in_path: str  # Path to input file
    out_path: str  # Path to output file (must have .mp3 extension)
    model: str  # TTS model to use
    voice: str  # Voice to use for speech synthesis
    speed: float = 1.0  # Speech speed
    base_url: str | None = None  # API Base URL

    def process_args(self) -> None:
        super().process_args()
        self.out_path = validate_mp3_suffix(self.out_path)


g_main_args = BaseArgs(
    in_path="../../test/fixture/sentence.txt",
    out_path="../../test/output/speech.mp3",
    model="kokoro",
    voice="af_sarah",
    speed=1.0,
    base_url="http://localhost:8880/v1",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    g_main_args = MainArgs().parse_args()

# %%
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

from openai import OpenAI


def mp3_from_tts(
    text: str, model: str, voice: str, speed: float, base_url: str | None
) -> Generator[bytes, None, None]:
    if not text.strip():
        yield b""
        return

    with OpenAI(base_url=base_url).audio.speech.with_streaming_response.create(
        model=model,
        voice=cast(Any, voice),
        input=text,
        speed=speed,
        response_format="mp3",
    ) as response:
        yield from response.iter_bytes(chunk_size=4096)


if __name__ == "__main__":
    with open(g_main_args.in_path) as f:
        g_text = f.read()
    g_output_path = Path(g_main_args.out_path)
    g_output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(g_output_path, "wb") as f:
        for g_chunk in mp3_from_tts(
            text=g_text,
            model=g_main_args.model,
            voice=g_main_args.voice,
            speed=g_main_args.speed,
            base_url=g_main_args.base_url,
        ):
            f.write(g_chunk)
# %%
