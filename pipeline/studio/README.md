# Studio: full videos and shorts on smaug

`pipeline/studio.py` makes one landscape video (1920×1080) and cuts it into vertical shorts (1080×1920, 50 s or less each). It publishes all of them on the NAS at `http://192.168.1.30:9103`, where each video can be watched or downloaded. Every model runs on smaug, and nothing is uploaded anywhere else.

| Use case | Command | Audio | Pictures |
|----------|---------|-------|----------|
| Hindi household reel, AI family members talk on camera | `ghar` | Indic Parler-TTS Hindi (Divya, Rani, Rohit, Aman) | a photoreal portrait of whoever is speaking, slowly zooming; Hinglish captions |
| Nursery rhyme, sung | `rhyme` | ACE-Step 1.5 sings your lyrics | 3D cartoon |
| Short creepy story | `scary` | Kokoro `bm_george` | dark cinematic |
| Did-you-know facts | `facts` | Kokoro `am_michael` | documentary photo |
| 20-question rapid-fire reel | `quiz` | Kokoro `af_bella` + ding | none: numbered boxes that tick green; split into Part 1, Part 2… of 50 s or less |

There are three ways to give it a script:

```bash
python studio.py rhyme --script /work/in/twinkle.txt   # your words, used exactly as written
python studio.py facts --topic "space"
python studio.py scary                                 # Ollama picks a topic from what is popular on Reddit now
python studio.py quiz --topic "space" --draft          # writes /work/in/quiz-<run>.txt: check it, then --script it
```

For `facts`, `quiz` and `ghar`, write a draft first. A `ghar` draft is JSON: edit `text` (the Hinglish caption) and `hi` (the same line in Devanagari, read by the voice) together. A quiz script is a `# title` line followed by one `question | answer` line per question.

## The pipeline

1. **Script.** Ollama (`gemma3:12b`, about 3 minutes per script) writes the script, unless you passed `--script`. It then writes one picture prompt per scene, plus a title, a description and hashtags. Afterwards the model is unloaded so the GPU is free.
2. **Audio.** Kokoro-82M reads each scene, which gives exact caption timing. For `rhyme`, ACE-Step 1.5 sings the whole song, and faster-whisper finds where the vocals start and end.
3. **Pictures.** Stable Diffusion 1.5 with the LCM LoRA draws one 768×512 still per scene in 6 steps. It fits the 4 GB GTX 1050.
4. **Video.** ffmpeg adds a Ken Burns zoom to each still, lays them over the audio and burns in the captions. Each short shows the scene on a blurred background with large captions.
5. **Publish.** Files go to `/mnt/ssd-ext/amrit/data/studio/public/<run>/`, together with an `index.html` page. nginx serves that folder on port 9103.

## Setup and running: one file

`studio.sh` does everything. Run it from any laptop on the home network that can SSH into smaug as `keeper`; it logs in and runs itself there. You can also run it on smaug directly.

```bash
curl -fsSLO https://raw.githubusercontent.com/kharedevansh11/Production-House-/studio-pipeline/pipeline/studio/studio.sh

bash studio.sh                                 # first time: install and start everything (20-40 min); re-run to update
bash studio.sh quiz --topic "human body"       # make a video; prints the links when done
bash studio.sh ghar --draft                    # write a Hindi household scene to check first
bash studio.sh ghar --script /work/in/ghar-<run>.json
bash studio.sh status                          # what is running, latest log lines
```

On the first run it asks once for a free Hugging Face token, which the Hindi voice model needs. Accept the terms at https://huggingface.co/ai4bharat/indic-parler-tts, then create a "read" token at https://huggingface.co/settings/tokens. The token is stored in `pipeline/studio/.env`, which git ignores.

Renders run in a detached container, so closing the SSH window does not stop them. Everything is listed at `http://192.168.1.30:9103`. Drafts are saved in `/mnt/ssd-ext/amrit/data/studio/work/in/` on smaug.


## Limits of this hardware

- **`ghar` takes a while.** Indic Parler-TTS runs on the CPU: expect roughly 10–20 minutes per reel.
- **Faces are generated, not real people.** Instagram asks for an "AI info" label on realistic synthetic people, so turn it on when posting.

- **No text-to-video model.** Wan 2.2 and LTX-Video need at least 6–8 GB of VRAM, and the GTX 1050 has 4 GB. Motion comes from animated stills, which is also how most rhyme channels are made. If the GPU is upgraded to 8 GB or more, `media.paint` and `media.scene_clip` are the two functions to replace with Wan 2.2 TI2V-5B.
- **ACE-Step runs on the CPU.** Its image is built on CUDA 12.8, and that build has no kernels for the GTX 1050. A 1–2 minute song may take tens of minutes. Expect this to be the slowest step.
- **RAM is 15 GB.** Ollama is unloaded before the pictures are drawn. Don't run two jobs at once.
- If the pictures come out black, set `studio.image_dtype: float32` in `config.yaml`.

## Ports and names

`amrit-studio-web` uses port 9103, the next free sandbox port. Kokoro and ACE-Step are reachable only on the `amrit_sandbox` network. Nothing in the roommate stack is touched.
