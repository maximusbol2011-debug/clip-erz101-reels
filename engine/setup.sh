#!/bin/bash
# Installs what the reel engine needs in a fresh cloud container (about 1 minute).
set -e
pip install -q kokoro-onnx soundfile numpy pillow >/dev/null 2>&1
mkdir -p /opt/kokoro /opt/fonts /opt/ttscache
cd /opt/kokoro
[ -s kokoro-v1.0.onnx ] || curl -sSL -o kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
[ -s voices-v1.0.bin ] || curl -sSL -o voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
cd /opt/fonts
G=https://raw.githubusercontent.com/google/fonts/main/ofl
curl -sSL -o Anton-Regular.ttf $G/anton/Anton-Regular.ttf
curl -sSL -o BebasNeue-Regular.ttf $G/bebasneue/BebasNeue-Regular.ttf
curl -sSL -o ArchivoBlack-Regular.ttf $G/archivoblack/ArchivoBlack-Regular.ttf
curl -sSL -o Montserrat.ttf "$G/montserrat/Montserrat%5Bwght%5D.ttf"
curl -sSL -o Caveat.ttf "$G/caveat/Caveat%5Bwght%5D.ttf"
curl -sSL -o SpecialElite.ttf https://raw.githubusercontent.com/google/fonts/main/apache/specialelite/SpecialElite-Regular.ttf
which ffmpeg >/dev/null || (apt-get update -qq && apt-get install -y -qq ffmpeg)
echo "setup ok"
