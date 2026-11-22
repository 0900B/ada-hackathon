#!/usr/bin/env sh
# The pitch video's sound: a Slovenian 112 caller (phone line) and a crew member (radio), synthesized
# with Microsoft's neural TTS via edge-tts (fictional text), plus a short ring. Output:
# media/out/pitch-raw/audio/{ring,caller_phone,crew_radio}.wav (48 kHz).
#   uv venv /tmp/tts && uv pip install --python /tmp/tts edge-tts
#   TTS=/tmp/tts/Scripts/edge-tts sh media/pitch-video/make-audio.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
FF="$HERE/../tools/node_modules/ffmpeg-static/ffmpeg.exe"
[ -x "$FF" ] || FF="$HERE/../tools/node_modules/ffmpeg-static/ffmpeg"
TTS="${TTS:-edge-tts}"
OUT="$HERE/../out/pitch-raw/audio"
mkdir -p "$OUT" && cd "$OUT"
q() { "$FF" -hide_banner -loglevel error -y "$@"; }

"$TTS" --voice sl-SI-PetraNeural --rate=+8% --pitch=+15Hz \
  --text "Halo, reševalci? Mož se je zgrudil na dvorišču, ne diha! Nihče ne dela oživljanja. Naslov je Šmarska cesta 3, Škofljica." \
  --write-media caller.mp3
"$TTS" --voice sl-SI-RokNeural --text "Vozilo je obstalo. Oprema je še v njem." --write-media crew.mp3

# phone line: 300-3400 Hz band, compression, a little line noise
q -i caller.mp3 -af "highpass=f=320,lowpass=f=3300,acompressor=threshold=-20dB:ratio=4:attack=5:release=80,volume=2.0" -ar 48000 -ac 1 caller_phone_dry.wav
q -i caller_phone_dry.wav -f lavfi -i "anoisesrc=color=pink:amplitude=0.012:sample_rate=48000" \
  -filter_complex "[1]highpass=f=300,lowpass=f=3400[n];[0][n]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.9" -ar 48000 -ac 1 caller_phone.wav
# radio: narrower band, harder compression, squelch beeps
q -i crew.mp3 -af "highpass=f=400,lowpass=f=2800,acompressor=threshold=-24dB:ratio=6:attack=3:release=60,volume=2.5,alimiter=limit=0.9" -ar 48000 -ac 1 crew_radio_dry.wav
q -f lavfi -i "sine=f=1400:d=0.12:sample_rate=48000" -af "volume=0.25" -ar 48000 -ac 1 beep.wav
q -i beep.wav -i crew_radio_dry.wav -i beep.wav -f lavfi -i "anoisesrc=color=white:amplitude=0.01:sample_rate=48000:d=0.2" \
  -filter_complex "[3]highpass=f=400,lowpass=f=2800[sq];[0][1][sq][2]concat=n=4:v=0:a=1" -ar 48000 -ac 1 crew_radio.wav
# ring: 440+480 Hz, 1 s on / 0.5 s off, twice
q -f lavfi -i "sine=f=440:d=1.0:sample_rate=48000" -f lavfi -i "sine=f=480:d=1.0:sample_rate=48000" \
  -filter_complex "[0][1]amix=inputs=2,volume=0.5,afade=t=in:d=0.02,afade=t=out:st=0.95:d=0.05[r];anullsrc=r=48000:cl=mono:d=0.5[s];[r][s]concat=n=2:v=0:a=1,aloop=loop=1:size=72000" \
  -ar 48000 -ac 1 ring.wav
ls -la "$OUT"
