# %%
from IPython.display import Audio

from media_processing.mp3_from_tts import mp3_from_tts

Audio(
    b"".join(
        mp3_from_tts(
            "..//..//test audio",
            model="kokoro",
            voice="af_sarah",
            speed=1.0,
            base_url="http://localhost:8880/v1",
        )
    ),
)

# %%
